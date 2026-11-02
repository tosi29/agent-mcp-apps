from concurrent.futures import ThreadPoolExecutor

import pytest

from exploration_agent.data import DataExplorer, Filters
from exploration_agent.results import ResultStore, model_summary


def test_search_and_grouped_values(parquet):
    explorer = DataExplorer(parquet)
    assert explorer.describe()["row_count"] == 360
    result = explorer.search(Filters("新宿区", 2024, 40_000_000, 50_000_000))
    # Independent fixture arithmetic, rather than repeating the SQL under test.
    expected = [i + 1 for i in range(360) if i % 3 == 1 and (i // 3) % 3 == 1 and 4 <= i % 10 <= 6]
    assert [r["transaction_id"] for r in result["rows"]] == expected
    grouped = explorer.aggregate("year", Filters("新宿区"))
    assert [r["transaction_count"] for r in grouped["rows"]] == [40, 40, 40]
    assert [r["average_price_yen"] for r in grouped["rows"]] == [42_500_000] * 3


def test_empty_and_bounded_results(parquet):
    explorer = DataExplorer(parquet)
    assert explorer.search(Filters("不存在"))["total_count"] == 0
    assert explorer.aggregate("year", Filters("不存在"))["rows"] == []
    result = explorer.search(Filters(), 200)
    assert result["total_count"] == 360
    assert result["returned_count"] == 200
    assert result["truncated"] is True


def test_untrusted_values_cannot_become_sql(parquet):
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
    ]:
        with pytest.raises(ValueError):
            explorer.search(filters)
    assert explorer.describe()["row_count"] == 360


def test_connections_can_run_independently(parquet):
    explorer = DataExplorer(parquet)
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(
            executor.map(
                lambda name: explorer.search(Filters(name))["total_count"],
                ["千代田区", "新宿区", "渋谷区"],
            )
        )
    assert results == [120] * 3


def test_result_artifact_and_model_projection(parquet, tmp_path):
    result = DataExplorer(parquet).search(Filters(), 200)
    store = ResultStore(tmp_path / "results")
    preview = store.put(result)
    summary = model_summary(result, preview["result_id"])
    assert len(store.get(preview["result_id"])["rows"]) == 200
    assert len(preview["preview_rows"]) == 20
    assert len(summary["sample_rows"]) == 3
    assert summary["sample_truncated"]
    assert "rows" not in summary
    with pytest.raises(ValueError):
        store.get("../secret")


def test_other_local_paths_are_blocked(parquet, tmp_path):
    secret = tmp_path / "outside.csv"
    secret.write_text("secret\nprivate\n")
    with pytest.raises(Exception, match="disabled by configuration"):
        DataExplorer(parquet)._query("SELECT * FROM read_csv(?)", [str(secret)])


def test_duckdb_execution_is_interrupted(parquet):
    with pytest.raises(Exception, match="[Ii]nterrupt"):
        DataExplorer(parquet, timeout_seconds=0.01)._query(
            "SELECT sum(sqrt(i)) FROM range(1000000000) AS t(i)", []
        )
