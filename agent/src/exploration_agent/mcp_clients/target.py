"""The one allowed exploration MCP server for this process, validated at startup."""

from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx2

from exploration_agent.mcp_clients.agentcore import RuntimeAuth, runtime_url


@dataclass(frozen=True)
class MCPTarget:
    url: str
    # A factory, because RuntimeAuth holds the session ID of one connection.
    auth: Callable[[], httpx2.Auth | None] = lambda: None
    startup_timeout: int = 5


def local_target(url: str) -> MCPTarget:
    if urlparse(url).hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("MCP URLにはループバックのhttp://127.0.0.1:8001/mcp等を指定してください")
    return MCPTarget(url)


def runtime_target(arn: str) -> MCPTarget:
    return MCPTarget(runtime_url(arn), auth=RuntimeAuth, startup_timeout=60)
