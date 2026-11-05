"""Local AG-UI endpoint, also used by the AgentCore entrypoint."""

from collections.abc import Callable
from functools import partial
from types import SimpleNamespace

import uvicorn
from ag_ui_strands import add_strands_fastapi_endpoint
from fastapi import FastAPI
from starlette.middleware.trustedhost import TrustedHostMiddleware
from strands.models.model import Model

from exploration_agent.agui import agui_events
from exploration_agent.model import build_model_factory
from exploration_agent.observability import configure_observability


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
        return {"status": "Healthy", "mode": mode}

    # The endpoint only calls run(), so each run can get its own agent and MCP connection.
    runner = SimpleNamespace(
        run=partial(
            agui_events,
            model_factory=model_factory,
            mcp_url=mcp_url,
            mcp_runtime_arn=mcp_runtime_arn,
        )
    )
    add_strands_fastapi_endpoint(app, runner, "/invocations")
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
    uvicorn.run(
        create_app(
            build_model_factory(args.model, compare=bool(args.mcp_url or args.mcp_runtime_arn)),
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
