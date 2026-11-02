"""Real Strands + OpenAI provider; only the external HTTP service is simulated.

These tests prove local SDK integration, not Sakura API compatibility or model quality.
"""

import asyncio
import json

import httpx2
import pytest
from openai import AsyncOpenAI
from strands.models.openai import OpenAIModel

from exploration_agent.cli import output
from exploration_agent.runtime import SakuraSettings, stream_question


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


@pytest.mark.parametrize("streaming", [True, False])
async def test_real_sdk_tool_loop_and_data_separation(parquet, tmp_path, streaming):
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
        events = [
            event
            async for event in stream_question(
                "合成データを検索", model, parquet, tmp_path / "results"
            )
        ]
    assert len(requests) == 3
    search_spec = next(
        item["function"]
        for item in requests[0]["tools"]
        if item["function"]["name"] == "search_transactions"
    )
    assert "tool_context" not in search_spec["parameters"]["properties"]
    assert all(request["stream"] is streaming for request in requests)
    assert events[-1]["type"] == "done"
    assert events[-1]["status"] == "success", events
    assert events[-1]["model_calls"] == 3
    assert events[-1]["tool_calls"] == 2
    assert events[-1]["tool_errors"] == 0
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    data = next(e for e in events if e["type"] == "data_result")
    assert data["tool_call_id"] == "call-search"
    assert len(data["preview_rows"]) == 20
    assert data["total_count"] == 360
    artifact = json.loads(
        (tmp_path / "results" / data["request_id"] / f"{data['result_id']}.json").read_text()
    )
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
        e["text"] for e in events if e["type"] == "text_delta"
    )
    types = [e["type"] for e in events]
    assert types.index("data_result") < max(i for i, t in enumerate(types) if t == "tool_end")


async def test_provider_error_is_terminal_and_not_leaked(parquet, tmp_path):
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
        events = [
            e
            async for e in stream_question(
                "テスト", OpenAIModel(client=client, model_id="mock"), parquet, tmp_path
            )
        ]
    assert calls == 1
    assert [e["type"] for e in events] == ["error", "done"]
    assert events[-1]["status"] == "error"
    assert "private-secret" not in json.dumps(events)


async def test_model_loop_has_a_hard_call_budget(parquet, tmp_path):
    calls = 0

    def handle(request):
        nonlocal calls
        calls += 1
        return response(
            completion(tool_message("describe_dataset", {}, f"call-{calls}"), "tool_calls"), True
        )

    async with AsyncOpenAI(
        api_key="test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    ) as client:
        events = [
            e
            async for e in stream_question(
                "テスト",
                OpenAIModel(client=client, model_id="mock"),
                parquet,
                tmp_path,
                max_model_calls=2,
            )
        ]
    assert calls == 2
    assert events[-1]["status"] == "error"


async def test_request_timeout(parquet, tmp_path):
    async def handle(request):
        await asyncio.sleep(1)
        return response(completion({"role": "assistant", "content": "unused"}, "stop"), True)

    async with AsyncOpenAI(
        api_key="test",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    ) as client:
        events = [
            e
            async for e in stream_question(
                "テスト",
                OpenAIModel(client=client, model_id="mock"),
                parquet,
                tmp_path,
                timeout_seconds=0.01,
            )
        ]
    assert events[-2]["code"] == "TimeoutError"
    assert events[-1]["status"] == "error"


def test_live_calls_require_explicit_configuration(monkeypatch):
    monkeypatch.delenv("SAKURA_FREE_PLAN_CONFIRMED", raising=False)
    with pytest.raises(ValueError, match="無償プラン"):
        SakuraSettings.from_env()
    monkeypatch.setenv("SAKURA_FREE_PLAN_CONFIRMED", "true")
    monkeypatch.delenv("SAKURA_API_KEY", raising=False)
    with pytest.raises(ValueError, match="SAKURA_API_KEY"):
        SakuraSettings.from_env()


def test_sse_frame_encoding(capsys):
    output({"request_id": "request", "seq": 1, "type": "text_delta", "text": "A\nB"}, True)
    encoded = capsys.readouterr().out
    assert encoded.startswith("id: request:1\nevent: text_delta\ndata: ")
    assert encoded.endswith("\n\n")
    assert json.loads(encoded.split("data: ")[1])["text"] == "A\nB"


async def test_text_arrives_before_http_stream_finishes(parquet, tmp_path):
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
        events = stream_question(
            "テスト", OpenAIModel(client=client, model_id="mock"), parquet, tmp_path
        )
        try:
            first = await asyncio.wait_for(anext(events), 2)
            assert first["type"] == "text_delta"
            assert first["text"] == "途中"
            assert not finish.is_set()
            finish.set()
            rest = [event async for event in events]
            assert rest[-1]["status"] == "success"
        finally:
            finish.set()
            await events.aclose()


async def test_invalid_tool_input_reports_error_without_data(parquet, tmp_path):
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
        events = [
            event
            async for event in stream_question(
                "テスト", OpenAIModel(client=client, model_id="mock"), parquet, tmp_path
            )
        ]
    assert not any(e["type"] == "data_result" for e in events)
    assert next(e for e in events if e["type"] == "tool_end")["status"] == "error"
    assert events[-1]["tool_errors"] == 1
