"""Bounded local result artifacts, independent from the model's tool results."""

import csv
import io
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3
from botocore.exceptions import ClientError
from mcp.types import ResourceLink

CSV_URI_TEMPLATE = "exploration://results/{result_id}.csv"
CSV_MIME = "text/csv"
# Spreadsheet apps evaluate cells starting with these as formulas.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class ResultStore:
    """Local files. Readable only by the same process host, e.g. one AgentCore session."""

    def __init__(self, directory: Path):
        self.directory = directory

    def _write(self, result_id: str, body: bytes) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (self.directory / f"{result_id}.json").open("xb") as output:
            output.write(body)

    def _read(self, result_id: str) -> bytes:
        return (self.directory / f"{result_id}.json").read_bytes()

    def put(self, result: dict[str, Any]) -> dict[str, Any]:
        result_id = uuid4().hex
        body = json.dumps(result, ensure_ascii=False, allow_nan=False).encode()
        self._write(result_id, body)
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
        return json.loads(self._read(result_id))

    def get_csv(self, result_id: str) -> str:
        """The stored rows (at most 200) as RFC 4180 CSV. Raises KeyError if unknown."""
        try:
            result = self.get(result_id)
        except (ValueError, FileNotFoundError) as error:
            raise KeyError(result_id) from error
        return to_csv(result["rows"])


class S3ResultStore(ResultStore):
    """Shared across AgentCore sessions, so any later connection can read a result."""

    def __init__(self, bucket: str, prefix: str = "results/"):
        self.bucket = bucket
        self.prefix = prefix

    def _client(self):
        # Created per call: Runtime V2 must not capture credentials in its startup snapshot.
        return boto3.client("s3", region_name="ap-northeast-1")

    def _write(self, result_id: str, body: bytes) -> None:
        self._client().put_object(
            Bucket=self.bucket,
            Key=f"{self.prefix}{result_id}.json",
            Body=body,
            ContentType="application/json",
            IfNoneMatch="*",
        )

    def _read(self, result_id: str) -> bytes:
        try:
            response = self._client().get_object(
                Bucket=self.bucket, Key=f"{self.prefix}{result_id}.json"
            )
        except ClientError as error:
            # With s3:ListBucket, a missing key is NoSuchKey rather than AccessDenied.
            if error.response.get("Error", {}).get("Code") == "NoSuchKey":
                raise FileNotFoundError(result_id) from error
            raise
        return response["Body"].read()


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
        title="保存した結果のCSV（不動産取引価格情報を加工して作成）",
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
        "notice": "sample_rowsは全件ではない。参照IDはMCP側の一時保存用。回答には出典を添える。",
    }
