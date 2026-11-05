"""The exploration MCP client and its fixed tool names."""

from urllib.parse import urlparse

from strands.tools.mcp import MCPClient

from exploration_agent.mcp_clients.agentcore import RuntimeAuth, runtime_url
from exploration_agent.mcp_clients.apps import APP_TOOL

MCP_TOOL_NAMES = (
    "describe_dataset",
    "search_transactions",
    "aggregate_transactions",
    "compare_values",
    APP_TOOL,
)
RESULT_TOOLS = {"search_transactions", "aggregate_transactions", "compare_values", APP_TOOL}


def build_mcp_clients(url: str | None, runtime_arn: str | None) -> list[MCPClient]:
    """Build the client for Agent(tools=...), which connects and closes it."""
    if runtime_arn is not None:
        return [
            MCPClient(
                url=runtime_url(runtime_arn),
                auth_provider=RuntimeAuth(),
                startup_timeout=60,
                tool_filters={"allowed": list(MCP_TOOL_NAMES)},
            )
        ]
    if url is None:
        return []
    if urlparse(url).hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("MCP URLにはループバックのhttp://127.0.0.1:8001/mcp等を指定してください")
    return [MCPClient(url=url, startup_timeout=5, tool_filters={"allowed": list(MCP_TOOL_NAMES)})]
