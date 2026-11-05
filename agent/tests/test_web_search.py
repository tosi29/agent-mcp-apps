"""The Tavily HTTP service is simulated. These tests do not prove the real API or result quality."""

import json
from functools import partial

import httpx
import httpx2
import pytest
from openai import AsyncOpenAI
from strands.models.openai import OpenAIModel
from test_agui_run import completion, response, tool_message
from test_server import decode_sse, run_input

from exploration_agent import agent as agent_module
from exploration_agent.agent import build_tools
from exploration_agent.entrypoints.server import create_app
from exploration_agent.tools import web as web_search
from exploration_agent.tools.web import (
    MAX_CONTENT_CHARS,
    MAX_FETCHES_PER_RUN,
    MAX_PAGE_CHARS,
    MAX_RESULTS,
    MAX_SEARCHES_PER_RUN,
    MAX_URL_CHARS,
    build_web_fetch_tool,
    build_web_search_tool,
    build_web_tools,
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
    search, fetch = build_tools()[1:]
    assert search.tool_name == "web_search" and fetch.tool_name == "web_fetch"
    assert list(search.tool_spec["inputSchema"]["json"]["properties"]) == ["query"]
    assert list(fetch.tool_spec["inputSchema"]["json"]["properties"]) == ["url"]
    monkeypatch.delenv("TAVILY_API_KEY")
    assert len(build_tools()) == 1
    monkeypatch.setenv("TAVILY_API_KEY_PARAMETER_NAME", "/test/tavily")
    assert [t.tool_name for t in build_tools()[1:]] == ["web_search", "web_fetch"]


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


def test_parameter_store_key_is_read_on_use_without_changing_environment(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY_PARAMETER_NAME", "/test/tavily")
    monkeypatch.setenv("TAVILY_API_KEY", "local-must-not-be-used")
    names = []

    def read(name):
        names.append(name)
        return "key-from-parameter"

    monkeypatch.setattr(web_search, "read_secure_parameter", read)
    sent = []

    def handle(request):
        sent.append(request.headers["authorization"])
        return httpx2.Response(200, json={"results": []})

    search = build_web_search_tool(transport=tavily(handle))
    assert names == []
    search(query="q")
    assert names == ["/test/tavily"]
    assert sent == ["Bearer key-from-parameter"]
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


PAGE_URL = "https://example.com/a"


def tavily_site(page):
    """Answer search with PAGE_URL and extract with the given page body."""

    def handle(request):
        if request.url.path == "/search":
            return httpx2.Response(
                200, json={"results": [{"title": "題", "url": PAGE_URL, "content": "抜粋"}]}
            )
        return httpx2.Response(200, json=page)

    return tavily(handle)


def test_fetch_works_without_a_search_and_page_is_truncated():
    requests = []
    site = tavily_site({"results": [{"url": PAGE_URL, "raw_content": "x" * (MAX_PAGE_CHARS + 1)}]})

    def handle(request):
        requests.append(request)
        return site.handle_request(request)

    result = build_web_fetch_tool(transport=tavily(handle))(url=PAGE_URL)
    assert len(requests) == 1
    assert str(requests[0].url) == "https://api.tavily.com/extract"
    assert requests[0].headers["authorization"] == f"Bearer {KEY}"
    assert json.loads(requests[0].content) == {
        "urls": [PAGE_URL],
        "extract_depth": "basic",
        "format": "markdown",
        "include_images": False,
        "include_favicon": False,
    }
    assert result["content"] == "x" * MAX_PAGE_CHARS and result["truncated"] is True
    assert "未検証" in result["notice"] and result["url"] == PAGE_URL


@pytest.mark.parametrize(
    "url",
    ["", "file:///etc/passwd", "javascript:alert(1)", "https://a.test/" + "x" * MAX_URL_CHARS],
)
def test_fetch_rejects_non_web_urls_without_calling_tavily(url):
    def handle(request):
        raise AssertionError("Tavily must not be called")

    with pytest.raises(ValueError, match="url"):
        build_web_fetch_tool(transport=tavily(handle))(url=url)


def test_fetch_budget_applies_per_run_and_does_not_carry_over():
    page = {"results": [{"url": PAGE_URL, "raw_content": "本文"}]}
    fetch = build_web_fetch_tool(transport=tavily_site(page))
    for _ in range(MAX_FETCHES_PER_RUN):
        fetch(url=PAGE_URL)
    with pytest.raises(ValueError, match="上限"):
        fetch(url=PAGE_URL)
    assert build_web_fetch_tool(transport=tavily_site(page))(url=PAGE_URL)["content"] == "本文"


@pytest.mark.parametrize(
    "page",
    [
        {"results": [], "failed_results": [{"url": PAGE_URL, "error": f"private {KEY}"}]},
        {"results": [{"url": PAGE_URL, "raw_content": "  "}]},
        {"results": [{"url": PAGE_URL}]},
        {"results": ["not-a-result"]},
    ],
)
def test_fetch_failure_is_generic_and_does_not_leak(page, caplog):
    with pytest.raises(RuntimeError, match="^Webページの取得に失敗しました$") as error:
        build_web_fetch_tool(transport=tavily_site(page))(url=PAGE_URL)
    assert error.value.__cause__ is None and error.value.__suppress_context__
    assert KEY not in str(error.value) and KEY not in caplog.text


async def test_agui_run_fetches_a_found_page_and_reports_status(monkeypatch):
    page = {"results": [{"url": PAGE_URL, "raw_content": "ページ本文"}]}
    monkeypatch.setattr(
        agent_module, "build_web_tools", partial(build_web_tools, transport=tavily_site(page))
    )
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        answer = {
            1: completion(tool_message("web_search", {"query": "地価"}), "tool_calls"),
            2: completion(tool_message("web_fetch", {"url": PAGE_URL}), "tool_calls"),
        }.get(len(requests), completion({"role": "assistant", "content": "完了"}, "stop"))
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
    assert [t["function"]["name"] for t in requests[0]["tools"]] == [
        "echo_text",
        "web_search",
        "web_fetch",
    ]
    searched, fetched = [m for m in requests[-1]["messages"] if m["role"] == "tool"]
    assert json.loads(searched["content"])["results"][0]["url"] == PAGE_URL
    assert json.loads(fetched["content"])["content"] == "ページ本文"
    statuses = [e["value"] for e in events if e.get("name") == "tool_status"]
    assert [(s["name"], s["status"]) for s in statuses] == [
        ("web_search", "success"),
        ("web_fetch", "success"),
    ]
    assert not any(e.get("name") == "data_result" for e in events)
    assert KEY not in reply.text
