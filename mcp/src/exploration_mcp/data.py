"""SDK-independent DuckDB queries owned by the MCP service."""

from __future__ import annotations

import math
import threading
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
from duckdb import (
    DuckDBPyConnection,
    DuckDBPyRelation,
    Expression,
    col,
    count_all,
    fn,
    lit,
    star,
    when,
)

DATASET = "office-market-v1"
MAX_ROWS = 200
# The display names are kept exactly as published; only the identifiers are ASCII.
AREAS = ("東京ビジネス地区", "千代田区", "中央区", "港区", "新宿区", "渋谷区")
COLUMNS = {
    "area": "地区（完全一致。東京ビジネス地区は都心5区の合計。候補はdescribe_datasetで確認）",
    "year": "年（西暦）",
    "month": "月（1〜12）",
    "vacancy_rate_pct": "平均空室率（％）。月末時点の月次値",
    "rent_yen_per_tsubo": "平均賃料（円/坪）。月次値",
}
GROUPS = {"area": "area", "year": "year", "month": "month"}
_CONFIG = {"threads": 1, "memory_limit": "256MB"}


def write_dataset(conn: DuckDBPyConnection, table: str, path: Path, *, synthetic: bool) -> None:
    """Write a fixed-schema table atomically; the synthetic flag travels with the file."""
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    flag = "true" if synthetic else "false"
    # `table` and the flag are fixed by this module, never by a tool argument.
    conn.execute(
        f"COPY (SELECT area, year, month, vacancy_rate_pct, rent_yen_per_tsubo FROM {table} "
        "ORDER BY year, month, area) TO ? "
        f"(FORMAT PARQUET, KV_METADATA {{dataset: '{DATASET}', synthetic: '{flag}'}})",
        [str(temporary)],
    )
    temporary.replace(path)


def prepare_sample(path: Path) -> int:
    """Generate deterministic fictional monthly values, unrelated to the actual market."""
    if path.exists():
        raise FileExistsError("データが既にあります。再生成は別の出力先を指定してください。")
    with duckdb.connect(config=_CONFIG) as conn:
        conn.execute(
            """
            CREATE TABLE sample AS SELECT
              ?[1 + a] AS area,
              2023 + y AS year,
              m AS month,
              round(1 + 0.5 * a + 0.25 * y + 0.1 * (m % 2), 2)::DOUBLE AS vacancy_rate_pct,
              20000 + 1000 * a + 500 * y + 10 * m AS rent_yen_per_tsubo
            FROM range(6) AS ta(a), range(3) AS ty(y), range(1, 13) AS tm(m)
            """,
            [list(AREAS)],
        )
        write_dataset(conn, "sample", path, synthetic=True)
        return conn.execute("SELECT count(*) FROM sample").fetchone()[0]  # pyright: ignore[reportOptionalSubscript]


