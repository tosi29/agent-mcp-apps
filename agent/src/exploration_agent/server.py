"""Local AG-UI endpoint. Request state and UI previews never become model state."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import uvicorn
from ag_ui.core import CustomEvent, EventType, RunAgentInput, RunErrorEvent, RunStartedEvent
from ag_ui.encoder import EventEncoder
from ag_ui_strands import StrandsAgent, StrandsAgentConfig, ToolBehavior
from ag_ui_strands.config import ToolResultContext
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from strands import Agent
from strands.models.model import Model

from exploration_agent.data import DataExplorer
from exploration_agent.fixture_model import FixtureModel
from exploration_agent.results import ResultStore
from exploration_agent.runtime import SYSTEM_PROMPT, RequestHooks, SakuraSettings, build_tools

MAX_BODY_BYTES = 128 * 1024
ALLOWED_ORIGINS = {"http://127.0.0.1:3000", "http://localhost:3000"}


async def agui_events(
    run: RunAgentInput,
    model: Model,
    parquet: Path,
    results_dir: Path,
    *,
    max_model_calls: int = 4,
    timeout_seconds: float = 120,
) -> AsyncIterator:
    """Use the maintained Strands adapter, with fresh per-request budgets and tools."""
    request_id = uuid4().hex
    previews: dict[str, dict] = {}
    statuses: dict[str, dict] = {}

    def observe(event_type: str, **payload: Any) -> None:
        if event_type == "data_result":
            previews[payload["tool_call_id"]] = {"request_id": request_id, **payload}
        elif event_type == "tool_end":
            statuses[payload["tool_call_id"]] = payload

    async def custom_result(context: ToolResultContext):
        if preview := previews.pop(context.tool_use_id, None):
            yield CustomEvent(type=EventType.CUSTOM, name="data_result", value=preview)
        if status := statuses.pop(context.tool_use_id, None):
            yield CustomEvent(type=EventType.CUSTOM, name="tool_status", value=status)

    hooks = RequestHooks(observe, max_model_calls)
    explorer = DataExplorer(parquet)
    await asyncio.to_thread(explorer.describe)
    template = Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=build_tools(explorer, ResultStore(results_dir / request_id), observe),
        callback_handler=None,
        retry_strategy=None,
    )
    adapter = StrandsAgent(
        agent=template,
        name="explorer",
        hooks=[hooks],
        config=StrandsAgentConfig(
            tool_behaviors={
                name: ToolBehavior(custom_result_handler=custom_result)
                for name in ("describe_dataset", "search_transactions", "aggregate_transactions")
            },
            # Explicitly preserve no-retry behavior when the adapter clones the template.
            thread_agent_kwargs=lambda _: {"retry_strategy": None, "callback_handler": None},
        ),
    )
    # Do not expose frontend tools, arbitrary UI state, attachments, or injected A2UI configuration.
    trusted_run = run.model_copy(
        update={
            "tools": [],
            "context": [],
            "state": {},
            "forwarded_props": {},
            "resume": None,
        }
    )
    started = False
    try:
        async with asyncio.timeout(timeout_seconds):
            async for event in adapter.run(trusted_run):
                if event.type == EventType.RUN_STARTED:
                    started = True
                if event.type in {EventType.RAW} or event.type.value.startswith("REASONING"):
                    continue
                if event.type == EventType.RUN_ERROR:
                    yield RunErrorEvent(
                        type=EventType.RUN_ERROR,
                        code="AGENT_RUN_FAILED",
                        message="実行に失敗しました。接続・設定・実行上限を確認してください。",
                    )
                    return
                if event.type == EventType.RUN_FINISHED:
                    yield CustomEvent(
                        type=EventType.CUSTOM,
                        name="run_metrics",
                        value={
                            "model_calls": hooks.model_calls,
                            "tool_calls": hooks.tool_calls,
                            "tool_errors": hooks.tool_errors,
                        },
                    )
                yield event
    except Exception:
        if not started:
            yield RunStartedEvent(
                type=EventType.RUN_STARTED,
                thread_id=run.thread_id,
                run_id=run.run_id,
            )
        yield RunErrorEvent(
            type=EventType.RUN_ERROR,
            code="AGENT_RUN_FAILED",
            message="実行に失敗しました。接続・設定・実行上限を確認してください。",
        )


def create_app(
    model_factory: Callable[[], Model],
    parquet: Path,
    results_dir: Path,
    *,
    mode: str,
    trusted_hosts: list[str] | None = None,
) -> FastAPI:
    app = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        telemetry={
            "auto_configure": False,
            "tracing": False,
            "metrics": False,
            "logs": False,
            "operation_spans": False,
        },
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=trusted_hosts
        if trusted_hosts is not None
        else ["127.0.0.1", "localhost", "testserver"],
    )
    busy = asyncio.Lock()

    @app.middleware("http")
    async def origin_guard(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin not in ALLOWED_ORIGINS:
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "origin not allowed"}, status_code=403)
        return await call_next(request)

    @app.get("/ping")
    async def ping():
        return {"status": "Healthy", "mode": mode, "dataset": "synthetic-real-estate-v1"}

    @app.post("/invocations")
    async def invocations(request: Request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_BODY_BYTES:
                raise HTTPException(413, "request too large")
        try:
            run = RunAgentInput.model_validate_json(body)
        except ValueError:
            raise HTTPException(422, "invalid AG-UI request") from None
        if len(run.messages) > 40:
            raise HTTPException(422, "conversation too long; start a new conversation")
        if not run.messages or run.messages[-1].role != "user":
            raise HTTPException(422, "a new user message is required")
        for message in run.messages:
            if message.role not in {"user", "assistant", "tool"}:
                raise HTTPException(422, "only conversation messages are accepted")
            if message.content is not None and not isinstance(message.content, str):
                raise HTTPException(422, "only text messages are accepted")
        prompt = run.messages[-1].content
        if not prompt or not prompt.strip() or len(prompt) > 4000:
            raise HTTPException(422, "prompt must contain 1–4000 characters")
        if busy.locked():
            raise HTTPException(429, "another request is running")
        await busy.acquire()
        encoder = EventEncoder(accept="text/event-stream")

        async def generate():
            try:
                async for event in agui_events(run, model_factory(), parquet, results_dir):
                    yield encoder.encode(event)
            except Exception:
                yield encoder.encode(
                    RunStartedEvent(
                        type=EventType.RUN_STARTED,
                        thread_id=run.thread_id,
                        run_id=run.run_id,
                    )
                )
                yield encoder.encode(
                    RunErrorEvent(
                        type=EventType.RUN_ERROR,
                        code="AGENT_SETUP_FAILED",
                        message="エージェントの準備に失敗しました。設定を確認してください。",
                    )
                )
            finally:
                busy.release()

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    return app


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="ローカルAG-UIサーバー")
    parser.add_argument("--model", choices=["sakura", "fixture"], default="sakura")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data", type=Path, default=Path("data/synthetic.parquet"))
    parser.add_argument("--results", type=Path, default=Path("results"))
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    if args.model == "sakura":
        settings = SakuraSettings.from_env()
        factory = settings.build_model
    else:
        factory = FixtureModel
    DataExplorer(args.data).describe()
    uvicorn.run(
        create_app(factory, args.data, args.results, mode=args.model),
        host="127.0.0.1",
        port=args.port,
        access_log=False,
    )


if __name__ == "__main__":
    main()
