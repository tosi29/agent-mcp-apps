"""Fetch a bounded UI resource through MCP, never through model conversation state."""

from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from strands.tools.mcp import MCPAgentTool

from exploration_agent.agentcore_mcp import runtime_transport

APP_TOOL = "show_transaction_dashboard"
APP_URI = "ui://exploration/transaction-dashboard-v1.html"
APP_MIME = "text/html;profile=mcp-app"
MAX_APP_HTML_BYTES = 768 * 1024


async def load_app_resources(
    tools: list[MCPAgentTool], url: str | None, runtime_arn: str | None
) -> dict[str, dict]:
    tool = next((tool for tool in tools if tool.tool_name == APP_TOOL), None)
    if tool is None:
        return {}
    meta = tool.mcp_tool.meta or {}
    if meta.get("ui", {}).get("resourceUri") != APP_URI:
        raise ValueError("MCP AppのUIリソースが許可対象と異なります")

    @asynccontextmanager
    async def transport():
        if runtime_arn:
            async with runtime_transport(runtime_arn) as streams:
                yield streams
        else:
            async with streamable_http_client(url) as streams:
                yield streams

    # Strands' tool client does not expose Apps capability configuration. A separate
    # resource-only SDK session advertises it explicitly; the resource is immutable.
    async with transport() as streams:
        async with ClientSession(
            *streams[:2],
            read_timeout_seconds=10,
            extensions={"io.modelcontextprotocol/ui": {"mimeTypes": [APP_MIME]}},
        ) as session:
            await session.initialize()
            resource = await session.read_resource(APP_URI)
    if len(resource.contents) != 1:
        raise ValueError("MCP Appのリソース数が不正です")
    content = resource.contents[0]
    html = getattr(content, "text", None)
    if (
        content.mime_type != APP_MIME
        or not isinstance(html, str)
        or len(html.encode("utf-8")) > MAX_APP_HTML_BYTES
    ):
        raise ValueError("MCP AppのHTML形式またはサイズが不正です")
    csp = (content.meta or {}).get("ui", {}).get("csp", {})
    if any(csp.get(key) for key in ("connectDomains", "resourceDomains", "frameDomains")):
        raise ValueError("このPoCのMCP Appは外部リソースを読み込めません")
    return {APP_TOOL: {"resourceUri": APP_URI, "mimeType": APP_MIME, "html": html}}
