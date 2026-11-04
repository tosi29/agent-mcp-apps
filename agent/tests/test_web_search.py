"""The Tavily HTTP service is simulated. These tests do not prove the real API or result quality."""

import json
from functools import partial

import httpx
import httpx2
import pytest
from openai import AsyncOpenAI
from strands.models.openai import OpenAIModel
from test_runtime import completion, response, tool_message
from test_server import decode_sse, run_input

from exploration_agent import runtime, web_search
from exploration_agent.runtime import build_tools
from exploration_agent.server import create_app
from exploration_agent.web_search import (
    MAX_CONTENT_CHARS,
    MAX_RESULTS,
    MAX_SEARCHES_PER_RUN,
    build_web_search_tool,
)

KEY = "tvly-private-test-key"


@pytest.fixture(autouse=True)
def tavily_env(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY_PARAMETER_NAME", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", KEY)


def tavily(handler):
    return httpx2.MockTransport(handler)


def found(results):
    return lambda request: httpx2.Response(200, json={"results": results})


def test_tool_is_registered_only_when_a_key_source_is_configured(monkeypatch):
    assert [t.tool_name for t in build_tools()[1:]] == ["web_search"]
    assert "query" in build_tools()[1].tool_spec["inputSchema"]["json"]["properties"]
    assert len(build_tools()[1].tool_spec["inputSchema"]["json"]["properties"]) == 1
    monkeypatch.delenv("TAVILY_API_KEY")
    assert len(build_tools()) == 1
    monkeypatch.setenv("TAVILY_API_KEY_PARAMETER_NAME", "/test/tavily")
    assert [t.tool_name for t in build_tools()[1:]] == ["web_search"]


def test_request_is_fixed_by_the_app_and_result_is_projected():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx2.Response(
            200,
            json={
                "results": [
                    {
                        "title": "題",
                        "url": "https://example.com/a",
                        "content": "x" * (MAX_CONTENT_CHARS + 1),
                        "raw_content": "raw-page-body",
                        "score": 0.9,
                    },
                    {"title": "不正", "url": "javascript:alert(1)", "content": "dropped"},
                    "not-a-result",
                ]
            },
        )

    result = build_web_search_tool(transport=tavily(handle))(query=" 地価 動向 ")
    assert str(requests[0].url) == "https://api.tavily.com/search"
    assert requests[0].headers["authorization"] == f"Bearer {KEY}"
    assert json.loads(requests[0].content) == {
        "query": "地価 動向",
        "search_depth": "basic",
        "max_results": MAX_RESULTS,
        "include_answer": False,
        "include_raw_content": False,
    }
    assert result["results"] == [
        {"title": "題", "url": "https://example.com/a", "content": "x" * MAX_CONTENT_CHARS}
    ]
    assert "未検証" in result["notice"]


@pytest.mark.parametrize("query", ["", "   ", "x" * 401])
def test_invalid_query_is_rejected_without_calling_tavily(query):
    def handle(request):
        raise AssertionError("Tavily must not be called")

    with pytest.raises(ValueError, match="query"):
        build_web_search_tool(transport=tavily(handle))(query=query)


def test_budget_applies_per_run_and_does_not_carry_over():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx2.Response(200, json={"results": []})

    first_run = build_web_search_tool(transport=tavily(handle))
    for _ in range(MAX_SEARCHES_PER_RUN):
        first_run(query="q")
    with pytest.raises(ValueError, match="上限"):
        first_run(query="q")
    assert len(calls) == MAX_SEARCHES_PER_RUN
    build_web_search_tool(transport=tavily(handle))(query="q")
    assert len(calls) == MAX_SEARCHES_PER_RUN + 1


@pytest.mark.parametrize(
    "reply",
    [
        httpx2.Response(401, json={"detail": f"bad key {KEY}"}),
        httpx2.Response(302, headers={"Location": "https://untrusted.invalid/"}),
        httpx2.Response(200, text="not-json"),
    ],
)
def test_failure_is_generic_and_does_not_leak_or_follow(reply, caplog):
    requests = []

    def handle(request):
        requests.append(request)
        return reply

    with pytest.raises(RuntimeError, match="^Web検索に失敗しました$") as error:
        build_web_search_tool(transport=tavily(handle))(query="q")
    assert error.value.__cause__ is None and error.value.__suppress_context__
    assert len(requests) == 1
    assert KEY not in str(error.value) and KEY not in caplog.text


def test_parameter_store_key_is_read_per_call_without_changing_environment(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY_PARAMETER_NAME", "/test/tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "local-must-not-be-used")
    names = []
    keys = iter(["key-before-rotation", "key-after-rotation"])

    def read(name):
        names.append(name)
        return next(keys)

    monkeypatch.setattr(web_search, "read_secure_parameter", read)
    sent = []

    def handle(request):
        sent.append(request.headers["authorization"])
        return httpx2.Response(200, json={"results": []})

    search = build_web_search_tool(transport=tavily(handle))
    assert names == []
    search(query="q")
    search(query="q")
    assert names == ["/test/tavily"] * 2
    assert sent == ["Bearer key-before-rotation", "Bearer key-after-rotation"]
    assert web_search.os.environ["TAVILY_API_KEY"] == "local-must-not-be-used"


@pytest.mark.parametrize("value", ["", None])
def test_unavailable_parameter_fails_the_tool_only(monkeypatch, value):
    monkeypatch.setenv("TAVILY_API_KEY_PARAMETER_NAME", "/test/tavily")

    def read(name):
        if value is None:
            raise RuntimeError("private-detail")
        return value

    monkeypatch.setattr(web_search, "read_secure_parameter", read)
    with pytest.raises(RuntimeError, match="^Web検索に失敗しました$"):
        build_web_search_tool(transport=tavily(found([])))(query="q")


async def test_agui_run_uses_web_search_and_reports_its_status(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "build_web_search_tool",
        partial(
            build_web_search_tool,
            transport=tavily(
                found([{"title": "題", "url": "https://example.com/a", "content": "抜粋"}])
            ),
        ),
    )
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        answer = (
            completion(tool_message("web_search", {"query": "地価"}), "tool_calls")
            if len(requests) == 1
            else completion({"role": "assistant", "content": "完了"}, "stop")
        )
        return response(answer, True)

    async with AsyncOpenAI(
        api_key="test-only",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    ) as model_client:
        app = create_app(
            lambda: OpenAIModel(client=model_client, model_id="mock"),
            mode="test",
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            reply = await client.post("/invocations", json=run_input())
    events = decode_sse(reply.text)
    assert events[-1]["type"] == "RUN_FINISHED", events
    assert [t["function"]["name"] for t in requests[0]["tools"]] == ["echo_text", "web_search"]
    tool_result = next(m for m in requests[-1]["messages"] if m["role"] == "tool")
    assert json.loads(tool_result["content"])["results"][0]["url"] == "https://example.com/a"
    status = next(e["value"] for e in events if e.get("name") == "tool_status")
    assert status["name"] == "web_search" and status["status"] == "success"
    assert not any(e.get("name") == "data_result" for e in events)
    assert KEY not in reply.text
