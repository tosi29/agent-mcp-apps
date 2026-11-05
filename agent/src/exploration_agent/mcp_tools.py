"""The exploration MCP client, and the split of its results between the model and the UI."""

import asyncio
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse

from strands.hooks import AfterToolCallEvent, HookProvider, HookRegistry
from strands.tools.mcp import MCPClient

from exploration_agent.agentcore_mcp import runtime_client
from exploration_agent.mcp_apps import APP_TOOL

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
        return [runtime_client(runtime_arn, allowed_tools=list(MCP_TOOL_NAMES))]
    if url is None:
        return []
    if urlparse(url).hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("MCP URLにはループバックのhttp://127.0.0.1:8001/mcp等を指定してください")
    return [MCPClient(url=url, startup_timeout=5, tool_filters={"allowed": list(MCP_TOOL_NAMES)})]


class MCPPreviewHook(HookProvider):
    """Forward UI data as an event, and remove it before it enters the model conversation."""

    def __init__(self, emit: Callable[..., None], app_loader: Callable[[], Awaitable[dict]]):
        self.emit = emit
        self.app_loader = app_loader
        self._app_task: asyncio.Task[dict] | None = None

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(AfterToolCallEvent, self.after_tool)

    async def after_tool(self, event: AfterToolCallEvent) -> None:
        name = event.tool_use["name"]
        if name not in MCP_TOOL_NAMES:
            return
        structured = event.result.pop("structuredContent", None)
        metadata = event.result.pop("metadata", None) or {}
        if name not in RESULT_TOOLS or event.result.get("status") != "success":
            return
        preview = metadata["preview"] if name == APP_TOOL else structured
        if name == APP_TOOL:
            # Parallel calls in one run share a single HTML fetch.
            self._app_task = self._app_task or asyncio.create_task(self.app_loader())
            app = {
                **await self._app_task,
                "toolInput": event.tool_use.get("input", {}),
                "toolResult": {
                    "content": [
                        {"type": "text", "text": block["text"]}
                        for block in event.result.get("content", [])
                        if isinstance(block.get("text"), str)
                    ],
                    "structuredContent": structured,
                    "_meta": {"preview": preview},
                },
            }
            preview = {**preview, "app": app}
        self.emit("data_result", tool_call_id=event.tool_use["toolUseId"], **preview)
