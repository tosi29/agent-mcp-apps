"""Local AG-UI endpoint, also used by the AgentCore entrypoint."""

import asyncio
import logging
from collections.abc import Callable
from functools import partial

import uvicorn
from ag_ui.core import EventType, RunAgentInput, RunErrorEvent, RunStartedEvent
from ag_ui.encoder import EventEncoder
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from strands.models.model import Model

from exploration_agent.entrypoints.agui import agui_events
from exploration_agent.fixture_model import FixtureModel
from exploration_agent.model import SakuraSettings
from exploration_agent.observability import configure_observability

MAX_BODY_BYTES = 128 * 1024
logger = logging.getLogger(__name__)
ALLOWED_ORIGINS = {"http://127.0.0.1:3000", "http://localhost:3000"}


def create_app(
    model_factory: Callable[[], Model],
    *,
    mode: str,
    mcp_url: str | None = None,
    mcp_runtime_arn: str | None = None,
    trusted_hosts: list[str] | None = None,
) -> FastAPI:
    configure_observability()
    app = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
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
        # Reasoning is displayed by the client, but is not replayed as conversation input.
        run = run.model_copy(
            update={
                "messages": [message for message in run.messages if message.role != "reasoning"]
            }
        )
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
                # The cloud factory can fetch a SecureString. Keep that I/O off the event loop.
                model = await asyncio.to_thread(model_factory)
                async for event in agui_events(
                    run,
                    model,
                    mcp_url=mcp_url,
                    mcp_runtime_arn=mcp_runtime_arn,
                ):
                    yield encoder.encode(event)
            except Exception:
                logger.exception("Agent setup failed run_id=%s", run.run_id)
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
    mcp = parser.add_mutually_exclusive_group()
    mcp.add_argument("--mcp-url", help="ローカルMCPサーバーのURL（例：http://127.0.0.1:8001/mcp）")
    mcp.add_argument("--mcp-runtime-arn", help="IAM認証で接続する東京のMCP Runtime ARN")
    args = parser.parse_args()
    configure_observability()
    if args.model == "sakura":
        settings = SakuraSettings.from_env()
        factory = settings.build_model
    else:
        factory = partial(FixtureModel, compare=bool(args.mcp_url or args.mcp_runtime_arn))
    uvicorn.run(
        create_app(
            factory,
            mode=args.model,
            mcp_url=args.mcp_url,
            mcp_runtime_arn=args.mcp_runtime_arn,
        ),
        host="127.0.0.1",
        port=args.port,
        access_log=True,
    )


if __name__ == "__main__":
    main()
