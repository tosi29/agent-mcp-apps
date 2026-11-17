"""Fetch the UI resource through MCP, never through model conversation state."""

from mcp import ClientSession
from mcp.client.streamable_http import (
    create_mcp_http_client,  # pyright: ignore[reportPrivateImportUsage]
    streamable_http_client,
)
from mcp.types import TextResourceContents

from exploration_agent.mcp_clients.target import MCPTarget

APP_TOOL = "show_transaction_dashboard"
APP_URI = "ui://exploration/transaction-dashboard-v1.html"
APP_MIME = "text/html;profile=mcp-app"


async def load_app_resources(target: MCPTarget) -> dict:
    # Strands' tool client does not expose Apps capability configuration. A separate
    # resource-only SDK session advertises it explicitly; the resource is immutable.
    async with (
        create_mcp_http_client(auth=target.auth()) as http_client,
        # AgentCore answers the session DELETE with 404.
        streamable_http_client(
            target.url, http_client=http_client, terminate_on_close=False
        ) as streams,
        ClientSession(
            *streams[:2],
            read_timeout_seconds=10,
            extensions={"io.modelcontextprotocol/ui": {"mimeTypes": [APP_MIME]}},
        ) as session,
    ):
        await session.initialize()
        resource = await session.read_resource(APP_URI)
    contents = resource.contents[0]
    if not isinstance(contents, TextResourceContents):
        raise ValueError("MCP App resource must be text")
    return {"resourceUri": APP_URI, "mimeType": APP_MIME, "html": contents.text}
