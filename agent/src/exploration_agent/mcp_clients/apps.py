"""Fetch the UI resource through MCP, never through model conversation state."""

from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

from exploration_agent.mcp_clients.agentcore import RuntimeAuth, runtime_url

APP_TOOL = "show_transaction_dashboard"
APP_URI = "ui://exploration/transaction-dashboard-v1.html"
APP_MIME = "text/html;profile=mcp-app"


async def load_app_resources(url: str | None, runtime_arn: str | None) -> dict:
    target = runtime_url(runtime_arn) if runtime_arn else url
    auth = RuntimeAuth() if runtime_arn else None
    # Strands' tool client does not expose Apps capability configuration. A separate
    # resource-only SDK session advertises it explicitly; the resource is immutable.
    async with (
        create_mcp_http_client(auth=auth) as http_client,
        # AgentCore answers the session DELETE with 404.
        streamable_http_client(
            target, http_client=http_client, terminate_on_close=False
        ) as streams,
        ClientSession(
            *streams[:2],
            read_timeout_seconds=10,
            extensions={"io.modelcontextprotocol/ui": {"mimeTypes": [APP_MIME]}},
        ) as session,
    ):
        await session.initialize()
        resource = await session.read_resource(APP_URI)
    return {"resourceUri": APP_URI, "mimeType": APP_MIME, "html": resource.contents[0].text}
