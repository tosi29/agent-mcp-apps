"""Request-scoped MCP connection and UI projection of the small comparison result."""

import asyncio
import math
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from urllib.parse import urlparse

from strands.hooks import AfterToolCallEvent, HookProvider, HookRegistry
from strands.tools.mcp import MCPAgentTool, MCPClient

from exploration_agent.agentcore_mcp import runtime_client

MCP_TOOL_NAMES = (
    "describe_dataset",
    "search_transactions",
    "aggregate_transactions",
    "compare_values",
)
RESULT_TOOLS = {"search_transactions", "aggregate_transactions", "compare_values"}


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
        client = runtime_client(runtime_arn, allowed_tools=list(MCP_TOOL_NAMES))
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
        client = MCPClient(
            url=url, startup_timeout=5, tool_filters={"allowed": list(MCP_TOOL_NAMES)}
        )
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
        if {tool.tool_name for tool in tools} != set(MCP_TOOL_NAMES):
            raise ValueError("MCPサーバーに必要な探索・比較ツールが揃っていません")
        for tool in tools:
            tool.timeout = timedelta(seconds=10)
        yield list(tools)
    finally:
        await asyncio.to_thread(client.stop, None, None, None)


class MCPPreviewHook(HookProvider):
    """Forward bounded previews to the UI, then remove them from agent conversation state."""

    def __init__(self, emit: Callable[..., None]):
        self.emit = emit

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(AfterToolCallEvent, self.after_tool)

    def after_tool(self, event: AfterToolCallEvent) -> None:
        name = event.tool_use["name"]
        if name not in MCP_TOOL_NAMES:
            return
        payload = event.result.pop("structuredContent", None)
        event.result.pop("metadata", None)
        if name not in RESULT_TOOLS or event.result.get("status") != "success":
            return
        if not isinstance(payload, dict):
            raise ValueError("MCPの表示用データがありません")
        result_id = payload.get("result_id")
        rows = payload.get("preview_rows")
        counts = [payload.get(key) for key in ("total_count", "returned_count")]
        if (
            not isinstance(result_id, str)
            or not re.fullmatch(r"[0-9a-f]{32}", result_id)
            or not isinstance(rows, list)
            or len(rows) > 20
            or any(type(value) is not int or value < 0 for value in counts)
            or not len(rows) <= counts[1] <= min(counts[0], 200)
            or payload.get("count_unit") not in {"transactions", "groups", "rows"}
            or payload.get("source") != "mcp"
            or any(type(payload.get(key)) is not bool for key in ("truncated", "preview_truncated"))
        ):
            raise ValueError("MCPの表示用データが不正です")
        for row in rows:
            if not isinstance(row, dict) or len(row) > 12:
                raise ValueError("MCPの表示行が不正です")
            for key, value in row.items():
                if not isinstance(key, str) or len(key) > 80:
                    raise ValueError("MCPの表示列が不正です")
                if value is None:
                    continue
                if isinstance(value, str) and len(value) <= 2000:
                    continue
                if type(value) in {int, float} and math.isfinite(value):
                    continue
                raise ValueError("MCPの表示値が不正です")
        preview = {
            key: payload[key]
            for key in (
                "result_id",
                "source",
                "total_count",
                "count_unit",
                "returned_count",
                "truncated",
                "preview_truncated",
                "preview_rows",
            )
        }
        if isinstance(payload.get("dataset"), str) and len(payload["dataset"]) <= 128:
            preview["dataset"] = payload["dataset"]
        if type(payload.get("synthetic")) is bool:
            preview["synthetic"] = payload["synthetic"]
        self.emit("data_result", tool_call_id=event.tool_use["toolUseId"], **preview)
