"""Convert a manually downloaded monthly office-market Excel file into the trusted Parquet.

The layout is checked strictly and values are stored unchanged. Nothing is fetched
from the network: the operator downloads the file and passes its local path.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import duckdb
from openpyxl import load_workbook

from exploration_mcp.data import _CONFIG, AREAS, write_dataset

MAX_FILE_BYTES = 5 * 1024 * 1024
FIRST_DATA_ROW = 4
RATE_LABEL = "平均空室率(％)"
RENT_LABEL = "平均賃料（円/坪）"


def _label(value: object) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _number(value: object, where: str) -> float | int | None:
    if value is None:
        return None  # The source leaves months without data blank.
    if type(value) not in (int, float) or not math.isfinite(value):  # pyright: ignore[reportArgumentType]
        raise ValueError(f"{where}: 数値ではありません")
    return value  # pyright: ignore[reportReturnType]


def read_excel(path: Path) -> list[tuple[str, int, int, float | None, int | None]]:
    if path.suffix.lower() != ".xlsx" or not path.is_file():
        raise ValueError("ローカルの.xlsxファイルを指定してください")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("ファイルが大きすぎます")
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.worksheets[0]
        rows = list(sheet.iter_rows(min_row=1, max_col=1 + 2 * len(AREAS), values_only=True))
    finally:
        workbook.close()
    if len(rows) < FIRST_DATA_ROW:
        raise ValueError("想定した表の形式ではありません")
    areas, labels = rows[1], rows[2]
    for index, area in enumerate(AREAS):
        column = 1 + 2 * index
        if _label(areas[column]) != area:
            raise ValueError(f"2行目の地区名が想定と異なります: {areas[column]!r}")
        if (_label(labels[column]), _label(labels[column + 1])) != (RATE_LABEL, RENT_LABEL):
            raise ValueError(f"3行目の項目名が想定と異なります（{area}）")
    records = []
    seen: set[int] = set()
    for number, row in enumerate(rows[FIRST_DATA_ROW - 1 :], start=FIRST_DATA_ROW):
        if all(value is None for value in row):
            continue
        period = row[0]
        if type(period) is not int or not 190001 <= period <= 210012 or not 1 <= period % 100 <= 12:
            raise ValueError(f"{number}行目: 年月（YYYYMM）を読み取れません")
        if period in seen:
            raise ValueError(f"{number}行目: 年月が重複しています")
        seen.add(period)
        for index, area in enumerate(AREAS):
            rate = _number(row[1 + 2 * index], f"{number}行目 {area} 空室率")
            rent = _number(row[2 + 2 * index], f"{number}行目 {area} 賃料")
            if rent is not None and rent != int(rent):
                raise ValueError(f"{number}行目 {area} 賃料: 整数ではありません")
            records.append(
                (
                    area,
                    period // 100,
                    period % 100,
                    None if rate is None else float(rate),
                    None if rent is None else int(rent),
                )
            )
    if not records:
        raise ValueError("データ行がありません")
    return records


def import_excel(source: Path, destination: Path) -> int:
    records = read_excel(source.resolve(strict=True))
    with duckdb.connect(config=_CONFIG) as conn:
        conn.execute("""CREATE TABLE imported (
            area VARCHAR, year BIGINT, month BIGINT,
            vacancy_rate_pct DOUBLE, rent_yen_per_tsubo BIGINT
        )""")
        conn.executemany("INSERT INTO imported VALUES (?, ?, ?, ?, ?)", records)
        write_dataset(conn, "imported", destination, synthetic=False)
    return len(records)
