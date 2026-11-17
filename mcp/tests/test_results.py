import csv
import io

import pytest

from exploration_mcp.results import ResultStore, to_csv


def test_csv_neutralizes_spreadsheet_formulas_but_keeps_numbers():
    text = to_csv(
        [
            {"name": "=HYPERLINK(1)", "value": -5, "note": None},
            {"name": "@SUM(A1)", "value": 1.5, "note": 'a,b\n"c"'},
        ]
    )
    assert text.endswith("\r\n")
    rows = list(csv.DictReader(io.StringIO(text, newline="")))
    assert rows[0] == {"name": "'=HYPERLINK(1)", "value": "-5", "note": ""}
    assert rows[1] == {"name": "'@SUM(A1)", "value": "1.5", "note": 'a,b\n"c"'}


def test_empty_result_is_empty_csv():
    assert to_csv([]) == ""


def test_csv_lookup_rejects_unknown_and_malformed_ids(tmp_path):
    store = ResultStore(tmp_path)
    result_id = store.put({"total_count": 1, "returned_count": 1, "rows": [{"x": 1}]})["result_id"]
    assert store.get_csv(result_id) == "x\r\n1\r\n"
    for bad in ["0" * 32, "../" + result_id, result_id.upper()]:
        with pytest.raises(KeyError):
            store.get_csv(bad)
