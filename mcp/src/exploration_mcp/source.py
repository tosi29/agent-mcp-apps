"""Build the trusted Parquet from the committed CSV downloads, without editing the CSVs.

Only a fixed set of columns is selected and converted. The layout is checked strictly,
so an unexpected download fails instead of being loaded partially.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

import duckdb

HEADER = [
    "種類",
    "価格情報区分",
    "地域",
    "市区町村コード",
    "都道府県名",
    "市区町村名",
    "地区名",
    "最寄駅：名称",
    "最寄駅：距離（分）",
    "取引価格（総額）",
    "坪単価",
    "面積（㎡）",
    "取引価格（㎡単価）",
    "土地の形状",
    "間口",
    "延床面積（㎡）",
    "建築年",
    "建物の構造",
    "用途",
    "今後の利用目的",
    "前面道路：方位",
    "前面道路：種類",
    "前面道路：幅員（ｍ）",
    "都市計画",
    "建ぺい率（％）",
    "容積率（％）",
    "取引時期",
    "取引の事情等",
]
PRICE_CATEGORY = "不動産取引価格情報"
AREA_CAPPED = "2,000㎡以上"  # The source caps large areas; keep them as missing, not 2000.
MAX_FILE_BYTES = 20 * 1024 * 1024
PERIOD = re.compile(r"(\d{4})年第([1-4])四半期")

Row = tuple[int, str, int, int, str, int, int | None]


def _text(value: str, where: str) -> str:
    if not value or len(value) > 40:
        raise ValueError(f"{where}: 1〜40文字の値が必要です")
    return value


def read_csv(path: Path, first_id: int) -> list[Row]:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"{path.name}: ファイルが大きすぎます")
    # The download service provides Shift_JIS (cp932) CSV files.
    text = path.read_bytes().decode("cp932")
    reader = csv.reader(io.StringIO(text, newline=""))
    if next(reader, None) != HEADER:
        raise ValueError(f"{path.name}: 列の構成が想定と異なります")
    index = {name: i for i, name in enumerate(HEADER)}
    rows: list[Row] = []
    for number, record in enumerate(reader, start=2):
        where = f"{path.name} {number}行目"
        if len(record) != len(HEADER):
            raise ValueError(f"{where}: 列数が想定と異なります")
        if record[index["価格情報区分"]] != PRICE_CATEGORY:
            raise ValueError(f"{where}: 不動産取引価格情報以外の行は扱いません")
        period = PERIOD.fullmatch(record[index["取引時期"]])
        if period is None:
            raise ValueError(f"{where}: 取引時期を読み取れません")
        price = record[index["取引価格（総額）"]]
        if not price.isascii() or not price.isdigit():
            raise ValueError(f"{where}: 取引価格（総額）が整数ではありません")
        area = record[index["面積（㎡）"]]
        if area != AREA_CAPPED and (not area.isascii() or not area.isdigit()):
            raise ValueError(f"{where}: 面積（㎡）を読み取れません")
        rows.append(
            (
                first_id + len(rows),
                _text(record[index["市区町村名"]], where),
                int(period[1]),
                int(period[2]),
                _text(record[index["種類"]], where),
                int(price),
                None if area == AREA_CAPPED else int(area),
            )
        )
    if not rows:
        raise ValueError(f"{path.name}: データ行がありません")
    return rows


def prepare_data(source: Path, destination: Path) -> int:
    files = sorted(source.resolve(strict=True).glob("*.csv"))
    if not files:
        raise ValueError("CSVがありません")
    rows: list[Row] = []
    for path in files:
        rows += read_csv(path, len(rows) + 1)
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    with duckdb.connect(config={"threads": 1, "memory_limit": "256MB"}) as conn:
        conn.execute("""CREATE TABLE transactions (
            transaction_id BIGINT, municipality VARCHAR, year BIGINT, quarter BIGINT,
            property_type VARCHAR, price_yen BIGINT, area_m2 BIGINT
        )""")
        conn.executemany("INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        conn.execute("COPY transactions TO ? (FORMAT PARQUET)", [str(temporary)])
    temporary.replace(destination)
    return len(rows)
