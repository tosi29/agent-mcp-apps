"""Streamable HTTP server; local and IAM-protected AgentCore entrypoints."""

import argparse
import logging

import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse, PlainTextResponse

from exploration_mcp.comparison import compare_values


class RejectBrowserOrigin:
    """AgentCore owns authentication; browser calls must go through the host backend."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and any(k == b"origin" for k, _ in scope["headers"]):
            await PlainTextResponse("Origin not allowed", status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)


def create_app(*, agentcore: bool = False):
    server = MCPServer("exploration-comparison", subscriptions=False, log_level="WARNING")
    server.tool()(compare_values)

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
    logging.disable(logging.CRITICAL)
    return create_app(agentcore=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="ローカルMCPツールサーバー")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    uvicorn.run(
        create_app(), host="127.0.0.1", port=args.port, access_log=False, log_level="warning"
    )


if __name__ == "__main__":
    main()
