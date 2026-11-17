"""Read MCP resources on a separate SDK session, never through model conversation state."""

from mcp import ClientSession
from mcp.client.streamable_http import (
    create_mcp_http_client,  # pyright: ignore[reportPrivateImportUsage]
    streamable_http_client,
)
from mcp.types import TextResourceContents

from exploration_agent.mcp_clients.target import MCPTarget


async def read_text_resource(
    target: MCPTarget, uri: str, *, extensions: dict | None = None
) -> TextResourceContents:
    async with (
        create_mcp_http_client(auth=target.auth()) as http_client,
        # AgentCore answers the session DELETE with 404.
        streamable_http_client(
            target.url, http_client=http_client, terminate_on_close=False
        ) as streams,
        ClientSession(*streams[:2], read_timeout_seconds=10, extensions=extensions) as session,
    ):
        await session.initialize()
        resource = await session.read_resource(uri)
    contents = resource.contents[0]
    if not isinstance(contents, TextResourceContents):
        raise ValueError("MCP resource must be text")
    return contents
