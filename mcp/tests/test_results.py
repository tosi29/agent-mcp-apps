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
BAD_IDS = [
    pytest.param("../" + "0" * 32, id="path-traversal"),
    pytest.param("0" * 31 + "A", id="uppercase"),
    pytest.param("x", id="too-short"),
]


# --- CSV conversion -------------------------------------------------------------------


@pytest.mark.parametrize(
    "rows, csv_text",
    [
        pytest.param([], "", id="no-rows"),
        pytest.param([{"n": -5, "v": 1.5}], "n,v\r\n-5,1.5\r\n", id="numbers-kept"),
        pytest.param([{"n": 1, "v": None}], "n,v\r\n1,\r\n", id="null-is-empty"),
        pytest.param([{"v": "=SUM(A1)"}], "v\r\n'=SUM(A1)\r\n", id="formula-neutralized"),
        pytest.param([{"v": "@x"}], "v\r\n'@x\r\n", id="at-neutralized"),
        pytest.param([{"v": 'a,"b"'}], 'v\r\n"a,""b"""\r\n', id="quoted"),
    ],
)
def test_to_csv(rows, csv_text):
    assert to_csv(rows) == csv_text


# --- Local store ----------------------------------------------------------------------


def test_local_store_round_trip(tmp_path):
    store = ResultStore(tmp_path)
    result_id = store.put(RESULT)["result_id"]
    assert store.get_csv(result_id) == "x\r\n1\r\n"


@pytest.mark.parametrize("result_id", [pytest.param("0" * 32, id="unknown"), *BAD_IDS])
def test_local_store_rejects(tmp_path, result_id):
    with pytest.raises(KeyError):
        ResultStore(tmp_path).get_csv(result_id)


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


@pytest.mark.parametrize("result_id", BAD_IDS)
def test_s3_store_rejects_bad_ids_before_s3(s3, result_id):
    store, _ = s3  # No stubbed response: any S3 call would fail the fixture.
    with pytest.raises(KeyError):
        store.get_csv(result_id)


# --- Store selection ------------------------------------------------------------------


@pytest.mark.parametrize(
    "bucket, agentcore, expected",
    [
        pytest.param("results-bucket", True, S3ResultStore, id="agentcore+bucket->S3"),
        pytest.param(None, True, ResultStore, id="agentcore-without-bucket->local"),
        pytest.param(None, False, ResultStore, id="local->local"),
    ],
)
def test_result_store_selection(monkeypatch, tmp_path, bucket, agentcore, expected):
    monkeypatch.delenv("MCP_RESULTS_BUCKET", raising=False)
    if bucket:
        monkeypatch.setenv("MCP_RESULTS_BUCKET", bucket)
    assert type(result_store(tmp_path, agentcore=agentcore)) is expected
