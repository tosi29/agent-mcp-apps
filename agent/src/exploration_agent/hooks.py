"""Tool status and UI data for the client, kept out of the model conversation."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry

from exploration_agent.mcp_clients.apps import APP_TOOL
from exploration_agent.mcp_clients.exploration import MCP_TOOL_NAMES, RESULT_TOOLS

logger = logging.getLogger(__name__)


class ToolResultHook(HookProvider):
    """Keep results per tool call for the client, and strip UI data from the model's copy."""

    def __init__(self, app_loader: Callable[[], Awaitable[dict]]):
        self.app_loader = app_loader
        self.previews: dict[str, dict] = {}
        self.statuses: dict[str, dict] = {}
        self._app_task: asyncio.Task[dict] | None = None

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before_tool)
        registry.add_callback(AfterToolCallEvent, self.after_tool)

    def before_tool(self, event: BeforeToolCallEvent) -> None:
        logger.info("tool_start %s", event.tool_use)

    async def after_tool(self, event: AfterToolCallEvent) -> None:
        name = event.tool_use["name"]
        tool_call_id = event.tool_use["toolUseId"]
        status = event.result.get("status", "error")
        # Raw exceptions may contain paths, provider responses, or secrets. Do not forward them.
        self.statuses[tool_call_id] = {"tool_call_id": tool_call_id, "name": name, "status": status}
        if name in MCP_TOOL_NAMES:
            structured = event.result.pop("structuredContent", None)
            metadata = event.result.pop("metadata", None) or {}
            if name in RESULT_TOOLS and status == "success":
                preview = await self._preview(event, structured, metadata)
                self.previews[tool_call_id] = {**preview, "tool_call_id": tool_call_id}
        logger.info("tool_end %s", event.result)

    async def _preview(self, event: AfterToolCallEvent, structured: Any, metadata: dict) -> dict:
        if event.tool_use["name"] != APP_TOOL:
            return structured
        preview = metadata["preview"]
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
        return {**preview, "app": app}
