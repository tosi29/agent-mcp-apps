import io
import json

import boto3
import pytest
from botocore.exceptions import ClientError
from botocore.response import StreamingBody
from botocore.stub import ANY, Stubber

from exploration_mcp.results import ResultStore, S3ResultStore, to_csv
from exploration_mcp.server import result_store

RESULT = {"total_count": 1, "returned_count": 1, "rows": [{"x": 1}]}


# --- CSV conversion -------------------------------------------------------------------


@pytest.mark.parametrize(
    "rows, csv_text",
    [
        pytest.param([], "", id="no-rows"),
        pytest.param([{"v": "=SUM(A1)"}], "v\r\n'=SUM(A1)\r\n", id="formula-text-neutralized"),
        pytest.param([{"v": -5}], "v\r\n-5\r\n", id="negative-number-kept"),
    ],
)
def test_to_csv(rows, csv_text):
    assert to_csv(rows) == csv_text


# --- S3 store (botocore Stubber; no AWS calls) -----------------------------------------


@pytest.fixture
def s3(monkeypatch):
    client = boto3.client(
        "s3", region_name="ap-northeast-1", aws_access_key_id="t", aws_secret_access_key="t"
    )
    store = S3ResultStore("results-bucket")
    monkeypatch.setattr(store, "_client", lambda: client)
    with Stubber(client) as stubber:
        yield store, stubber
        stubber.assert_no_pending_responses()


def test_s3_store_round_trip_without_overwrite(s3):
    store, stubber = s3
    put = {"Bucket": "results-bucket", "Key": ANY, "Body": ANY}
    stubber.add_response(
        "put_object", {}, {**put, "ContentType": "application/json", "IfNoneMatch": "*"}
    )
    result_id = store.put(RESULT)["result_id"]
    body = json.dumps(RESULT).encode()
    stubber.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(body), len(body))},
        {"Bucket": "results-bucket", "Key": f"results/{result_id}.json"},
    )
    assert store.get_csv(result_id) == "x\r\n1\r\n"


@pytest.mark.parametrize(
    "s3_error, raised",
    [
        pytest.param("NoSuchKey", KeyError, id="missing-or-expired->not-found"),
        pytest.param("AccessDenied", ClientError, id="other-errors-surface"),
    ],
)
def test_s3_store_read_errors(s3, s3_error, raised):
    store, stubber = s3
    stubber.add_client_error("get_object", service_error_code=s3_error)
    with pytest.raises(raised):
        store.get_csv("0" * 32)


def test_s3_store_rejects_bad_ids_before_s3(s3):
    store, _ = s3  # No stubbed response: any S3 call would fail the fixture.
    with pytest.raises(KeyError):
        store.get_csv("../" + "0" * 32)


# --- Store selection ------------------------------------------------------------------


@pytest.mark.parametrize(
    "env, expected",
    [
        pytest.param({"MCP_RESULTS_BUCKET": "results-bucket"}, S3ResultStore, id="bucket->S3"),
        pytest.param({}, ResultStore, id="no-bucket->local-files"),
    ],
)
def test_result_store_selection(monkeypatch, tmp_path, env, expected):
    monkeypatch.delenv("MCP_RESULTS_BUCKET", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert type(result_store(tmp_path, agentcore=True)) is expected
