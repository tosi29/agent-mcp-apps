"""Request-scoped MCP connection and UI projection of the small comparison result."""

import asyncio
import math
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from urllib.parse import urlparse

from strands.hooks import AfterToolCallEvent, HookProvider, HookRegistry
from strands.tools.mcp import MCPAgentTool, MCPClient

from exploration_agent.agentcore_mcp import runtime_client
from exploration_agent.results import ResultStore


@asynccontextmanager
async def connect_mcp(
    url: str | None, *, runtime_arn: str | None = None
) -> AsyncIterator[list[MCPAgentTool]]:
    if url is not None and runtime_arn is not None:
        raise ValueError("ローカルMCP URLとMCP Runtime ARNは同時に指定できません")
    if url is None and runtime_arn is None:
        yield []
        return
    if runtime_arn is not None:
        client = runtime_client(runtime_arn)
    else:
        parsed = urlparse(url)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path != "/mcp"
        ):
            raise ValueError(
                "MCP URLにはループバックのhttp://127.0.0.1:8001/mcp等を指定してください"
            )
        client = MCPClient(url=url, startup_timeout=5, tool_filters={"allowed": ["compare_values"]})
    opening = asyncio.create_task(asyncio.to_thread(client.start))
    try:
        await asyncio.shield(opening)
    except asyncio.CancelledError:
        # A cancelled await cannot stop the worker thread. Close any connection it finishes opening.
        try:
            await opening
        except Exception:
            pass  # start() cleans up its own initialization failure.
        else:
            await asyncio.to_thread(client.stop, None, None, None)
        raise
    try:
        tools = await asyncio.wait_for(asyncio.to_thread(client.list_tools_sync), timeout=10)
        if [tool.tool_name for tool in tools] != ["compare_values"]:
            raise ValueError("MCPサーバーにcompare_valuesツールがありません")
        for tool in tools:
            tool.timeout = timedelta(seconds=10)
        yield list(tools)
    finally:
        await asyncio.to_thread(client.stop, None, None, None)


class ComparisonPreviewHook(HookProvider):
    """Project exactly four numeric fields into the existing UI result event."""

    def __init__(self, store: ResultStore, emit: Callable[..., None]):
        self.store = store
        self.emit = emit

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(AfterToolCallEvent, self.after_tool)

    def after_tool(self, event: AfterToolCallEvent) -> None:
        if event.tool_use["name"] != "compare_values" or event.result.get("status") != "success":
            return
        payload = event.result.get("structuredContent")
        fields = ("baseline", "current", "difference", "percent_change")
        if not isinstance(payload, dict) or any(field not in payload for field in fields):
            raise ValueError("MCPの比較結果が不正です")
        row = {field: payload[field] for field in fields}
        for field, value in row.items():
            if value is None and field == "percent_change":
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError("MCPの比較結果が不正です")
        preview = self.store.put(
            {
                "source": "mcp",
                "total_count": 1,
                "count_unit": "rows",
                "returned_count": 1,
                "truncated": False,
                "rows": [row],
            }
        )
        self.emit("data_result", tool_call_id=event.tool_use["toolUseId"], **preview)
