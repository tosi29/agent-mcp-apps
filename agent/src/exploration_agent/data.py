"""SDK-independent, bounded queries over a single trusted local Parquet file."""

from __future__ import annotations

import math
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

MAX_ROWS = 200
COLUMNS = {
    "transaction_id": "合成取引ID",
    "municipality": "市区町村（完全一致。候補はdescribe_datasetで確認）",
    "year": "取引年（西暦）",
    "quarter": "四半期（1〜4）",
    "price_yen": "合成取引総額（円）。単価ではない",
    "area_m2": "合成面積（平方メートル）",
}
GROUPS = {"municipality": "municipality", "year": "year", "quarter": "quarter"}


def prepare_sample(path: Path) -> None:
    """Generate 360 deterministic fictional rows, unrelated to actual transactions."""
    path = path.resolve()
    if path.exists():
        raise FileExistsError("サンプルが既にあります。再生成は別の出力先を指定してください。")
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(config={"threads": 1, "memory_limit": "256MB"}) as conn:
        conn.execute("""
            CREATE TABLE sample AS SELECT
              i + 1 AS transaction_id,
              ['千代田区', '新宿区', '渋谷区'][1 + (i % 3)] AS municipality,
              2023 + ((i // 3) % 3) AS year,
              1 + ((i // 9) % 4) AS quarter,
              20000000 + (i % 10) * 5000000 AS price_yen,
              30 + (i % 8) * 10 AS area_m2
            FROM range(360) AS t(i)
        """)
        conn.execute("COPY sample TO ? (FORMAT PARQUET)", [str(path)])


def _integer(name: str, value: int, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")


@dataclass(frozen=True)
class Filters:
    municipality: str = ""
    year: int | None = None
    min_price_yen: int | None = None
    max_price_yen: int | None = None

    def sql(self) -> tuple[str, list[Any]]:
        if not isinstance(self.municipality, str) or len(self.municipality) > 40:
            raise ValueError("municipality must be a string of at most 40 characters")
        clauses, values = [], []
        municipality = unicodedata.normalize("NFKC", self.municipality).strip()
        if municipality:
            clauses.append("municipality = ?")
            values.append(municipality)
        for name, value, low, high, op in (
            ("year", self.year, 1900, 2100, "="),
            ("min_price_yen", self.min_price_yen, 0, 10**12, ">="),
            ("max_price_yen", self.max_price_yen, 0, 10**12, "<="),
        ):
            if value is not None:
                _integer(name, value, low, high)
                column = "year" if name == "year" else "price_yen"
                clauses.append(f"{column} {op} ?")
                values.append(value)
        if (
            self.min_price_yen is not None
            and self.max_price_yen is not None
            and self.min_price_yen > self.max_price_yen
        ):
            raise ValueError("min_price_yen exceeds max_price_yen")
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), values


class DataExplorer:
    """No caller-supplied SQL, identifiers, URLs, extensions, or file paths in tools.

    memory_limit/interrupt are DuckDB controls, not an OS security boundary.
    Each operation gets its own connection; no shared cursors or snapshot state.
    """

    def __init__(self, parquet: Path, timeout_seconds: float = 5):
        self.parquet = parquet.resolve(strict=True)
        if not self.parquet.is_file() or self.parquet.suffix != ".parquet":
            raise ValueError("a local .parquet file is required")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        self.timeout_seconds = timeout_seconds

    def _query(self, sql: str, params: list[Any]) -> list[dict[str, Any]]:
        with duckdb.connect(
            config={
                "threads": 1,
                "memory_limit": "256MB",
                "max_temp_directory_size": "0B",
                "autoinstall_known_extensions": False,
                "autoload_known_extensions": False,
            }
        ) as conn:
            conn.execute("SET allowed_paths = ?", [[str(self.parquet)]])
            conn.execute("SET enable_external_access = false")
            conn.execute("SET lock_configuration = true")
            conn.read_parquet(str(self.parquet)).create_view("transactions")
            timer = threading.Timer(self.timeout_seconds, conn.interrupt)
            timer.daemon = True
            timer.start()
            try:
                cursor = conn.execute(sql, params)
                names = [column[0] for column in cursor.description]
                return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
            finally:
                timer.cancel()
                timer.join()

    def describe(self) -> dict[str, Any]:
        schema = self._query("DESCRIBE transactions", [])
        actual = {column["column_name"] for column in schema}
        if actual != set(COLUMNS):
            raise ValueError("unsupported schema; this PoC accepts only its synthetic fixture")
        return {
            "dataset": "synthetic-real-estate-v1",
            "synthetic": True,
            "notice": "架空データ。国交省の実データではなく、市場価格の判断に使えません。",
            "columns": [{**column, "meaning": COLUMNS[column["column_name"]]} for column in schema],
            "municipalities": self._query(
                "SELECT DISTINCT municipality FROM transactions ORDER BY municipality LIMIT 20", []
            ),
            "row_count": self._query("SELECT count(*) AS n FROM transactions", [])[0]["n"],
            "max_result_rows": MAX_ROWS,
        }

    def search(self, filters: Filters, limit: int = 100) -> dict[str, Any]:
        _integer("limit", limit, 1, MAX_ROWS)
        where, params = filters.sql()
        rows = self._query(
            "SELECT *, count(*) OVER() AS _total FROM transactions"
            + where
            + " ORDER BY transaction_id LIMIT ?",
            [*params, limit],
        )
        return self._result(rows, limit, "transactions")

    def aggregate(self, group_by: str, filters: Filters) -> dict[str, Any]:
        if group_by not in GROUPS:
            raise ValueError("group_by must be municipality, year, or quarter")
        group = GROUPS[group_by]
        where, params = filters.sql()
        rows = self._query(
            f"WITH grouped AS (SELECT {group}, count(*) AS transaction_count, "
            "round(avg(price_yen), 2) AS average_price_yen, "
            "min(price_yen) AS min_price_yen, max(price_yen) AS max_price_yen "
            f"FROM transactions{where} GROUP BY {group}) "
            f"SELECT *, count(*) OVER() AS _total FROM grouped ORDER BY {group} LIMIT ?",
            [*params, MAX_ROWS],
        )
        return self._result(rows, MAX_ROWS, "groups")

    @staticmethod
    def _result(rows: list[dict], limit: int, unit: str) -> dict[str, Any]:
        total = rows[0]["_total"] if rows else 0
        for row in rows:
            row.pop("_total")
        return {
            "dataset": "synthetic-real-estate-v1",
            "synthetic": True,
            "total_count": total,
            "count_unit": unit,
            "returned_count": len(rows),
            "limit": limit,
            "truncated": total > len(rows),
            "rows": rows,
        }
