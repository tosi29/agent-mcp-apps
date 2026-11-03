import httpx
import pytest
from test_server import decode_sse, run_input

from exploration_agent import agentcore_server
from exploration_agent.agentcore_server import create_agentcore_app
from exploration_agent.fixture_model import FixtureModel
from exploration_agent.server import create_app


async def test_agentcore_entrypoint_runs_fixture_with_fresh_request_state(
    parquet, tmp_path, monkeypatch
):
    monkeypatch.setenv("EXPLORER_DATA_PATH", str(parquet))
    results_dir = tmp_path / "results"
    monkeypatch.setenv("EXPLORER_RESULTS_DIR", str(results_dir))
    app = create_agentcore_app()
    assert not results_dir.exists()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://runtime.internal:8080"
    ) as client:
        ping = await client.get("/ping")
        assert ping.status_code == 200
        assert ping.json()["mode"] == "fixture"
        first = await client.post("/invocations", json=run_input())
        second = await client.post("/invocations", json=run_input(runId="next-run"))
        assert (
            await client.post(
                "/invocations", json=run_input(), headers={"Origin": "https://untrusted.invalid"}
            )
        ).status_code == 403
    request_ids = []
    for response in [first, second]:
        assert response.status_code == 200
        events = decode_sse(response.text)
        assert events[-1]["type"] == "RUN_FINISHED"
        data = next(event["value"] for event in events if event.get("name") == "data_result")
        assert [row["transaction_count"] for row in data["preview_rows"]] == [40] * 3
        request_ids.append(data["request_id"])
    assert request_ids[0] != request_ids[1]
    assert all((results_dir / request_id).is_dir() for request_id in request_ids)


def test_agentcore_validates_data_before_becoming_healthy(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPLORER_DATA_PATH", str(tmp_path / "missing.parquet"))
    with pytest.raises(FileNotFoundError):
        create_agentcore_app()


async def test_local_entrypoint_still_rejects_remote_hosts(parquet, tmp_path):
    app = create_app(FixtureModel, parquet, tmp_path, mode="fixture")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://runtime.internal:8080"
    ) as client:
        assert (await client.get("/ping")).status_code == 400


def test_agentcore_mcp_configuration_is_lazy_and_fixture_enables_comparison(
    parquet, tmp_path, monkeypatch
):
    arn = "arn:aws:bedrock-agentcore:ap-northeast-1:123456789012:runtime/comparison-AbCdEf1234"
    monkeypatch.setenv("EXPLORER_DATA_PATH", str(parquet))
    monkeypatch.setenv("MCP_RUNTIME_ARN", arn)
    captured = {}

    def capture(factory, *_args, **kwargs):
        captured.update(kwargs)
        captured["model"] = factory()
        return "app"

    monkeypatch.setattr(agentcore_server, "create_app", capture)
    assert create_agentcore_app() == "app"
    assert captured["mcp_runtime_arn"] == arn
    assert captured["model"].compare is True
