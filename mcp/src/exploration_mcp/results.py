"""Bounded local result artifacts, independent from the model's tool results."""

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4


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


def model_summary(result: dict[str, Any], result_id: str) -> dict[str, Any]:
    """At most three rows reach the LLM. The artifact is capped separately at 200."""
    return {
        **{k: v for k, v in result.items() if k != "rows"},
        "result_id": result_id,
        "sample_rows": result["rows"][:3],
        "sample_truncated": result["total_count"] > 3,
        "notice": "合成データ。sample_rowsは全件ではない。参照IDはMCP側の一時保存用。",
    }
