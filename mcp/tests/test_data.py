from concurrent.futures import ThreadPoolExecutor

import duckdb
import pytest
from duckdb import col, fn

from exploration_mcp.data import AREAS, DataExplorer, Filters, write_dataset
from exploration_mcp.results import ResultStore, model_summary


# Independent fixture arithmetic, rather than repeating the SQL under test.
def sample_rate(area, year, month):
    return round(1 + 0.5 * AREAS.index(area) + 0.25 * (year - 2023) + 0.1 * (month % 2), 2)


def sample_rent(area, year, month):
    return 20000 + 1000 * AREAS.index(area) + 500 * (year - 2023) + 10 * month


def test_search_and_grouped_values(parquet):
    explorer = DataExplorer(parquet)
    assert explorer.describe()["row_count"] == 216
    result = explorer.search(Filters("千代田区", 2024, 2024, min_vacancy_rate_pct=1.8))
    expected = [m for m in range(1, 13) if sample_rate("千代田区", 2024, m) >= 1.8]
    assert [r["month"] for r in result["rows"]] == expected == [1, 3, 5, 7, 9, 11]
    assert result["rows"][0] == {
        "area": "千代田区",
        "year": 2024,
        "month": 1,
        "vacancy_rate_pct": sample_rate("千代田区", 2024, 1),
        "rent_yen_per_tsubo": sample_rent("千代田区", 2024, 1),
    }
    grouped = explorer.aggregate("year", Filters("千代田区"))
    assert [r["year"] for r in grouped["rows"]] == [2023, 2024, 2025]
    assert [r["month_count"] for r in grouped["rows"]] == [12, 12, 12]
    assert [r["mean_vacancy_rate_pct"] for r in grouped["rows"]] == [1.55, 1.8, 2.05]
    assert [r["mean_rent_yen_per_tsubo"] for r in grouped["rows"]] == [21065, 21565, 22065]
    assert grouped["synthetic"] is True


def test_period_month_and_area_order(parquet):
    explorer = DataExplorer(parquet)
    result = explorer.search(Filters(year_from=2025, month=12))
    assert [r["area"] for r in result["rows"]] == list(AREAS)
    assert {(r["year"], r["month"]) for r in result["rows"]} == {(2025, 12)}
    grouped = explorer.aggregate("area", Filters(year_from=2024, year_to=2025))
    assert [r["area"] for r in grouped["rows"]] == list(AREAS)
    assert {r["month_count"] for r in grouped["rows"]} == {24}
    months = explorer.aggregate("month", Filters("港区"))
    assert [r["month"] for r in months["rows"]] == list(range(1, 13))
    assert months["rows"][0]["min_rent_yen_per_tsubo"] == sample_rent("港区", 2023, 1)
    assert months["rows"][0]["max_rent_yen_per_tsubo"] == sample_rent("港区", 2025, 1)


def test_empty_and_bounded_results(parquet):
    explorer = DataExplorer(parquet)
    assert explorer.search(Filters("不存在"))["total_count"] == 0
    assert explorer.aggregate("year", Filters("不存在"))["rows"] == []
    result = explorer.search(Filters(), 200)
    assert result["total_count"] == 216
    assert result["returned_count"] == 200
    assert result["truncated"] is True
    assert explorer.search(Filters("　新宿区　"), 1)["total_count"] == 36


def test_describe_preserves_schema_metadata(parquet):
    description = DataExplorer(parquet).describe()
    types = {
        "area": "VARCHAR",
        "year": "BIGINT",
        "month": "BIGINT",
        "vacancy_rate_pct": "DOUBLE",
        "rent_yen_per_tsubo": "BIGINT",
    }
    assert [column["column_name"] for column in description["columns"]] == list(types)
    for column in description["columns"]:
        assert column == {
            "column_name": column["column_name"],
            "column_type": types[column["column_name"]],
            "null": "YES",
            "key": None,
            "default": None,
            "extra": None,
            "meaning": column["meaning"],
        }
        assert column["meaning"]
    assert description["areas"] == [{"area": name} for name in AREAS]
    assert description["synthetic"] is True
    assert "合成" in description["notice"]
    assert (description["first_year_month"], description["last_year_month"]) == (202301, 202512)


def _write_rows(path, rows):
    # Build independent input data, without using the query expressions under test.
    with duckdb.connect() as conn:
        conn.execute("""CREATE TABLE fixture (
            area VARCHAR, year BIGINT, month BIGINT,
            vacancy_rate_pct DOUBLE, rent_yen_per_tsubo BIGINT
        )""")
        conn.executemany("INSERT INTO fixture VALUES (?, ?, ?, ?, ?)", rows)
        write_dataset(conn, "fixture", path, synthetic=True)


