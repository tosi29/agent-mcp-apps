"""Loopback-only Streamable HTTP server with single JSON responses."""

import argparse

import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from exploration_mcp.comparison import compare_values


def create_app():
    server = MCPServer("exploration-comparison", subscriptions=False, log_level="WARNING")
    server.tool()(compare_values)
    return server.streamable_http_app(
        json_response=True,
        stateless_http=True,
        max_request_body_size=128 * 1024,
        transport_security=TransportSecuritySettings(
            allowed_hosts=["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*"],
            allowed_origins=[],
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="ローカルMCPツールサーバー")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    uvicorn.run(
        create_app(), host="127.0.0.1", port=args.port, access_log=False, log_level="warning"
    )


if __name__ == "__main__":
    main()
