import httpx
import pytest
from test_server import decode_sse, run_input

from exploration_agent.entrypoints import agentcore as agentcore_server
from exploration_agent.entrypoints.agentcore import create_agentcore_app
from exploration_agent.entrypoints.server import create_app
from exploration_agent.fixture_model import FixtureModel
from exploration_agent.mcp_clients.agentcore import runtime_url


@pytest.fixture(autouse=True)
def no_sakura_api(monkeypatch):
    monkeypatch.setattr(
        agentcore_server, "sakura_factory_from_parameter_store", lambda: FixtureModel
    )


async def test_agentcore_entrypoint_runs_with_fresh_request_state(tmp_path, monkeypatch):
    results_dir = tmp_path / "results"
    monkeypatch.chdir(tmp_path)
    app = create_agentcore_app()
    assert not results_dir.exists()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://runtime.internal:8080"
    ) as client:
        ping = await client.get("/ping")
        assert ping.status_code == 200
        assert ping.json()["mode"] == "sakura"
        first = await client.post("/invocations", json=run_input())
        second = await client.post("/invocations", json=run_input(runId="next-run"))
    for response in [first, second]:
        assert response.status_code == 200
        events = decode_sse(response.text)
        assert events[-1]["type"] == "RUN_FINISHED"
        assert any(
            e["type"] == "TOOL_CALL_START" and e["toolCallName"] == "echo_text" for e in events
        )
        assert not any(e.get("name") == "data_result" for e in events)
        assert [e["value"]["status"] for e in events if e.get("name") == "tool_status"] == [
            "success"
        ]
    assert not results_dir.exists()


def test_agentcore_starts_without_local_parquet_or_duckdb(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert create_agentcore_app() is not None


async def test_local_entrypoint_still_rejects_remote_hosts(tmp_path):
    app = create_app(FixtureModel, mode="fixture")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://runtime.internal:8080"
    ) as client:
        assert (await client.get("/ping")).status_code == 400


def test_agentcore_mcp_configuration_is_lazy(tmp_path, monkeypatch):
    arn = "arn:aws:bedrock-agentcore:ap-northeast-1:123456789012:runtime/comparison-AbCdEf1234"
    monkeypatch.setenv("MCP_RUNTIME_ARN", arn)
    captured = {}

    def capture(_factory, *_args, **kwargs):
        captured.update(kwargs)
        return "app"

    monkeypatch.setattr(agentcore_server, "create_app", capture)
    assert create_agentcore_app() == "app"
    assert captured["mcp"].url == runtime_url(arn)
