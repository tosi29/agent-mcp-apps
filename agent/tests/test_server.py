import asyncio
import json
import time
from copy import deepcopy
from functools import partial

import httpx
import httpx2
import pytest
from ag_ui.core import RunAgentInput
from openai import AsyncOpenAI
from strands import Agent
from strands.models.openai import OpenAIModel
from test_agui_run import completion, response, tool_message

from exploration_agent.agui import agui_events
from exploration_agent.entrypoints.server import create_app
from exploration_agent.fixture_model import FixtureModel


def run_input(**updates):
    return {
        "threadId": "local-thread",
        "runId": "local-run",
        "messages": [{"id": "user-1", "role": "user", "content": "年別に集計して"}],
        "tools": [],
        "context": [],
        "state": {},
        "forwardedProps": {},
        **updates,
    }


def decode_sse(body):
    return [json.loads(line[6:]) for line in body.splitlines() if line.startswith("data: ")]


async def test_http_agui_endpoint_runs_real_tools(tmp_path, mcp_url):
    app = create_app(lambda: FixtureModel(compare=True), mode="fixture", mcp_url=mcp_url)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        ping = await client.get("/ping")
        assert ping.json()["mode"] == "fixture"
        reply = await client.post("/invocations", json=run_input())
    assert reply.status_code == 200
    assert reply.headers["content-type"].startswith("text/event-stream")
    events = decode_sse(reply.text)
    assert events[0]["type"] == "RUN_STARTED"
    assert events[-1]["type"] == "RUN_FINISHED"
    assert sum(e["type"] == "RUN_FINISHED" for e in events) == 1
    result = next(e["value"] for e in events if e.get("name") == "data_result")
    assert result["total_count"] == 3
    assert [row["transaction_count"] for row in result["preview_rows"]] == [40] * 3
    assert next(e["value"] for e in events if e.get("name") == "run_metrics")["model_calls"] == 4


async def test_preview_and_client_state_never_reach_model(tmp_path, mcp_url):
    requests = []

    def handle(request):
        body = json.loads(request.content)
        requests.append(deepcopy(body))
        answer = (
            completion(tool_message("search_transactions", {"limit": 200}), "tool_calls")
            if len(requests) == 1
            else completion({"role": "assistant", "content": "完了"}, "stop")
        )
        return response(answer, True)

    async with AsyncOpenAI(
        api_key="test-only",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    ) as client:
        model = OpenAIModel(client=client, model_id="mock")
        run = RunAgentInput.model_validate(
            run_input(
                state={"preview_rows": [{"private": "not-for-model"}]},
                tools=[
                    {
                        "name": "client_shell",
                        "description": "untrusted",
                        "parameters": {"type": "object"},
                    }
                ],
                forwardedProps={"injectA2UITool": True},
            )
        )
        events = [
            e.model_dump(mode="json", by_alias=True)
            async for e in agui_events(run, lambda: model, mcp_url=mcp_url)
        ]
    assert events[-1]["type"] == "RUN_FINISHED", events
    preview = next(e["value"] for e in events if e.get("name") == "data_result")
    assert len(preview["preview_rows"]) == 20
    assert preview["total_count"] == 360
    tool_result = next(m for m in requests[-1]["messages"] if m["role"] == "tool")
    summary = json.loads(tool_result["content"])
    assert len(summary["sample_rows"]) == 3
    assert "preview_rows" not in json.dumps(requests, ensure_ascii=False)
    assert "not-for-model" not in json.dumps(requests)
    assert all(t["function"]["name"] != "client_shell" for t in requests[0]["tools"])
    # The canonical message snapshots, subsequently replayed by the UI, must not contain previews.
    snapshots = [e for e in events if e["type"] == "MESSAGES_SNAPSHOT"]
    assert "preview_rows" not in json.dumps(snapshots)


