import pytest
from openpyxl import Workbook

from exploration_mcp.data import AREAS, DataExplorer, Filters, prepare_sample
from exploration_mcp.importer import import_excel

RATE = "平均空室率\n(％)"
RENT = "平均賃料\n（円/坪）"


def write_workbook(path, rows, *, areas=AREAS, labels=(RATE, RENT)):
    # Mirror the published layout: notice row, merged area headers, item names, newest first.
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.append([None, "注意書き"])
    sheet.append([None, *[cell for area in areas for cell in (area, None)]])
    sheet.append([None, *(list(labels) * len(areas))])
    for row in rows:
        sheet.append(row)
    book.save(path)


def values(period, base_rate, base_rent):
    return [period, *[v for i in range(6) for v in (base_rate + i, base_rent + i)]]


def test_import_keeps_values_and_marks_real_data(tmp_path):
    source = tmp_path / "market.xlsx"
    rows = [values(202602, 1.25, 20000), values(202601, 2, 21000), values(199912, 3.5, 30000)]
    rows[0][5] = None  # A month without data is left blank in the source.
    write_workbook(source, rows)
    destination = tmp_path / "office-market.parquet"
    prepare_sample(destination)
    assert import_excel(source, destination) == 18  # Replaces the synthetic file.
    explorer = DataExplorer(destination)
    description = explorer.describe()
    assert description["synthetic"] is False
    assert (description["first_year_month"], description["last_year_month"]) == (199912, 202602)
    result = explorer.search(Filters("千代田区"))
    assert [(r["year"], r["month"]) for r in result["rows"]] == [(1999, 12), (2026, 1), (2026, 2)]
    assert [r["vacancy_rate_pct"] for r in result["rows"]] == [4.5, 3.0, 2.25]
    assert [r["rent_yen_per_tsubo"] for r in result["rows"]] == [30001, 21001, 20001]
    chuo = explorer.search(Filters("中央区", 2026, 2026, 2))["rows"][0]
    assert chuo["vacancy_rate_pct"] is None
    assert chuo["rent_yen_per_tsubo"] == 20002
    assert explorer.aggregate("year", Filters("東京ビジネス地区"))["rows"][-1]["month_count"] == 2
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.parametrize(
    "change,message",
    [
        (
            {"areas": ("東京ビジネス地区", "千代田区", "中央区", "港区", "新宿区", "品川区")},
            "地区名",
        ),
        ({"labels": ("空室率", RENT)}, "項目名"),
        ({"rows": [values(202601, 1, 1), values(202601, 1, 1)]}, "重複"),
        ({"rows": [values(202613, 1, 1)]}, "年月"),
        ({"rows": [["2026年1月", *values(0, 1, 1)[1:]]]}, "年月"),
        ({"rows": [[202601, "1.0", *values(0, 1, 1)[2:]]]}, "数値"),
        ({"rows": [values(202601, 1, 1.5)]}, "整数"),
        ({"rows": []}, "形式|データ行"),
    ],
)
def test_unexpected_layout_or_values_are_rejected(tmp_path, change, message):
    source = tmp_path / "market.xlsx"
    rows = change.pop("rows", [values(202601, 1, 1)])
    write_workbook(source, rows, **change)
    destination = tmp_path / "office-market.parquet"
    with pytest.raises(ValueError, match=message):
        import_excel(source, destination)
    assert not destination.exists()


def test_only_local_xlsx_is_accepted(tmp_path):
    source = tmp_path / "market.csv"
    source.write_text("a,b\n")
    with pytest.raises(ValueError, match="xlsx"):
        import_excel(source, tmp_path / "out.parquet")
