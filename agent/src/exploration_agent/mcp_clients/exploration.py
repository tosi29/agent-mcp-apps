"""The exploration MCP client and its fixed tool names."""

from strands.tools.mcp import MCPClient

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


def build_mcp_clients(target: MCPTarget | None) -> list[MCPClient]:
    """Build the client for Agent(tools=...), which connects and closes it."""
    if target is None:
        return []
    return [
        MCPClient(
            url=target.url,
            # Strands annotates httpx.Auth, but passes it to the MCP SDK, which uses httpx2.
            auth_provider=target.auth(),  # pyright: ignore[reportArgumentType]
            startup_timeout=target.startup_timeout,
            tool_filters={"allowed": list(MCP_TOOL_NAMES)},
        )
    ]
