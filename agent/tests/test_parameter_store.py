from types import SimpleNamespace

import boto3
import httpx
import pytest
from botocore.stub import Stubber
from test_server import decode_sse, run_input

from exploration_agent import model as parameter_store
from exploration_agent import secure_parameter
from exploration_agent.entrypoints.agentcore import create_agentcore_app
from exploration_agent.fixture_model import FixtureModel
from exploration_agent.model import SakuraSettings

NAME = "/test/sakura-api-key"
PARAMS = {"Name": NAME, "WithDecryption": True}


@pytest.fixture
def ssm(monkeypatch):
    secure_parameter.read_secure_parameter.cache_clear()
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

    monkeypatch.setattr(secure_parameter.boto3, "Session", session)
    monkeypatch.setenv("EXPLORER_MODEL_MODE", "sakura")
    monkeypatch.setenv("SAKURA_API_KEY_PARAMETER_NAME", NAME)
    monkeypatch.setenv("SAKURA_MODEL_ID", "test-model")
    with Stubber(client) as stub:
        yield stub, sessions
        stub.assert_no_pending_responses()
    secure_parameter.read_secure_parameter.cache_clear()


async def test_key_is_read_once_on_first_run_without_changing_environment(
    ssm, tmp_path, monkeypatch
):
    stub, sessions = ssm
    monkeypatch.setenv("SAKURA_API_KEY", "local-environment-must-not-change")
    keys = []

    def build(settings):
        keys.append(settings.api_key)
        return FixtureModel()  # No actual Sakura API call in this test.

    monkeypatch.setattr(SakuraSettings, "build_model", build)
    stub.add_response(
        "get_parameter",
        {"Parameter": {"Name": NAME, "Type": "SecureString", "Value": "test-key", "Version": 1}},
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
            assert "test-key" not in response.text
    assert keys == ["test-key", "test-key"]
    assert sessions == [{"region_name": "ap-northeast-1"}]
    assert parameter_store.os.environ["SAKURA_API_KEY"] == "local-environment-must-not-change"


def test_failed_read_is_retried_on_next_use(ssm):
    stub, _ = ssm
    stub.add_client_error("get_parameter", "ThrottlingException", expected_params=PARAMS)
    stub.add_response(
        "get_parameter",
        {"Parameter": {"Name": NAME, "Type": "SecureString", "Value": "test-key", "Version": 1}},
        PARAMS,
    )
    with pytest.raises(RuntimeError):
        secure_parameter.read_secure_parameter(NAME)
    assert secure_parameter.read_secure_parameter(NAME) == "test-key"


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


def test_sakura_mode_cannot_silently_fall_back_to_fixture(monkeypatch):
    monkeypatch.setenv("EXPLORER_MODEL_MODE", "sakura")
    monkeypatch.delenv("SAKURA_API_KEY_PARAMETER_NAME", raising=False)
    monkeypatch.delenv("SAKURA_API_KEY", raising=False)
    with pytest.raises(ValueError, match="SAKURA_API_KEY"):
        create_agentcore_app()