def test_exact_matching_treats_special_characters_as_values(tmp_path):
    names = ["a%b", "axb", "a_b", "acb", "a'b", r"a\b", "' OR 1=1 --"]
    path = tmp_path / "literal.parquet"
    _write_rows(path, [(name, 2024, 1 + i, 1.0, 100) for i, name in enumerate(names)])
    explorer = DataExplorer(path)
    for i, name in enumerate(names):
        result = explorer.search(Filters(name))
        assert result["total_count"] == 1
        assert result["rows"][0]["month"] == 1 + i


def test_group_count_is_measured_before_limit(tmp_path):
    path = tmp_path / "groups.parquet"
    _write_rows(path, [(f"region-{i:03}", 2024, 1, 1.0, i) for i in range(205)])
    result = DataExplorer(path).aggregate("area", Filters())
    assert result["total_count"] == 205
    assert result["returned_count"] == 200
    assert result["count_unit"] == "groups"
    assert result["truncated"] is True
    assert [row["area"] for row in result["rows"]] == [f"region-{i:03}" for i in range(200)]


def test_aggregate_rounding_and_rate_bounds(tmp_path):
    path = tmp_path / "rounding.parquet"
    _write_rows(
        path,
        [("新宿区", 2024, m, rate, rent) for m, rate, rent in [(1, 1, 1), (2, 1, 2), (3, 2, 2)]],
    )
    result = DataExplorer(path).aggregate(
        "year", Filters(min_vacancy_rate_pct=1, max_vacancy_rate_pct=2)
    )
    assert result["rows"] == [
        {
            "year": 2024,
            "month_count": 3,
            "mean_vacancy_rate_pct": 1.33,
            "min_vacancy_rate_pct": 1,
            "max_vacancy_rate_pct": 2,
            "mean_rent_yen_per_tsubo": 2,
            "min_rent_yen_per_tsubo": 1,
            "max_rent_yen_per_tsubo": 2,
        }
    ]


def test_untrusted_values_cannot_become_sql(parquet):
    explorer = DataExplorer(parquet)
    assert explorer.search(Filters("' OR 1=1 --"))["total_count"] == 0
    with pytest.raises(ValueError):
        explorer.aggregate("year; COPY office_market TO '/tmp/leak'", Filters())
    for limit in [0, 201, True, "5"]:
        with pytest.raises(ValueError):
            explorer.search(Filters(), limit)
    for filters in [
        Filters(year_from=True),
        Filters(month=13),
        Filters(year_from=2025, year_to=2024),
        Filters(min_vacancy_rate_pct=-1),
        Filters(max_vacancy_rate_pct="5"),  # pyright: ignore[reportArgumentType]
        Filters(min_vacancy_rate_pct=3, max_vacancy_rate_pct=1),
    ]:
        with pytest.raises(ValueError):
            explorer.search(filters)
    assert explorer.describe()["row_count"] == 216


def test_unmarked_parquet_is_rejected(tmp_path):
    path = tmp_path / "plain.parquet"
    with duckdb.connect() as conn:
        conn.execute("COPY (SELECT 1 AS area) TO ? (FORMAT PARQUET)", [str(path)])
    with pytest.raises(ValueError, match="unsupported data file"):
        DataExplorer(path)


def test_connections_can_run_independently(parquet):
    explorer = DataExplorer(parquet)
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(
            executor.map(
                lambda name: explorer.search(Filters(name))["total_count"],
                ["千代田区", "新宿区", "渋谷区"],
            )
        )
    assert results == [36] * 3


def test_result_artifact_and_model_projection(parquet, tmp_path):
    result = DataExplorer(parquet).search(Filters(), 200)
    store = ResultStore(tmp_path / "results")
    preview = store.put(result)
    summary = model_summary(result, preview["result_id"])
    assert len(store.get(preview["result_id"])["rows"]) == 200
    assert len(preview["preview_rows"]) == 20
    assert len(summary["sample_rows"]) == 3
    assert summary["sample_truncated"]
    assert summary["notice"].startswith("合成データ。")
    assert "rows" not in summary
    with pytest.raises(ValueError):
        store.get("../secret")


def test_other_local_paths_are_blocked(parquet, tmp_path):
    secret = tmp_path / "outside.csv"
    secret.write_text("secret\nprivate\n")
    with pytest.raises(Exception, match="disabled by configuration"):
        DataExplorer(parquet)._query(lambda conn: conn.read_csv(str(secret)))


def test_duckdb_execution_is_interrupted(parquet):
    with pytest.raises(Exception, match="[Ii]nterrupt"):
        DataExplorer(parquet, timeout_seconds=0.01)._query(
            lambda conn: conn.table_function("range", [1_000_000_000]).aggregate(
                [fn("sum", fn("sqrt", col("range")))]
            )
        )
