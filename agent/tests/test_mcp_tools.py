import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import httpx2
import pytest
from ag_ui.core import RunAgentInput
from openai import AsyncOpenAI
from strands.models.openai import OpenAIModel
from test_runtime import completion, response, tool_message
from test_server import decode_sse, run_input

from exploration_agent import mcp_tools
from exploration_agent.fixture_model import FixtureModel
from exploration_agent.mcp_tools import connect_mcp
from exploration_agent.server import agui_events, create_app


@pytest.fixture(scope="module")
def mcp_url(unused_tcp_port_factory):
    port = unused_tcp_port_factory()
    source = Path(__file__).resolve().parents[2] / "mcp" / "src"
    process = subprocess.Popen(
        [sys.executable, "-m", "exploration_mcp.server", "--port", str(port)],
        env={**os.environ, "PYTHONPATH": str(source)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}/mcp"
    try:
        for _ in range(100):
            assert process.poll() is None, "MCP server exited during startup"
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                pass
            time.sleep(0.05)
        else:
            pytest.fail("MCP server did not start")
        yield url
    finally:
        process.terminate()
        process.wait(timeout=5)


async def test_existing_and_mcp_tools_emit_independent_results(mcp_url, parquet, tmp_path):
    events = [
        event.model_dump(mode="json", by_alias=True)
        async for event in agui_events(
            RunAgentInput.model_validate(run_input()),
            FixtureModel(compare=True),
            parquet,
            tmp_path,
            mcp_url=mcp_url,
        )
    ]
    assert events[-1]["type"] == "RUN_FINISHED"
    results = [event["value"] for event in events if event.get("name") == "data_result"]
    assert len(results) == 2
    assert results[0]["total_count"] == 3
    assert results[1]["source"] == "mcp"
    assert results[1]["preview_rows"] == [
        {
            "baseline": 42_500_000,
            "current": 42_500_000,
            "difference": 0,
            "percent_change": 0,
        }
    ]
    metrics = next(event["value"] for event in events if event.get("name") == "run_metrics")
    assert metrics == {"model_calls": 4, "tool_calls": 3, "tool_errors": 0}
    statuses = [event["value"]["status"] for event in events if event.get("name") == "tool_status"]
    assert statuses == ["success"] * 3


async def test_mcp_preview_is_not_added_to_model_history(mcp_url, parquet, tmp_path):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        answer = (
            completion(
                tool_message("compare_values", {"baseline": 100, "current": 120}), "tool_calls"
            )
            if len(requests) == 1
            else completion({"role": "assistant", "content": "増減率は20%です。"}, "stop")
        )
        return response(answer, True)

    async with AsyncOpenAI(
        api_key="test-only",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    ) as client:
        events = [
            event.model_dump(mode="json", by_alias=True)
            async for event in agui_events(
                RunAgentInput.model_validate(run_input()),
                OpenAIModel(client=client, model_id="mock"),
                parquet,
                tmp_path,
                mcp_url=mcp_url,
            )
        ]
    assert events[-1]["type"] == "RUN_FINISHED"
    assert (
        next(event["value"] for event in events if event.get("name") == "data_result")["source"]
        == "mcp"
    )
    summary = json.loads(
        next(
            message["content"] for message in requests[-1]["messages"] if message["role"] == "tool"
        )
    )
    assert summary["percent_change"] == 20
    assert "preview_rows" not in json.dumps(requests)
    assert "result_id" not in json.dumps(requests)


async def test_unavailable_mcp_fails_without_falling_back(parquet, tmp_path, unused_tcp_port):
    app = create_app(
        FixtureModel,
        parquet,
        tmp_path,
        mode="fixture",
        mcp_url=f"http://127.0.0.1:{unused_tcp_port}/mcp",
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        result = await client.post("/invocations", json=run_input())
    events = decode_sse(result.text)
    assert [event["type"] for event in events] == ["RUN_STARTED", "RUN_ERROR"]
    assert "Traceback" not in result.text


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/mcp",
        "http://user:secret@localhost/mcp",
        "http://localhost/mcp?token=secret",
    ],
)
async def test_only_loopback_mcp_without_embedded_credentials_is_allowed(url):
    with pytest.raises(ValueError):
        async with connect_mcp(url):
            pytest.fail("Invalid URL connected")


async def test_cancel_during_connect_closes_the_connection(monkeypatch):
    started, release = threading.Event(), threading.Event()
    closed = []

    class Client:
        def start(self):
            started.set()
            assert release.wait(2)

        def stop(self, *_args):
            closed.append(True)

    monkeypatch.setattr(mcp_tools, "MCPClient", lambda **_kwargs: Client())

    async def open_connection():
        async with connect_mcp("http://127.0.0.1:8001/mcp"):
            pytest.fail("A cancelled connection must not be yielded")

    task = asyncio.create_task(open_connection())
    try:
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed == [True]