def _integer(name: str, value: int, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")


def _rate(name: str, value: float) -> None:
    if type(value) not in (int, float) or not 0 <= value <= 100:
        raise ValueError(f"{name} must be a number in [0, 100]")


@dataclass(frozen=True)
class Filters:
    area: str = ""
    year_from: int | None = None
    year_to: int | None = None
    month: int | None = None
    min_vacancy_rate_pct: float | None = None
    max_vacancy_rate_pct: float | None = None

    def expression(self) -> Expression:
        if not isinstance(self.area, str) or len(self.area) > 40:
            raise ValueError("area must be a string of at most 40 characters")
        for name, value, low, high in (
            ("year_from", self.year_from, 1900, 2100),
            ("year_to", self.year_to, 1900, 2100),
            ("month", self.month, 1, 12),
        ):
            if value is not None:
                _integer(name, value, low, high)
        for name, value in (
            ("min_vacancy_rate_pct", self.min_vacancy_rate_pct),
            ("max_vacancy_rate_pct", self.max_vacancy_rate_pct),
        ):
            if value is not None:
                _rate(name, value)
        if self.year_from is not None and self.year_to is not None:
            if self.year_from > self.year_to:
                raise ValueError("year_from exceeds year_to")
        if self.min_vacancy_rate_pct is not None and self.max_vacancy_rate_pct is not None:
            if self.min_vacancy_rate_pct > self.max_vacancy_rate_pct:
                raise ValueError("min_vacancy_rate_pct exceeds max_vacancy_rate_pct")
        predicate = lit(True)
        area = unicodedata.normalize("NFKC", self.area).strip()
        if area:
            predicate &= col("area") == lit(area)
        if self.year_from is not None:
            predicate &= col("year") >= lit(self.year_from)
        if self.year_to is not None:
            predicate &= col("year") <= lit(self.year_to)
        if self.month is not None:
            predicate &= col("month") == lit(self.month)
        if self.min_vacancy_rate_pct is not None:
            predicate &= col("vacancy_rate_pct") >= lit(self.min_vacancy_rate_pct)
        if self.max_vacancy_rate_pct is not None:
            predicate &= col("vacancy_rate_pct") <= lit(self.max_vacancy_rate_pct)
        return predicate


def _page(relation: DuckDBPyRelation, order: list[Expression], limit: int) -> DuckDBPyRelation:
    # Count before LIMIT, including grouped results, without a separate count query.
    return relation.select(star(), count_all().over().alias("_total")).sort(*order).limit(limit)


def _area_order() -> Expression:
    # Published order: the five-ward total first, then the wards. Unknown names sort last.
    order = when(col("area") == lit(AREAS[0])).then(lit(0))
    for index, name in enumerate(AREAS[1:], start=1):
        order = order.when(col("area") == lit(name)).then(lit(index))
    return order.otherwise(lit(len(AREAS)))


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
        metadata = {
            row["key"]: row["value"]
            for row in self._query(
                lambda conn: conn.table_function("parquet_kv_metadata", [str(self.parquet)]).select(
                    col("key").cast("VARCHAR").alias("key"),
                    col("value").cast("VARCHAR").alias("value"),
                )
            )
        }
        if metadata.get("dataset") != DATASET or metadata.get("synthetic") not in ("true", "false"):
            raise ValueError("unsupported data file; create it with prepare-sample or import-excel")
        self.synthetic = metadata["synthetic"] == "true"

    def _query(
        self, build: Callable[[DuckDBPyConnection], DuckDBPyRelation]
    ) -> list[dict[str, Any]]:
        with duckdb.connect(
            config={
                **_CONFIG,
                "max_temp_directory_size": "0B",
                "autoinstall_known_extensions": False,
                "autoload_known_extensions": False,
            }
        ) as conn:
            conn.execute("SET allowed_paths = ?", [[str(self.parquet)]])
            conn.execute("SET enable_external_access = false")
            conn.execute("SET lock_configuration = true")
            conn.read_parquet(str(self.parquet)).create_view("office_market")
            timer = threading.Timer(self.timeout_seconds, conn.interrupt)
            timer.daemon = True
            timer.start()
            try:
                # Relations are lazy: keep the timeout active through fetchall().
                relation = build(conn)
                names = relation.columns
                return [dict(zip(names, row, strict=True)) for row in relation.fetchall()]
            finally:
                timer.cancel()
                timer.join()

    def _notice(self) -> str:
        if self.synthetic:
            return "架空の合成データ。実際の空室率・賃料ではなく、市況の判断に使えません。"
        return (
            "公表された月次値をそのまま格納した実データ。集計値は月次値の単純平均で、公表値ではない。"
            "2001年以前は各年12月の値のみ。"
        )

    def describe(self) -> dict[str, Any]:
        schema = self._query(
            lambda conn: (
                conn.table_function("pragma_table_info", ["office_market"])
                .order(col("cid"))
                .select(
                    col("name").alias("column_name"),
                    col("type").alias("column_type"),
                    when(col("notnull")).then(lit("NO")).otherwise(lit("YES")).alias("null"),
                    when(col("pk")).then(lit("PRI")).otherwise(lit(None)).alias("key"),
                    col("dflt_value").alias("default"),
                    lit(None).alias("extra"),
                )
            )
        )
        if [column["column_name"] for column in schema] != list(COLUMNS):
            raise ValueError("unsupported schema; create it with prepare-sample or import-excel")
        period = self._query(
            lambda conn: conn.table("office_market").aggregate(
                [
                    count_all().alias("row_count"),
                    fn("min", col("year") * lit(100) + col("month")).alias("first"),
                    fn("max", col("year") * lit(100) + col("month")).alias("last"),
                ]
            )
        )[0]
        return {
            "dataset": DATASET,
            "synthetic": self.synthetic,
            "notice": self._notice(),
            "columns": [{**column, "meaning": COLUMNS[column["column_name"]]} for column in schema],
            "areas": self._query(
                lambda conn: (
                    conn.table("office_market")
                    .aggregate([col("area")], group_expr=col("area"))
                    .sort(_area_order(), col("area"))
                    .limit(20)
                )
            ),
            "row_count": period["row_count"],
            "first_year_month": period["first"],
            "last_year_month": period["last"],
            "max_result_rows": MAX_ROWS,
        }

    def search(self, filters: Filters, limit: int = 100) -> dict[str, Any]:
        _integer("limit", limit, 1, MAX_ROWS)
        predicate = filters.expression()
        rows = self._query(
            lambda conn: _page(
                conn.table("office_market").filter(predicate),
                [col("year"), col("month"), _area_order()],
                limit,
            )
        )
        return self._result(rows, limit, "rows")

    def aggregate(self, group_by: str, filters: Filters) -> dict[str, Any]:
        if group_by not in GROUPS:
            raise ValueError("group_by must be area, year, or month")
        group = col(GROUPS[group_by])
        predicate = filters.expression()
        rate = col("vacancy_rate_pct")
        rent = col("rent_yen_per_tsubo")

        def build(conn: DuckDBPyConnection) -> DuckDBPyRelation:
            grouped = (
                conn.table("office_market")
                .filter(predicate)
                .aggregate(
                    [
                        group,
                        count_all().alias("month_count"),
                        fn("round", rate.mean(), lit(2)).alias("mean_vacancy_rate_pct"),
                        rate.min().alias("min_vacancy_rate_pct"),
                        rate.max().alias("max_vacancy_rate_pct"),
                        fn("round", rent.mean(), lit(0))
                        .cast("BIGINT")
                        .alias("mean_rent_yen_per_tsubo"),
                        rent.min().alias("min_rent_yen_per_tsubo"),
                        rent.max().alias("max_rent_yen_per_tsubo"),
                    ],
                    group_expr=group,
                )
            )
            order = [_area_order(), group] if group_by == "area" else [group]
            return _page(grouped, order, MAX_ROWS)

        rows = self._query(build)
        return self._result(rows, MAX_ROWS, "groups")

    def _result(self, rows: list[dict], limit: int, unit: str) -> dict[str, Any]:
        total = rows[0]["_total"] if rows else 0
        for row in rows:
            row.pop("_total")
        return {
            "dataset": DATASET,
            "synthetic": self.synthetic,
            "total_count": total,
            "count_unit": unit,
            "returned_count": len(rows),
            "limit": limit,
            "truncated": total > len(rows),
            "rows": rows,
        }
