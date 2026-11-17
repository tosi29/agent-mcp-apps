"""Bounded local result artifacts, independent from the model's tool results."""

import csv
import io
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from mcp.types import ResourceLink

CSV_URI_TEMPLATE = "exploration://results/{result_id}.csv"
CSV_MIME = "text/csv"
# Spreadsheet apps evaluate cells starting with these as formulas.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class ResultStore:
    def __init__(self, directory: Path):
        self.directory = directory

    def put(self, result: dict[str, Any]) -> dict[str, Any]:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        result_id = uuid4().hex
        path = self.directory / f"{result_id}.json"
        with path.open("x", encoding="utf-8") as output:
            json.dump(result, output, ensure_ascii=False, allow_nan=False)
        rows = result["rows"]
        metadata = {k: v for k, v in result.items() if k != "rows"}
        return {
            "result_id": result_id,
            **metadata,
            "preview_rows": rows[:20],
            "preview_truncated": len(rows) > 20,
        }

    def get(self, result_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{32}", result_id):
            raise ValueError("invalid result_id")
        return json.loads((self.directory / f"{result_id}.json").read_text(encoding="utf-8"))

    def get_csv(self, result_id: str) -> str:
        """The stored rows (at most 200) as RFC 4180 CSV. Raises KeyError if unknown."""
        try:
            result = self.get(result_id)
        except (ValueError, FileNotFoundError) as error:
            raise KeyError(result_id) from error
        return to_csv(result["rows"])


def _cell(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def to_csv(rows: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\r\n")
        writer.writeheader()
        writer.writerows({k: _cell(v) for k, v in row.items()} for row in rows)
    return output.getvalue()


def csv_link(preview: dict[str, Any]) -> ResourceLink:
    """A reference only: the client reads the CSV with resources/read when it needs it."""
    return ResourceLink(
        uri=CSV_URI_TEMPLATE.format(result_id=preview["result_id"]),
        name=f"result-{preview['result_id']}.csv",
        title="保存した結果のCSV（合成データ）",
        description=(
            f"保存済みの{preview['returned_count']}行。"
            "同じMCPサーバーでresources/readすると取得できる一時ファイル。"
        ),
        mime_type=CSV_MIME,
    )


def model_summary(result: dict[str, Any], result_id: str) -> dict[str, Any]:
    """At most three rows reach the LLM. The artifact is capped separately at 200."""
    return {
        **{k: v for k, v in result.items() if k != "rows"},
        "result_id": result_id,
        "sample_rows": result["rows"][:3],
        "sample_truncated": result["total_count"] > 3,
        "notice": "合成データ。sample_rowsは全件ではない。参照IDはMCP側の一時保存用。",
    }
