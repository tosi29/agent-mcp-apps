"""Optional public documentation MCP servers. The app fixes URLs, tools and limits."""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry
from strands.tools.mcp import MCPClient
from strands.types.tools import AgentTool

logger = logging.getLogger(__name__)


DOCS_SERVERS = {
    "https://knowledge-mcp.global.api.aws": (
        "aws___search_documentation",
        "aws___read_documentation",
        "aws___list_regions",
        "aws___get_regional_availability",
    ),
    "https://learn.microsoft.com/api/mcp": (
        "microsoft_docs_search",
        "microsoft_docs_fetch",
        "microsoft_code_sample_search",
    ),
}
DOCS_TOOL_NAMES = frozenset(name for tools in DOCS_SERVERS.values() for name in tools)
MAX_RESULT_CHARS = 8000
TOOL_TIMEOUT = timedelta(seconds=20)
TRUNCATED_NOTICE = "（上限に達したため以降を省略しました）"


class OptionalMCPClient(MCPClient):
    """continue_on_error covers startup only. A failed tool listing must not stop the run either."""

    async def load_tools(self, **kwargs: Any) -> Sequence[AgentTool]:
        try:
            return await super().load_tools(**kwargs)
        except Exception as error:
            logger.warning("docs_mcp_unavailable error=%s", type(error).__name__)
            return []


def build_docs_clients() -> list[MCPClient]:
    if os.environ.get("DOCS_MCP_ENABLED", "").strip().lower() != "true":
        return []
    return [
        OptionalMCPClient(
            url=url,
            startup_timeout=5,
            tool_filters={"allowed": list(tools)},
            continue_on_error=True,
        )
        for url, tools in DOCS_SERVERS.items()
    ]


class DocsMCPHook(HookProvider):
    """Per-call timeout, and bounded text-only results."""

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before_tool)
        registry.add_callback(AfterToolCallEvent, self.after_tool)

    def before_tool(self, event: BeforeToolCallEvent) -> None:
        if event.tool_use["name"] not in DOCS_TOOL_NAMES:
            return
        if event.selected_tool is not None:
            # MCPClient has no option for this; MCPAgentTool reads it on each call.
            event.selected_tool.timeout = TOOL_TIMEOUT

    def after_tool(self, event: AfterToolCallEvent) -> None:
        if event.tool_use["name"] not in DOCS_TOOL_NAMES:
            return
        result = event.result
        body = "\n".join(
            block["text"]
            for block in result.get("content", [])
            if isinstance(block.get("text"), str)
        )
        text = body[:MAX_RESULT_CHARS]
        if len(body) > MAX_RESULT_CHARS:
            text += f"\n{TRUNCATED_NOTICE}"
        # One block: the AG-UI adapter forwards and replays only the last text block.
        result["content"] = [{"text": text}]
