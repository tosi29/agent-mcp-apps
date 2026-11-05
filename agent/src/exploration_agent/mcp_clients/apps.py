"""Fetch the UI resource through MCP, never through model conversation state."""

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from exploration_agent.mcp_clients.agentcore import runtime_transport

APP_TOOL = "show_transaction_dashboard"
APP_URI = "ui://exploration/transaction-dashboard-v1.html"
APP_MIME = "text/html;profile=mcp-app"


async def load_app_resources(url: str | None, runtime_arn: str | None) -> dict:
    transport = runtime_transport(runtime_arn) if runtime_arn else streamable_http_client(url)
    # Strands' tool client does not expose Apps capability configuration. A separate
    # resource-only SDK session advertises it explicitly; the resource is immutable.
    async with transport as streams:
        async with ClientSession(
            *streams[:2],
            read_timeout_seconds=10,
            extensions={"io.modelcontextprotocol/ui": {"mimeTypes": [APP_MIME]}},
        ) as session:
            await session.initialize()
            resource = await session.read_resource(APP_URI)
    return {"resourceUri": APP_URI, "mimeType": APP_MIME, "html": resource.contents[0].text}
