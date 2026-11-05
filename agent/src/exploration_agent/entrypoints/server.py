"""Local AG-UI endpoint, also used by the AgentCore entrypoint."""

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from functools import partial

import uvicorn
from ag_ui.core import EventType, RunAgentInput, RunErrorEvent, RunStartedEvent
from ag_ui_strands import add_strands_fastapi_endpoint
from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware
from strands.models.model import Model

from exploration_agent.entrypoints.agui import agui_events
from exploration_agent.fixture_model import FixtureModel
from exploration_agent.model import SakuraSettings
from exploration_agent.observability import configure_observability

logger = logging.getLogger(__name__)


class ExplorationRunner:
    """The endpoint only calls run(), so each run can get its own agent and MCP connection."""

    def __init__(
        self,
        model_factory: Callable[[], Model],
        *,
        mcp_url: str | None,
        mcp_runtime_arn: str | None,
    ):
        self.model_factory = model_factory
        self.mcp_url = mcp_url
        self.mcp_runtime_arn = mcp_runtime_arn

    async def run(self, run: RunAgentInput) -> AsyncIterator:
        try:
            # The cloud factory can fetch a SecureString. Keep that I/O off the event loop.
            model = await asyncio.to_thread(self.model_factory)
            async for event in agui_events(
                run, model, mcp_url=self.mcp_url, mcp_runtime_arn=self.mcp_runtime_arn
            ):
                yield event
        except Exception:
            # The endpoint would send str(error) to the client. Log it and send a fixed message.
            logger.exception("Agent setup failed run_id=%s", run.run_id)
            yield RunStartedEvent(
                type=EventType.RUN_STARTED, thread_id=run.thread_id, run_id=run.run_id
            )
            yield RunErrorEvent(
                type=EventType.RUN_ERROR,
                code="AGENT_SETUP_FAILED",
                message="エージェントの準備に失敗しました。設定を確認してください。",
            )


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

    @app.get("/ping")
    async def ping():
        return {"status": "Healthy", "mode": mode, "dataset": "synthetic-real-estate-v1"}

    add_strands_fastapi_endpoint(
        app,
        ExplorationRunner(model_factory, mcp_url=mcp_url, mcp_runtime_arn=mcp_runtime_arn),
        "/invocations",
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
