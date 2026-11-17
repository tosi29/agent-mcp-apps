"""Local AG-UI endpoint, also used by the AgentCore entrypoint."""

import logging
from collections.abc import Callable, Sequence
from functools import partial
from types import SimpleNamespace
from typing import cast

import uvicorn
from ag_ui_strands import StrandsAgent, add_strands_fastapi_endpoint
from fastapi import FastAPI, Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from strands.models.model import Model

from exploration_agent.agui import agui_events
from exploration_agent.fixture_model import FixtureModel
from exploration_agent.mcp_clients.resources import RESULT_CSV_URI, read_result_csv
from exploration_agent.mcp_clients.target import MCPTarget, local_target, runtime_target
from exploration_agent.model import sakura_factory_from_env
from exploration_agent.observability import configure_observability

logger = logging.getLogger(__name__)


def create_app(
    model_factory: Callable[[], Model],
    *,
    mode: str,
    mcp: MCPTarget | None = None,
    trusted_hosts: Sequence[str] = ("127.0.0.1", "localhost"),
    result_downloads: bool = True,
) -> FastAPI:
    configure_observability()
    app = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)

    @app.get("/ping")
    async def ping():
        return {"status": "Healthy", "mode": mode}

    if result_downloads and mcp is not None:
        target = mcp

        @app.get("/resources/read")
        async def read_resource(uri: str):
            """Follow a result CSV resource_link for the UI. The model is not involved."""
            if not RESULT_CSV_URI.fullmatch(uri):
                return Response("unsupported resource", status_code=400)
            try:
                text = await read_result_csv(target, uri)
            except Exception:
                # Expired IDs and MCP failures look the same to the client; details stay in logs.
                logger.exception("Result CSV read failed uri=%s", uri)
                return Response("resource unavailable", status_code=404)
            return Response(
                text,
                media_type="text/csv; charset=utf-8",
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )

    # The endpoint only calls run(), so each run can get its own agent and MCP connection.
    # The runner duck-types StrandsAgent for that one method.
    runner = SimpleNamespace(run=partial(agui_events, model_factory=model_factory, mcp=mcp))
    add_strands_fastapi_endpoint(app, cast(StrandsAgent, runner), "/invocations")
    return app


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="ローカルAG-UIサーバー")
    parser.add_argument("--model", choices=["sakura", "fixture"], default="sakura")
    parser.add_argument("--port", type=int, default=8000)
    mcp = parser.add_mutually_exclusive_group()
    mcp.add_argument(
        "--mcp-url",
        dest="mcp",
        type=local_target,
        help="ローカルMCPサーバーのURL（例：http://127.0.0.1:8001/mcp）",
    )
    mcp.add_argument(
        "--mcp-runtime-arn",
        dest="mcp",
        type=runtime_target,
        help="IAM認証で接続する東京のMCP Runtime ARN",
    )
    args = parser.parse_args()
    uvicorn.run(
        create_app(
            FixtureModel if args.model == "fixture" else sakura_factory_from_env(),
            mode=args.model,
            mcp=args.mcp,
        ),
        host="127.0.0.1",
        port=args.port,
        access_log=True,
    )


if __name__ == "__main__":
    main()
