"""Tool status and UI data for the client, kept out of the model conversation."""

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry

from exploration_agent.mcp_clients.apps import APP_TOOL
from exploration_agent.mcp_clients.exploration import RESOURCE_LINK_KEY, RESULT_TOOLS
from exploration_agent.mcp_clients.resources import RESULT_CSV_MIME, RESULT_CSV_URI

logger = logging.getLogger(__name__)


class ToolResultHook(HookProvider):
    """Keep results per tool call for the client, and strip UI data from the model's copy."""

    def __init__(self, app_loader: Callable[[], Coroutine[Any, Any, dict]]):
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
        status = event.result["status"]
        # Raw exceptions may contain paths, provider responses, or secrets. Do not forward them.
        self.statuses[tool_call_id] = {"tool_call_id": tool_call_id, "name": name, "status": status}
        structured = event.result.pop("structuredContent", None)
        metadata = event.result.pop("metadata", None)
        links = _pop_resource_links(event.result)
        if name in RESULT_TOOLS and status == "success":
            preview = await self._preview(event, structured, metadata)
            self.previews[tool_call_id] = {
                **preview,
                "tool_call_id": tool_call_id,
                "downloads": _csv_downloads(links),
            }
        logger.info("tool_end %s", event.result)

    async def _preview(self, event: AfterToolCallEvent, structured: Any, metadata: Any) -> dict:
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
                    {"type": "text", "text": text}
                    for block in event.result.get("content", [])
                    if isinstance(text := block.get("text"), str)
                ],
                "structuredContent": structured,
                "_meta": {"preview": preview},
            },
        }
        return {**preview, "app": app}


def _pop_resource_links(result: Any) -> list[dict]:
    """Links are references for the client. The model keeps the text summary only."""
    content = result.get("content", [])
    links = [
        block["json"][RESOURCE_LINK_KEY]
        for block in content
        if isinstance(block.get("json"), dict) and RESOURCE_LINK_KEY in block["json"]
    ]
    result["content"] = [
        block
        for block in content
        if not (isinstance(block.get("json"), dict) and RESOURCE_LINK_KEY in block["json"])
    ]
    return links


def _csv_downloads(links: list[dict]) -> list[dict]:
    # Forward only the result CSV template; the UI must not follow arbitrary MCP URIs.
    return [
        {"uri": link["uri"], "title": str(link.get("title") or "CSV"), "mimeType": RESULT_CSV_MIME}
        for link in links
        if isinstance(link.get("uri"), str)
        and RESULT_CSV_URI.fullmatch(link["uri"])
        and link.get("mimeType") == RESULT_CSV_MIME
    ]