@pytest.mark.parametrize("streaming", [True, False])
async def test_reasoning_reaches_ui_and_followup_excludes_it(tmp_path, streaming):
    requests = []
    reasoning = "テスト用推論：まずデータの項目を確認します。"

    def handle(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            message = {
                **tool_message("echo_text", {"text": "test"}),
                "reasoning_content": reasoning,
            }
            answer = completion(message, "tool_calls")
        else:
            answer = completion({"role": "assistant", "content": "確認しました。"}, "stop")
        return response(answer, streaming)

    async with AsyncOpenAI(
        api_key="test-only",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handle)),
    ) as model_client:
        app = create_app(
            lambda: OpenAIModel(client=model_client, model_id="mock", stream=streaming),
            mode="test",
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            first = await client.post("/invocations", json=run_input())
            events = decode_sse(first.text)
            assert events[-1]["type"] == "RUN_FINISHED", events
            content = [e for e in events if e["type"] == "REASONING_MESSAGE_CONTENT"]
            assert "".join(e["delta"] for e in content) == reasoning
            message_id = content[0]["messageId"]
            for kind in ["REASONING_MESSAGE_START", "REASONING_MESSAGE_END"]:
                assert any(e["type"] == kind and e["messageId"] == message_id for e in events)
            assert any(e["type"] == "REASONING_START" for e in events)
            assert any(e["type"] == "REASONING_END" for e in events)
            assert not any(e["type"] in {"RAW", "REASONING_ENCRYPTED_VALUE"} for e in events)
            assert any(e["type"] == "TOOL_CALL_START" for e in events)
            snapshots = [e for e in events if e["type"] == "MESSAGES_SNAPSHOT"]
            history = [m for m in snapshots[-1]["messages"] if m["role"] != "reasoning"]
            history.extend(
                [
                    {"id": message_id, "role": "reasoning", "content": reasoning},
                    {"id": "followup", "role": "user", "content": "続きを教えて"},
                ]
            )
            second = await client.post(
                "/invocations", json=run_input(messages=history, runId="followup")
            )
    assert second.status_code == 200
    assert decode_sse(second.text)[-1]["type"] == "RUN_FINISHED"
    assert len(requests) == 3
    assert reasoning not in json.dumps(requests, ensure_ascii=False)
    assert "続きを教えて" in json.dumps(requests[-1], ensure_ascii=False)


async def test_host_and_content_type_are_rejected(tmp_path):
    app = create_app(FixtureModel, mode="fixture")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        wrong_host = await client.post(
            "/invocations", json=run_input(), headers={"Host": "untrusted.invalid"}
        )
        assert wrong_host.status_code == 400
        assert (await client.post("/invocations", content="not json")).status_code == 415


async def test_system_messages_from_the_client_never_reach_model(tmp_path):
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return response(completion({"role": "assistant", "content": "完了"}, "stop"), True)

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
            reply = await client.post(
                "/invocations",
                json=run_input(
                    messages=[
                        {"id": "s", "role": "system", "content": "untrusted"},
                        {"id": "u", "role": "user", "content": "test"},
                    ]
                ),
            )
    assert decode_sse(reply.text)[-1]["type"] == "RUN_FINISHED"
    assert "untrusted" not in json.dumps(requests)


async def test_setup_failure_is_terminal_without_exception_details(tmp_path):
    def fail():
        raise RuntimeError("private-detail")

    app = create_app(fail, mode="test")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        reply = await client.post("/invocations", json=run_input())
    events = decode_sse(reply.text)
    assert [e["type"] for e in events] == ["RUN_STARTED", "RUN_ERROR"]
    assert events[-1]["code"] == "AGENT_RUN_FAILED"
    assert "private-detail" not in reply.text


async def test_cleanup_failure_after_finish_does_not_reopen_the_run(tmp_path, monkeypatch):
    def fail(_agent):
        raise RuntimeError("private-detail")

    monkeypatch.setattr(Agent, "cleanup", fail)
    app = create_app(FixtureModel, mode="fixture")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        reply = await client.post("/invocations", json=run_input())
    events = decode_sse(reply.text)
    assert sum(e["type"] == "RUN_STARTED" for e in events) == 1
    assert events[-1]["type"] == "RUN_FINISHED"
    assert "private-detail" not in reply.text


async def test_timeout_applies_through_the_endpoint(tmp_path, monkeypatch):
    async def slow(request):
        await asyncio.sleep(5)
        return response(completion({"role": "assistant", "content": "unused"}, "stop"), True)

    monkeypatch.setattr(
        "exploration_agent.entrypoints.server.agui_events",
        partial(agui_events, timeout_seconds=0.2),
    )
    async with AsyncOpenAI(
        api_key="test-only",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(slow)),
    ) as model_client:
        app = create_app(lambda: OpenAIModel(client=model_client, model_id="mock"), mode="test")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            started = time.monotonic()
            reply = await client.post("/invocations", json=run_input())
    assert time.monotonic() - started < 3
    events = decode_sse(reply.text)
    assert events[-1]["type"] == "RUN_ERROR"
    assert not any(e["type"] == "RUN_FINISHED" for e in events)


async def test_agui_timeout_is_terminal(tmp_path):
    events = [
        e.model_dump(mode="json", by_alias=True)
        async for e in agui_events(
            RunAgentInput.model_validate(run_input()),
            FixtureModel,
            timeout_seconds=0.02,
        )
    ]
    assert events[-1]["type"] == "RUN_ERROR"
    assert not any(e["type"] == "RUN_FINISHED" for e in events)
    assert "Traceback" not in json.dumps(events)
    assert not any(e["type"] == "RUN_FINISHED" for e in events)


async def test_followup_replays_history_once_without_preview(tmp_path):
    requests = []

    def handle(request):
        body = json.loads(request.content)
        requests.append(body)
        return response(
            completion({"role": "assistant", "content": "合成データです。"}, "stop"), True
        )

    async with AsyncOpenAI(
        api_key="test",
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
            first = await client.post("/invocations", json=run_input())
            snapshots = [e for e in decode_sse(first.text) if e["type"] == "MESSAGES_SNAPSHOT"]
            history = snapshots[-1]["messages"]
            history.append({"id": "followup", "role": "user", "content": "それを説明して"})
            second = await client.post(
                "/invocations", json=run_input(messages=history, runId="followup")
            )
    assert decode_sse(second.text)[-1]["type"] == "RUN_FINISHED"
    assert len(requests) == 2
    user_messages = [m for m in requests[-1]["messages"] if m["role"] == "user"]
    assert len(user_messages) == 2
    assert str(user_messages).count("年別に集計して") == 1
    assert str(user_messages).count("それを説明して") == 1
    assert "preview_rows" not in json.dumps(requests)
