"""Real Strands + OpenAI provider through AG-UI; only the external HTTP service is simulated.

These tests prove local SDK integration, not Sakura API compatibility or model quality.
"""

import asyncio
import json

import httpx2
import pytest
from ag_ui.core import RunAgentInput
from openai import AsyncOpenAI
from strands.models.openai import OpenAIModel

from exploration_agent.entrypoints.agui import agui_events
from exploration_agent.model import SakuraSettings


def completion(message, finish_reason):
    return {
        "id": "local-test",
        "object": "chat.completion",
        "created": 0,
        "model": "mock",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
    }


def tool_message(name, args, call_id="call-search"):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(args),
                },
            }
        ],
    }


def response(body, streaming):
    if not streaming:
        return httpx2.Response(200, json=body)
    message = body["choices"][0]["message"]
    if message.get("tool_calls"):
        call = message["tool_calls"][0]
        args = call["function"]["arguments"]
        middle = len(args) // 2
        deltas = [
            {
                "tool_calls": [
                    {
                        **call,
                        "index": 0,
                        "function": {
                            "name": call["function"]["name"],
                            "arguments": args[:middle],
                        },
                    }
                ]
            },
            {"tool_calls": [{"index": 0, "function": {"arguments": args[middle:]}}]},
        ]
    else:
        deltas = [{"content": "合成データの"}, {"content": "検索結果です。"}]
    if reasoning := message.get("reasoning_content"):
        middle = len(reasoning) // 2
        deltas = [
            {"reasoning_content": reasoning[:middle]},
            {"reasoning_content": reasoning[middle:]},
            *deltas,
        ]
    chunks = []
    for delta, finish in [*[(d, None) for d in deltas], ({}, body["choices"][0]["finish_reason"])]:
        chunks.append(
            "data: "
            + json.dumps(
                {
                    "id": "local-test",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": "mock",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                },
                ensure_ascii=False,
            )
            + "\n\n"
        )
    return httpx2.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content="".join(chunks) + "data: [DONE]\n\n",
    )


def run_events(model, prompt="テスト", **kwargs):
    run = RunAgentInput.model_validate(
        {
            "threadId": "local-thread",
            "runId": "local-run",
            "messages": [{"id": "user-1", "role": "user", "content": prompt}],
            "tools": [],
            "context": [],
            "state": {},
            "forwardedProps": {},
        }
    )
    return agui_events(run, model, **kwargs)


async def collect(model, prompt="テスト", **kwargs):
    return [
        event.model_dump(mode="json", by_alias=True)
        async for event in run_events(model, prompt, **kwargs)
    ]


def custom(events, name):
    return [event["value"] for event in events if event.get("name") == name]


@pytest.mark.parametrize("streaming", [True, False])
async def test_real_sdk_tool_loop_and_data_separation(tmp_path, streaming, mcp_url, mcp_results):
    requests = []

    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            answer = completion(tool_message("describe_dataset", {}, "call-schema"), "tool_calls")
        elif len(requests) == 2:
            answer = completion(tool_message("search_transactions", {"limit": 200}), "tool_calls")
        else:
            answer = completion(
                {"role": "assistant", "content": "合成データの検索結果です。"}, "stop"
            )
        return response(answer, streaming)

    async with AsyncOpenAI(
        api_key="test-only",
        base_url="https://mock.invalid/v1",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    ) as client:
        model = OpenAIModel(client=client, model_id="mock", stream=streaming)
        events = await collect(model, "合成データを検索", mcp_url=mcp_url)
    assert len(requests) == 3
    search_spec = next(
        item["function"]
        for item in requests[0]["tools"]
        if item["function"]["name"] == "search_transactions"
    )
    assert "tool_context" not in search_spec["parameters"]["properties"]
    assert all(request["stream"] is streaming for request in requests)
    assert events[-1]["type"] == "RUN_FINISHED", events
    assert custom(events, "run_metrics") == [{"model_calls": 3, "tool_calls": 2, "tool_errors": 0}]
    data = custom(events, "data_result")[0]
    assert data["tool_call_id"] == "call-search"
    assert len(data["preview_rows"]) == 20
    assert data["total_count"] == 360
    artifact = json.loads((mcp_results / f"{data['result_id']}.json").read_text())
    assert len(artifact["rows"]) == 200
    model_result = next(
        m for m in requests[-1]["messages"] if m.get("tool_call_id") == "call-search"
    )
    assert "sample_rows" in model_result["content"]
    assert "preview_rows" not in model_result["content"]
    projection = json.loads(model_result["content"])
    assert len(projection["sample_rows"]) == 3
    assert projection["total_count"] == 360
    assert projection["sample_truncated"] is True
    assert "rows" not in projection
    assert "合成データの検索結果です。" == "".join(
        e["delta"] for e in events if e["type"] == "TEXT_MESSAGE_CONTENT"
    )


