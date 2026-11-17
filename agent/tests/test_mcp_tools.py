import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import httpx
import httpx2
import pytest
from ag_ui.core import RunAgentInput
from botocore.credentials import ReadOnlyCredentials
from openai import AsyncOpenAI
from strands.models.openai import OpenAIModel
from test_agui_run import completion, response, tool_message
from test_server import decode_sse, run_input

from exploration_agent.agui import agui_events
from exploration_agent.entrypoints.server import create_app
from exploration_agent.fixture_model import FixtureModel
from exploration_agent.mcp_clients import agentcore as agentcore_mcp
from exploration_agent.mcp_clients.exploration import MCP_TOOL_NAMES, build_mcp_clients
from exploration_agent.mcp_clients.target import local_target, runtime_target


async def test_mcp_exploration_and_comparison_emit_independent_results(mcp_url):
    events = [
        event.model_dump(mode="json", by_alias=True)
        async for event in agui_events(
            RunAgentInput.model_validate(run_input()),
            FixtureModel,
            mcp=local_target(mcp_url),
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
                lambda: OpenAIModel(client=client, model_id="mock"),
                mcp=local_target(mcp_url),
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


@pytest.mark.parametrize("parallel", [False, True])
async def test_mcp_app_html_and_ui_metadata_are_not_sent_to_model(mcp_url, monkeypatch, parallel):
    from exploration_agent.mcp_clients.apps import load_app_resources

    requests = []
    loads = []

    async def load(*args):
        loads.append(True)
        return await load_app_resources(*args)

    monkeypatch.setattr("exploration_agent.agui.load_app_resources", load)

    def handle(request):
        requests.append(json.loads(request.content))
        message = tool_message(
            "show_transaction_dashboard", {"group_by": "quarter", "municipality": "新宿区"}
        )
        if parallel:
            message["tool_calls"] += tool_message(
                "show_transaction_dashboard", {"group_by": "quarter"}, "call-second-app"
            )["tool_calls"]
        answer = (
            completion(message, "tool_calls")
            if len(requests) == 1
            else completion(
                {"role": "assistant", "content": "合成データのグラフを表示しました。"}, "stop"
            )
        )
        return response(answer, not parallel)

    async with AsyncOpenAI(
        api_key="test-only",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    ) as client:
        events = [
            event.model_dump(mode="json", by_alias=True)
            async for event in agui_events(
                RunAgentInput.model_validate(run_input()),
                lambda: OpenAIModel(client=client, model_id="mock", stream=not parallel),
                mcp=local_target(mcp_url),
            )
        ]
    assert events[-1]["type"] == "RUN_FINISHED"
    results = [event["value"] for event in events if event.get("name") == "data_result"]
    assert len(results) == (2 if parallel else 1)
    assert len({result["result_id"] for result in results}) == len(results)
    assert len(loads) == 1
    result = results[0]
    assert len(result["preview_rows"]) == 4
    app = result["app"]
    assert app["resourceUri"] == "ui://exploration/transaction-dashboard-v1.html"
    assert app["mimeType"] == "text/html;profile=mcp-app"
    assert "<html" in app["html"]
    assert app["toolInput"]["group_by"] == "quarter"
    assert app["toolResult"]["content"][0]["type"] == "text"
    assert len(app["toolResult"]["_meta"]["preview"]["preview_rows"]) == 4
    assert "preview_rows" not in json.dumps(requests)
    assert "<html" not in json.dumps(requests)
    tool_result = next(m for m in requests[-1]["messages"] if m["role"] == "tool")
    assert len(json.loads(tool_result["content"])["sample_rows"]) == 3
    assert "preview_rows" not in json.dumps([e for e in events if e["type"] == "TOOL_CALL_RESULT"])


async def test_unavailable_mcp_fails_without_falling_back(tmp_path, unused_tcp_port):
    app = create_app(
        FixtureModel,
        mode="fixture",
        mcp=local_target(f"http://127.0.0.1:{unused_tcp_port}/mcp"),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1"
    ) as client:
        result = await client.post("/invocations", json=run_input())
    events = decode_sse(result.text)
    assert [event["type"] for event in events] == ["RUN_STARTED", "RUN_ERROR"]
    assert "Traceback" not in result.text


def test_only_loopback_mcp_is_allowed():
    with pytest.raises(ValueError):
        local_target("https://example.com/mcp")


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
        # Use the real Strands adapter and MCP server, with only AWS HTTP ingress simulated.
        client = build_mcp_clients(runtime_target(RUNTIME_ARN))[0]
        await asyncio.to_thread(client.start)
        try:
            tools = await asyncio.to_thread(client.list_tools_sync)
            assert {tool.tool_name for tool in tools} == set(MCP_TOOL_NAMES)
            result = await asyncio.to_thread(
                client.call_tool_sync,
                "comparison",
                "compare_values",
                {"baseline": 100, "current": 120},
            )
            structured = result.get("structuredContent")
            assert structured is not None
            assert structured["preview_rows"][0]["percent_change"] == 20
        finally:
            await asyncio.to_thread(client.stop, None, None, None)
    assert len(credentials) == len(requests)
    assert len(sessions) == 2
    assert sessions[0] != sessions[1]


async def test_app_resource_session_is_signed_and_advertises_apps(mcp_url, monkeypatch):
    from exploration_agent.mcp_clients.apps import APP_MIME, APP_URI, load_app_resources

    bodies = []
    methods = []
    frozen = ReadOnlyCredentials("test-key", "test-secret", "test-session-token")

    async def forward(request):
        assert request.headers["Authorization"].startswith("AWS4-HMAC-SHA256 ")
        methods.append(request.method)
        bodies.append(request.content.decode())
        async with httpx.AsyncClient() as upstream:
            response = await upstream.post(
                mcp_url,
                content=request.content,
                headers={k: v for k, v in request.headers.items() if k != "host"},
            )
        return httpx2.Response(
            response.status_code,
            headers={**response.headers, "Mcp-Session-Id": "returned-session"},
            content=response.content,
        )

    original_client = httpx2.AsyncClient
    monkeypatch.setattr(
        agentcore_mcp.boto3,
        "Session",
        lambda: SimpleNamespace(
            get_credentials=lambda: SimpleNamespace(get_frozen_credentials=lambda: frozen)
        ),
    )
    monkeypatch.setattr(
        httpx2,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx2.MockTransport(forward), **kwargs),
    )
    app = await load_app_resources(runtime_target(RUNTIME_ARN))
    assert app["resourceUri"] == APP_URI
    assert app["mimeType"] == APP_MIME
    assert app["html"]
    assert any("io.modelcontextprotocol/ui" in body for body in bodies)
    # AgentCore answers the session DELETE with 404, so it must not be sent.
    assert "DELETE" not in methods


@pytest.mark.parametrize(
    "arn",
    [
        RUNTIME_ARN.replace("ap-northeast-1", "us-east-1"),
        RUNTIME_ARN + "?token=secret",
        "https://example.com/mcp",
        "",
    ],
)
def test_invalid_runtime_arn_is_rejected_before_connecting(arn):
    with pytest.raises(ValueError):
        runtime_target(arn)


async def test_runtime_auth_does_not_use_missing_credentials(monkeypatch):
    monkeypatch.setattr(
        agentcore_mcp.boto3, "Session", lambda: SimpleNamespace(get_credentials=lambda: None)
    )

    async def unexpected(_request):
        pytest.fail("Unauthenticated requests must not be sent")

    async with httpx2.AsyncClient(
        auth=agentcore_mcp.RuntimeAuth(), transport=httpx2.MockTransport(unexpected)
    ) as client:
        with pytest.raises(ValueError, match="AWS認証情報"):
            await client.post(agentcore_mcp.runtime_url(RUNTIME_ARN), json={})
