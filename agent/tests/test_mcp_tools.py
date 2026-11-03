import asyncio
import json
import threading
from types import SimpleNamespace
from uuid import uuid4

import httpx
import httpx2
import pytest
from ag_ui.core import RunAgentInput
from botocore.credentials import ReadOnlyCredentials
from openai import AsyncOpenAI
from strands.models.openai import OpenAIModel
from test_runtime import completion, response, tool_message
from test_server import decode_sse, run_input

from exploration_agent import agentcore_mcp, mcp_tools
from exploration_agent.fixture_model import FixtureModel
from exploration_agent.mcp_tools import MCP_TOOL_NAMES, connect_mcp
from exploration_agent.server import agui_events, create_app


async def test_mcp_exploration_and_comparison_emit_independent_results(mcp_url):
    events = [
        event.model_dump(mode="json", by_alias=True)
        async for event in agui_events(
            RunAgentInput.model_validate(run_input()),
            FixtureModel(compare=True),
            mcp_url=mcp_url,
        )
    ]
    assert events[-1]["type"] == "RUN_FINISHED"
    results = [event["value"] for event in events if event.get("name") == "data_result"]
    assert len(results) == 2
    assert all(result["source"] == "mcp" for result in results)
    assert results[0]["total_count"] == 3
    assert results[0]["dataset"] == "synthetic-real-estate-v1"
    assert results[0]["synthetic"] is True
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


async def test_mcp_preview_is_not_added_to_model_history(mcp_url, tmp_path):
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


async def test_unavailable_mcp_fails_without_falling_back(tmp_path, unused_tcp_port):
    app = create_app(
        FixtureModel,
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


RUNTIME_ARN = "arn:aws:bedrock-agentcore:ap-northeast-1:123456789012:runtime/comparison-AbCdEf1234"


async def test_signed_runtime_transport_runs_real_mcp_and_refreshes_credentials(
    mcp_url, monkeypatch
):
    requests = []
    credentials = []
    sessions = []

    def session():
        key = f"test-key-{len(credentials)}"
        credentials.append(key)
        frozen = ReadOnlyCredentials(key, "test-secret", "test-session-token")
        return SimpleNamespace(
            get_credentials=lambda: SimpleNamespace(get_frozen_credentials=lambda: frozen)
        )

    async def forward(request):
        requests.append(request)
        assert request.url.host == "bedrock-agentcore.ap-northeast-1.amazonaws.com"
        assert request.headers["Authorization"].startswith("AWS4-HMAC-SHA256 ")
        assert f"Credential=test-key-{len(requests) - 1}/" in request.headers["Authorization"]
        assert "/ap-northeast-1/bedrock-agentcore/aws4_request" in request.headers["Authorization"]
        assert request.headers["X-Amz-Security-Token"] == "test-session-token"
        if json.loads(request.content)["method"] == "server/discover":
            sessions.append(request.headers["Mcp-Session-Id"])
        elif len(requests) > 1:
            assert request.headers["Mcp-Session-Id"] == returned_session
        async with httpx.AsyncClient() as upstream:
            response = await upstream.post(
                mcp_url,
                content=request.content,
                headers={k: v for k, v in request.headers.items() if k != "host"},
            )
        return httpx2.Response(
            response.status_code,
            headers={**response.headers, "Mcp-Session-Id": returned_session},
            content=response.content,
        )

    original_client = httpx2.AsyncClient
    monkeypatch.setattr(agentcore_mcp.boto3, "Session", session)
    monkeypatch.setattr(
        agentcore_mcp.httpx2,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx2.MockTransport(forward), **kwargs),
    )
    for _ in range(2):
        returned_session = str(uuid4())
        async with connect_mcp(None, runtime_arn=RUNTIME_ARN) as tools:
            assert {tool.tool_name for tool in tools} == set(MCP_TOOL_NAMES)
            # Use the real Strands adapter and MCP server, with only AWS HTTP ingress simulated.
            client = tools[0].mcp_client
            result = await asyncio.to_thread(
                client.call_tool_sync,
                "comparison",
                "compare_values",
                {"baseline": 100, "current": 120},
            )
            assert result["structuredContent"]["preview_rows"][0]["percent_change"] == 20
    assert len(credentials) == len(requests)
    assert len(sessions) == 2
    assert sessions[0] != sessions[1]


@pytest.mark.parametrize(
    "arn",
    [
        RUNTIME_ARN.replace("ap-northeast-1", "us-east-1"),
        RUNTIME_ARN + "?token=secret",
        "https://example.com/mcp",
        "",
    ],
)
async def test_invalid_runtime_arn_is_rejected_before_connecting(arn):
    with pytest.raises(ValueError):
        async with connect_mcp(None, runtime_arn=arn):
            pytest.fail("Invalid runtime must not connect")


async def test_local_and_runtime_connections_are_mutually_exclusive():
    with pytest.raises(ValueError):
        async with connect_mcp("http://127.0.0.1:8001/mcp", runtime_arn=RUNTIME_ARN):
            pytest.fail("Ambiguous connection must not connect")


async def test_runtime_auth_does_not_sign_redirect_targets_or_use_missing_credentials(monkeypatch):
    monkeypatch.setattr(
        agentcore_mcp.boto3, "Session", lambda: SimpleNamespace(get_credentials=lambda: None)
    )
    auth = agentcore_mcp.RuntimeAuth(agentcore_mcp.runtime_url(RUNTIME_ARN))

    async def unexpected(_request):
        pytest.fail("Unauthenticated or mismatched requests must not be sent")

    async with httpx2.AsyncClient(auth=auth, transport=httpx2.MockTransport(unexpected)) as client:
        with pytest.raises(ValueError, match="署名先"):
            await client.post("https://untrusted.invalid/mcp", json={})
        with pytest.raises(ValueError, match="AWS認証情報"):
            await client.post(auth.url, json={})