async def test_provider_error_is_terminal_and_not_leaked(tmp_path):
    calls = 0

    def handle(request):
        nonlocal calls
        calls += 1
        return httpx2.Response(
            429, json={"error": {"message": "private-secret", "type": "rate_limit"}}
        )

    async with AsyncOpenAI(
        api_key="test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    ) as client:
        events = await collect(OpenAIModel(client=client, model_id="mock"))
    assert calls == 1
    assert events[-1]["type"] == "RUN_ERROR"
    assert not any(e["type"] == "RUN_FINISHED" for e in events)
    assert "private-secret" not in json.dumps(events)


def test_sakura_settings_require_key_and_model(monkeypatch):
    monkeypatch.delenv("SAKURA_API_KEY", raising=False)
    monkeypatch.delenv("SAKURA_MODEL_ID", raising=False)
    with pytest.raises(ValueError, match="SAKURA_API_KEY"):
        SakuraSettings.from_env()
    monkeypatch.setenv("SAKURA_API_KEY", "test-key")
    with pytest.raises(ValueError, match="SAKURA_MODEL_ID"):
        SakuraSettings.from_env()
    monkeypatch.setenv("SAKURA_MODEL_ID", "test-model")
    settings = SakuraSettings.from_env()
    assert settings.api_key == "test-key"
    assert settings.model_id == "test-model"


async def test_text_arrives_before_http_stream_finishes(tmp_path):
    finish = asyncio.Event()

    class SlowStream(httpx2.AsyncByteStream):
        async def __aiter__(self):
            chunk = {
                "id": "slow",
                "object": "chat.completion.chunk",
                "created": 0,
                "model": "mock",
                "choices": [{"index": 0, "delta": {"content": "途中"}, "finish_reason": None}],
            }
            yield ("data: " + json.dumps(chunk) + "\n\n").encode()
            await finish.wait()
            chunk["choices"][0] = {"index": 0, "delta": {}, "finish_reason": "stop"}
            yield ("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode()

    def handle(request):
        return httpx2.Response(
            200, headers={"content-type": "text/event-stream"}, stream=SlowStream()
        )

    async with AsyncOpenAI(
        api_key="test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    ) as client:
        events = run_events(OpenAIModel(client=client, model_id="mock"))
        try:
            while True:
                event = await asyncio.wait_for(anext(events), 2)
                if event.type == "TEXT_MESSAGE_CONTENT":
                    break
            assert event.delta == "途中"
            assert not finish.is_set()
            finish.set()
            rest = [event async for event in events]
            assert rest[-1].type == "RUN_FINISHED"
        finally:
            finish.set()
            await events.aclose()


async def test_invalid_tool_input_reports_error_without_data(tmp_path, mcp_url):
    calls = 0

    def handle(request):
        nonlocal calls
        calls += 1
        answer = (
            completion(tool_message("search_transactions", {"limit": 201}), "tool_calls")
            if calls == 1
            else completion({"role": "assistant", "content": "失敗しました"}, "stop")
        )
        return response(answer, True)

    async with AsyncOpenAI(
        api_key="test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    ) as client:
        events = await collect(OpenAIModel(client=client, model_id="mock"), mcp_url=mcp_url)
    assert custom(events, "data_result") == []
    assert custom(events, "tool_status")[0]["status"] == "error"
    assert custom(events, "run_metrics")[0]["tool_errors"] == 1


async def test_ordinary_function_call_sample_works_without_mcp():
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        answer = (
            completion(tool_message("echo_text", {"text": "こんにちは"}), "tool_calls")
            if len(requests) == 1
            else completion({"role": "assistant", "content": "返しました。"}, "stop")
        )
        return response(answer, True)

    async with AsyncOpenAI(
        api_key="test-only",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    ) as client:
        events = await collect(OpenAIModel(client=client, model_id="mock"), "こんにちはを返して")
    assert [t["function"]["name"] for t in requests[0]["tools"]] == ["echo_text"]
    tool_result = next(m for m in requests[-1]["messages"] if m["role"] == "tool")
    assert json.loads(tool_result["content"]) == {"text": "こんにちは"}
    assert events[-1]["type"] == "RUN_FINISHED"
    assert custom(events, "run_metrics")[0]["tool_calls"] == 1
    assert custom(events, "data_result") == []
