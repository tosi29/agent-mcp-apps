"""Streamable HTTP server; local and IAM-protected AgentCore entrypoints."""

import argparse
import json
import os
from pathlib import Path
from typing import Any, cast

import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse, PlainTextResponse

from exploration_mcp.apps import dashboard_app
from exploration_mcp.data import DataExplorer, Filters, prepare_sample
from exploration_mcp.observability import configure_observability
from exploration_mcp.results import ResultStore
from exploration_mcp.tools import register_tools


class RejectBrowserOrigin:
    """AgentCore owns authentication; browser calls must go through the host backend."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and any(k == b"origin" for k, _ in scope["headers"]):
            await PlainTextResponse("Origin not allowed", status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app(
    *, agentcore: bool = False, data_path: Path | None = None, results_dir: Path | None = None
):
    configure_observability()
    explorer = DataExplorer(
        data_path or Path(os.environ.get("MCP_DATA_PATH", "data/synthetic.parquet"))
    )
    # Connections are closed before Runtime V2 can capture its startup snapshot.
    explorer.describe()
    default_results = "/tmp/results" if agentcore else "results"
    store = ResultStore(results_dir or Path(os.environ.get("MCP_RESULTS_DIR", default_results)))
    server = MCPServer(
        "exploration-tools",
        subscriptions=False,
        # MCPServer validates the level at runtime; the environment value is only a str here.
        log_level=cast(Any, os.environ.get("LOG_LEVEL", "INFO")),
        extensions=[dashboard_app(explorer, store)],
    )
    register_tools(server, explorer, store)

    @server.custom_route("/ping", methods=["GET"])
    async def ping(_request):
        return JSONResponse({"status": "Healthy"})

    app = server.streamable_http_app(
        json_response=True,
        stateless_http=True,
        max_request_body_size=128 * 1024,
        transport_security=TransportSecuritySettings(
            # Runtime forwards an internal Host. IAM is enforced before reaching the container.
            enable_dns_rebinding_protection=not agentcore,
            allowed_hosts=["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*"],
            allowed_origins=[],
        ),
    )
    if agentcore:
        app.add_middleware(RejectBrowserOrigin)
    return app


def create_agentcore_app():
    return create_app(agentcore=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="ローカルMCPツールサーバー")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument(
        "--data", type=Path, default=Path(os.environ.get("MCP_DATA_PATH", "data/synthetic.parquet"))
    )
    parser.add_argument(
        "--results", type=Path, default=Path(os.environ.get("MCP_RESULTS_DIR", "results"))
    )
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("prepare-sample", help="合成Parquetを生成する（モデルAPI不要）")
    commands.add_parser("inspect", help="データ項目を確認する（モデルAPI不要）")
    commands.add_parser("query-demo", help="新宿区を年別集計する（モデルAPI不要）")
    result = commands.add_parser("result", help="同じMCP環境の保存結果を読む（モデルAPI不要）")
    result.add_argument("result_id")
    args = parser.parse_args()
    if args.command == "prepare-sample":
        prepare_sample(args.data)
        print(json.dumps({"row_count": 360, "path": str(args.data), "synthetic": True}))
        return
    queries = {
        "result": lambda: ResultStore(args.results).get(args.result_id),
        "inspect": lambda: DataExplorer(args.data).describe(),
        "query-demo": lambda: DataExplorer(args.data).aggregate("year", Filters("新宿区")),
    }
    if args.command:
        print(json.dumps(queries[args.command](), ensure_ascii=False, allow_nan=False))
        return
    uvicorn.run(
        create_app(data_path=args.data, results_dir=args.results),
        host="127.0.0.1",
        port=args.port,
        access_log=True,
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
