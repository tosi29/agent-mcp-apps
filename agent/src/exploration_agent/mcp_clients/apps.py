"""Fetch the UI resource through MCP, never through model conversation state."""

from exploration_agent.mcp_clients.resources import read_text_resource
from exploration_agent.mcp_clients.target import MCPTarget

APP_TOOL = "show_transaction_dashboard"
APP_URI = "ui://exploration/transaction-dashboard-v1.html"
APP_MIME = "text/html;profile=mcp-app"


async def load_app_resources(target: MCPTarget) -> dict:
    # Strands' tool client does not expose Apps capability configuration. A separate
    # resource-only SDK session advertises it explicitly; the resource is immutable.
    contents = await read_text_resource(
        target, APP_URI, extensions={"io.modelcontextprotocol/ui": {"mimeTypes": [APP_MIME]}}
    )
    return {"resourceUri": APP_URI, "mimeType": APP_MIME, "html": contents.text}
