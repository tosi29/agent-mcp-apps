"""The exploration MCP client and its fixed tool names."""

import re
from typing import Any

from mcp.types import ResourceLink
from strands.tools.mcp import MCPClient
from strands.types.tools import ToolResultContent

from exploration_agent.mcp_clients.apps import APP_TOOL
from exploration_agent.mcp_clients.target import MCPTarget

MCP_TOOL_NAMES = (
    "describe_dataset",
    "search_transactions",
    "aggregate_transactions",
    "compare_values",
    APP_TOOL,
)
RESULT_TOOLS = {"search_transactions", "aggregate_transactions", "compare_values", APP_TOOL}
# Key of the JSON block that carries a resource_link from the MCP client to ToolResultHook.
RESOURCE_LINK_KEY = "mcpResourceLink"
# The only resource_link forwarded to the UI. The MCP server publishes this template.
RESULT_CSV_URI = re.compile(r"exploration://results/[0-9a-f]{32}\.csv")
RESULT_CSV_MIME = "text/csv"


class ExplorationMCPClient(MCPClient):
    """Strands drops resource_link content. Keep it so the hook can move it to the UI."""

    def map_mcp_content_to_tool_result_content(self, content: Any) -> ToolResultContent | None:
        if isinstance(content, ResourceLink):
            link = content.model_dump(mode="json", by_alias=True, exclude_none=True)
            return {"json": {RESOURCE_LINK_KEY: link}}
        return super().map_mcp_content_to_tool_result_content(content)


def build_mcp_clients(target: MCPTarget | None) -> list[ExplorationMCPClient]:
    """Build the client for Agent(tools=...), which connects and closes it."""
    if target is None:
        return []
    return [
        ExplorationMCPClient(
            url=target.url,
            # Strands annotates httpx.Auth, but passes it to the MCP SDK, which uses httpx2.
            auth_provider=target.auth(),  # pyright: ignore[reportArgumentType]
            startup_timeout=target.startup_timeout,
            tool_filters={"allowed": list(MCP_TOOL_NAMES)},
        )
    ]
