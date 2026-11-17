import csv
import io

import pytest
from conftest import SOURCE

from exploration_mcp.data import DataExplorer, Filters
from exploration_mcp.source import HEADER, prepare_data


def write_csv(directory, rows, header=HEADER):
    # Mirror the download format: Shift_JIS with CRLF line endings.
    output = io.StringIO()
    csv.writer(output, lineterminator="\r\n").writerows([header, *rows])
    (directory / "download.csv").write_bytes(output.getvalue().encode("cp932"))


def record(**values):
    base = dict.fromkeys(HEADER, "")
    base.update(
        {
            "種類": "宅地(土地)",
            "価格情報区分": "不動産取引価格情報",
            "市区町村名": "品川区",
            "取引価格（総額）": "61000000",
            "面積（㎡）": "45",
            "取引時期": "2024年第4四半期",
        }
    )
    base.update(values)
    return [base[name] for name in HEADER]


def test_committed_csvs_are_converted_without_loss(tmp_path, source_rows):
    path = tmp_path / "transactions.parquet"
    assert prepare_data(SOURCE, path) == len(source_rows)
    explorer = DataExplorer(path)
    rows = explorer.search(Filters(), 200)["rows"]
    for row, source in zip(rows, source_rows, strict=False):
        assert row["municipality"] == source["市区町村名"]
        assert row["property_type"] == source["種類"]
        assert row["price_yen"] == int(source["取引価格（総額）"])
        assert f"{row['year']}年第{row['quarter']}四半期" == source["取引時期"]
    assert [row["transaction_id"] for row in rows] == list(range(1, 201))


def test_capped_area_is_missing_and_file_is_replaced(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    write_csv(source, [record(), record(**{"面積（㎡）": "2,000㎡以上"})])
    path = tmp_path / "transactions.parquet"
    path.write_bytes(b"old")
    assert prepare_data(source, path) == 2
    rows = DataExplorer(path).search(Filters())["rows"]
    assert [row["area_m2"] for row in rows] == [45, None]
    assert rows[0]["year"] == 2024 and rows[0]["quarter"] == 4
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize(
    "rows,header,message",
    [
        ([record()], [*HEADER[:-1], "別の列"], "列の構成"),
        ([record(**{"価格情報区分": "成約価格情報"})], HEADER, "不動産取引価格情報以外"),
        ([record(**{"取引時期": "2024年第5四半期"})], HEADER, "取引時期"),
        ([record(**{"取引価格（総額）": "6千万"})], HEADER, "取引価格"),
        ([record(**{"面積（㎡）": "約45"})], HEADER, "面積"),
        ([record(**{"市区町村名": ""})], HEADER, "1〜40文字"),
        ([record()[:-1]], HEADER, "列数"),
        ([], HEADER, "データ行"),
    ],
)
def test_unexpected_layout_or_values_are_rejected(tmp_path, rows, header, message):
    source = tmp_path / "source"
    source.mkdir()
    write_csv(source, rows, header)
    path = tmp_path / "transactions.parquet"
    with pytest.raises(ValueError, match=message):
        prepare_data(source, path)
    assert not path.exists()


def test_empty_source_directory_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="CSV"):
        prepare_data(tmp_path, tmp_path / "out.parquet")
