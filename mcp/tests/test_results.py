import csv
import io
import json
from types import SimpleNamespace

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber

from exploration_mcp.results import ResultStore, S3ResultStore, to_csv


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


def _stubbed_s3_store(monkeypatch):
    client = boto3.client(
        "s3",
        region_name="ap-northeast-1",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    stubber = Stubber(client)
    store = S3ResultStore("results-bucket")
    monkeypatch.setattr(store, "_client", lambda: client)
    return store, stubber


def test_s3_store_writes_once_and_reads_back_as_csv(monkeypatch):
    store, stubber = _stubbed_s3_store(monkeypatch)
    rows = [{"municipality": "=cmd", "count": 1}]
    with stubber:
        stubber.add_response(
            "put_object",
            {},
            {
                "Bucket": "results-bucket",
                "Key": ANY,
                "Body": ANY,
                "ContentType": "application/json",
                "IfNoneMatch": "*",
            },
        )
        preview = store.put({"total_count": 1, "returned_count": 1, "rows": rows})
        key = f"results/{preview['result_id']}.json"
        body = json.dumps({"rows": rows}).encode()
        stubber.add_response(
            "get_object",
            {"Body": StreamingBody(io.BytesIO(body), len(body))},
            {"Bucket": "results-bucket", "Key": key},
        )
        assert store.get_csv(preview["result_id"]) == "municipality,count\r\n'=cmd,1\r\n"
        stubber.assert_no_pending_responses()


def test_s3_store_maps_missing_object_and_rejects_bad_ids_before_s3(monkeypatch):
    store, stubber = _stubbed_s3_store(monkeypatch)
    with stubber:
        stubber.add_client_error("get_object", service_error_code="NoSuchKey", http_status_code=404)
        with pytest.raises(KeyError):
            store.get_csv("0" * 32)
        # No stubbed call remains, so these never reach S3.
        for bad in ["../" + "0" * 32, "x"]:
            with pytest.raises(KeyError):
                store.get_csv(bad)
        stubber.assert_no_pending_responses()


def test_s3_store_does_not_hide_other_s3_errors(monkeypatch):
    store, stubber = _stubbed_s3_store(monkeypatch)
    with stubber:
        stubber.add_client_error(
            "get_object", service_error_code="AccessDenied", http_status_code=403
        )
        with pytest.raises(ClientError):
            store.get_csv("0" * 32)


def test_server_uses_s3_only_when_bucket_is_configured(monkeypatch, parquet, tmp_path):
    from exploration_mcp import server

    created = []
    monkeypatch.setattr(server, "S3ResultStore", lambda bucket: created.append(bucket) or object())
    monkeypatch.setattr(server, "register_tools", lambda *args: None)
    monkeypatch.setattr(server, "dashboard_app", lambda *args: None)
    monkeypatch.setattr(server, "MCPServer", lambda *args, **kwargs: _FakeServer())
    monkeypatch.setenv("MCP_RESULTS_BUCKET", "results-bucket")
    server.create_app(agentcore=True, data_path=parquet)
    assert created == ["results-bucket"]
    # An explicit local directory (local CLI and tests) keeps local files.
    server.create_app(data_path=parquet, results_dir=tmp_path)
    assert created == ["results-bucket"]


class _FakeServer:
    def custom_route(self, *args, **kwargs):
        return lambda fn: fn

    def streamable_http_app(self, **kwargs):
        return SimpleNamespace(add_middleware=lambda *args: None)
