from concurrent.futures import ThreadPoolExecutor
from statistics import mean

import duckdb
import pytest
from duckdb import col, fn

from exploration_mcp.data import DataExplorer, Filters
from exploration_mcp.results import ResultStore, model_summary

MUNICIPALITIES = ["品川区", "大田区", "川崎市幸区"]


def year(row):
    return int(row["取引時期"][:4])


def test_search_and_grouped_values_match_source(parquet, source_rows):
    explorer = DataExplorer(parquet)
    assert explorer.describe()["row_count"] == len(source_rows)
    expected = [
        int(r["取引価格（総額）"])
        for r in source_rows
        if r["市区町村名"] == "品川区"
        and year(r) == 2024
        and 40_000_000 <= int(r["取引価格（総額）"]) <= 50_000_000
    ]
    result = explorer.search(Filters("品川区", 2024, "", 40_000_000, 50_000_000), 200)
    assert [r["price_yen"] for r in result["rows"]] == expected
    assert result["total_count"] == len(expected) > 0
    grouped = explorer.aggregate("year", Filters("品川区"))
    for row in grouped["rows"]:
        prices = [
            int(r["取引価格（総額）"])
            for r in source_rows
            if r["市区町村名"] == "品川区" and year(r) == row["year"]
        ]
        assert row["transaction_count"] == len(prices)
        assert row["average_price_yen"] == round(mean(prices), 2)
        assert (row["min_price_yen"], row["max_price_yen"]) == (min(prices), max(prices))
    assert [r["year"] for r in grouped["rows"]] == [2023, 2024, 2025]


def test_property_type_filter_and_group(parquet, source_rows):
    explorer = DataExplorer(parquet)
    land = sum(r["種類"] == "宅地(土地)" for r in source_rows)
    # Full-width parentheses typed by a user are normalized to the source's ASCII form.
    assert explorer.search(Filters(property_type="宅地（土地）"), 1)["total_count"] == land
    grouped = explorer.aggregate("property_type", Filters())
    assert {r["property_type"]: r["transaction_count"] for r in grouped["rows"]} == {
        "宅地(土地)": land,
        "宅地(土地と建物)": len(source_rows) - land,
    }


def test_empty_and_bounded_results(parquet, source_rows):
    explorer = DataExplorer(parquet)
    assert explorer.search(Filters("不存在"))["total_count"] == 0
    assert explorer.aggregate("year", Filters("不存在"))["rows"] == []
    result = explorer.search(Filters(), 200)
    assert result["total_count"] == len(source_rows)
    assert result["returned_count"] == 200
    assert result["truncated"] is True
    shinagawa = sum(r["市区町村名"] == "品川区" for r in source_rows)
    assert explorer.search(Filters("　品川区　"), 1)["total_count"] == shinagawa


def test_describe_preserves_schema_metadata_and_attribution(parquet):
    description = DataExplorer(parquet).describe()
    types = {
        "transaction_id": "BIGINT",
        "municipality": "VARCHAR",
        "year": "BIGINT",
        "quarter": "BIGINT",
        "property_type": "VARCHAR",
        "price_yen": "BIGINT",
        "area_m2": "BIGINT",
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
    assert description["municipalities"] == [
        {"municipality": name} for name in sorted(MUNICIPALITIES)
    ]
    assert (description["first_period"], description["last_period"]) == (
        "2023年第1四半期",
        "2025年第4四半期",
    )
    assert "国土交通省 不動産情報ライブラリ" in description["attribution"]


def _write_transactions(path, rows):
    # Build independent input data, without using the query expressions under test.
    with duckdb.connect() as conn:
        conn.execute("""CREATE TABLE fixture (
            transaction_id BIGINT, municipality VARCHAR, year BIGINT, quarter BIGINT,
            property_type VARCHAR, price_yen BIGINT, area_m2 BIGINT
        )""")
        conn.executemany("INSERT INTO fixture VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        conn.table("fixture").write_parquet(str(path))


def test_exact_matching_treats_special_characters_as_values(tmp_path):
    names = ["a%b", "axb", "a_b", "acb", "a'b", r"a\b", "' OR 1=1 --"]
    path = tmp_path / "literal.parquet"
    _write_transactions(path, [(i, name, 2024, 1, name, 100, 50) for i, name in enumerate(names)])
    explorer = DataExplorer(path)
    for i, name in enumerate(names):
        for filters in (Filters(name), Filters(property_type=name)):
            result = explorer.search(filters)
            assert result["total_count"] == 1
            assert result["rows"][0]["transaction_id"] == i


def test_group_count_is_measured_before_limit(tmp_path):
    path = tmp_path / "groups.parquet"
    _write_transactions(
        path, [(i, f"region-{i:03}", 2024, 1, "宅地(土地)", i, 50) for i in range(205)]
    )
    result = DataExplorer(path).aggregate("municipality", Filters())
    assert result["total_count"] == 205
    assert result["returned_count"] == 200
    assert result["count_unit"] == "groups"
    assert result["truncated"] is True
    assert [row["municipality"] for row in result["rows"]] == [f"region-{i:03}" for i in range(200)]


def test_aggregate_rounding_and_price_bounds(tmp_path):
    path = tmp_path / "rounding.parquet"
    _write_transactions(
        path,
        [(i, "品川区", 2024, 1, "宅地(土地)", price, 50) for i, price in enumerate([1, 1, 2])],
    )
    result = DataExplorer(path).aggregate("year", Filters(min_price_yen=1, max_price_yen=2))
    assert result["rows"] == [
        {
            "year": 2024,
            "transaction_count": 3,
            "average_price_yen": 1.33,
            "min_price_yen": 1,
            "max_price_yen": 2,
        }
    ]


def test_untrusted_values_cannot_become_sql(parquet, source_rows):
    explorer = DataExplorer(parquet)
    assert explorer.search(Filters("' OR 1=1 --"))["total_count"] == 0
    with pytest.raises(ValueError):
        explorer.aggregate("year; COPY transactions TO '/tmp/leak'", Filters())
    for limit in [0, 201, True, "5"]:
        with pytest.raises(ValueError):
            explorer.search(Filters(), limit)
    for filters in [
        Filters(year=True),
        Filters(min_price_yen=-1),
        Filters(min_price_yen=10, max_price_yen=1),
        Filters(property_type="x" * 41),
    ]:
        with pytest.raises(ValueError):
            explorer.search(filters)
    assert explorer.describe()["row_count"] == len(source_rows)


def test_connections_can_run_independently(parquet, source_rows):
    explorer = DataExplorer(parquet)
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(
            executor.map(lambda name: explorer.search(Filters(name))["total_count"], MUNICIPALITIES)
        )
    assert results == [sum(r["市区町村名"] == name for r in source_rows) for name in MUNICIPALITIES]


def test_result_artifact_and_model_projection(parquet, tmp_path):
    result = DataExplorer(parquet).search(Filters(), 200)
    store = ResultStore(tmp_path / "results")
    preview = store.put(result)
    summary = model_summary(result, preview["result_id"])
    assert len(store.get(preview["result_id"])["rows"]) == 200
    assert len(preview["preview_rows"]) == 20
    assert len(summary["sample_rows"]) == 3
    assert summary["sample_truncated"]
    assert "国土交通省" in summary["attribution"]
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
