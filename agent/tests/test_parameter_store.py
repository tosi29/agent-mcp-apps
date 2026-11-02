from types import SimpleNamespace

import boto3
import httpx
import pytest
from botocore.stub import Stubber
from test_server import decode_sse, run_input

from exploration_agent import parameter_store
from exploration_agent.agentcore_server import create_agentcore_app
from exploration_agent.fixture_model import FixtureModel
from exploration_agent.runtime import SakuraSettings

NAME = "/test/sakura-api-key"
PARAMS = {"Name": NAME, "WithDecryption": True}


@pytest.fixture
def ssm(monkeypatch):
    client = boto3.client(
        "ssm",
        region_name="ap-northeast-1",
        aws_access_key_id="test-only",
        aws_secret_access_key="test-only",
    )
    sessions = []

    def session(**kwargs):
        sessions.append(kwargs)
        return SimpleNamespace(client=lambda *args, **kwargs: client)

    monkeypatch.setattr(parameter_store.boto3, "Session", session)
    monkeypatch.setenv("EXPLORER_MODEL_MODE", "sakura")
    monkeypatch.setenv("SAKURA_API_KEY_PARAMETER_NAME", NAME)
    monkeypatch.setenv("SAKURA_MODEL_ID", "test-model")
    with Stubber(client) as stub:
        yield stub, sessions
        stub.assert_no_pending_responses()


async def test_key_is_read_after_snapshot_per_run_without_changing_environment(
    ssm, parquet, tmp_path, monkeypatch
):
    stub, sessions = ssm
    monkeypatch.setenv("EXPLORER_DATA_PATH", str(parquet))
    monkeypatch.setenv("EXPLORER_RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("SAKURA_API_KEY", "local-environment-must-not-change")
    keys = []

    def build(settings):
        keys.append(settings.api_key)
        return FixtureModel()  # No actual Sakura API call in this test.

    monkeypatch.setattr(SakuraSettings, "build_model", build)
    for key in ["test-key-before-rotation", "test-key-after-rotation"]:
        stub.add_response(
            "get_parameter",
            {"Parameter": {"Name": NAME, "Type": "SecureString", "Value": key, "Version": 1}},
            PARAMS,
        )
    app = create_agentcore_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://runtime.internal:8080"
    ) as client:
        assert (await client.get("/ping")).json()["mode"] == "sakura"
        assert sessions == [] and keys == []
        for run_id in ["first", "second"]:
            response = await client.post("/invocations", json=run_input(runId=run_id))
            events = decode_sse(response.text)
            assert events[-1]["type"] == "RUN_FINISHED"
            assert "test-key-" not in response.text
    assert keys == ["test-key-before-rotation", "test-key-after-rotation"]
    assert sessions == [{"region_name": "ap-northeast-1"}] * 2
    assert parameter_store.os.environ["SAKURA_API_KEY"] == "local-environment-must-not-change"


@pytest.mark.parametrize("kind", ["access_denied", "plain_string", "empty_value"])
def test_invalid_parameter_fails_without_leaking_key(ssm, kind):
    stub, _ = ssm
    if kind == "access_denied":
        stub.add_client_error(
            "get_parameter", "AccessDeniedException", "private-test-key", expected_params=PARAMS
        )
    else:
        stub.add_response(
            "get_parameter",
            {
                "Parameter": {
                    "Type": "String" if kind == "plain_string" else "SecureString",
                    "Value": "private-test-key" if kind == "plain_string" else "",
                }
            },
            PARAMS,
        )
    with pytest.raises((RuntimeError, ValueError)) as error:
        parameter_store.build_sakura_model_from_parameter_store()
    assert "private-test-key" not in str(error.value)


def test_sakura_mode_cannot_silently_fall_back_to_fixture(parquet, monkeypatch):
    monkeypatch.setenv("EXPLORER_DATA_PATH", str(parquet))
    monkeypatch.setenv("EXPLORER_MODEL_MODE", "sakura")
    monkeypatch.delenv("SAKURA_API_KEY_PARAMETER_NAME", raising=False)
    with pytest.raises(ValueError, match="SAKURA_API_KEY_PARAMETER_NAME"):
        create_agentcore_app()
