"""AG-UI events for one run. Request state and UI previews never become model state."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import aclosing
from typing import Any, cast

from ag_ui.core import CustomEvent, EventType, RunAgentInput, RunErrorEvent, RunStartedEvent
from ag_ui_strands import StrandsAgent, StrandsAgentConfig, ToolBehavior
from ag_ui_strands.config import ToolResultContext
from strands import Agent
from strands.models.model import Model

from exploration_agent.agent import exploration_agent
from exploration_agent.hooks import ToolResultHook
from exploration_agent.mcp_clients.apps import load_app_resources
from exploration_agent.mcp_clients.docs import DocsMCPHook
from exploration_agent.mcp_clients.target import MCPTarget
from exploration_agent.observability import log_callback

logger = logging.getLogger(__name__)


def _build_adapter(
    template: Agent, app_loader: Callable[[], Coroutine[Any, Any, dict]]
) -> StrandsAgent:
    """Use the maintained Strands adapter, with fresh per-request hooks and tools."""
    results = ToolResultHook(app_loader)

    async def custom_result(context: ToolResultContext):
        if preview := results.previews.pop(context.tool_use_id, None):
            yield CustomEvent(type=EventType.CUSTOM, name="data_result", value=preview)
        if status := results.statuses.pop(context.tool_use_id, None):
            yield CustomEvent(type=EventType.CUSTOM, name="tool_status", value=status)

    return StrandsAgent(
        agent=template,
        name="explorer",
        hooks=[results, DocsMCPHook()],
        config=StrandsAgentConfig(
            tool_behaviors={
                name: ToolBehavior(custom_result_handler=custom_result)
                for name in template.tool_registry.registry
            },
            # Explicitly preserve no-retry behavior when the adapter clones the template.
            thread_agent_kwargs=lambda _: {
                "retry_strategy": None,
                "callback_handler": log_callback,
            },
        ),
    )


def _app_loader(mcp: MCPTarget | None) -> Callable[[], Coroutine[Any, Any, dict]]:
    async def load() -> dict:
        # The dashboard tool exists only when the exploration MCP server is configured.
        if mcp is None:
            raise RuntimeError("Exploration MCP is not configured")
        return await load_app_resources(mcp)

    return load


def _trusted_input(run: RunAgentInput) -> RunAgentInput:
    # Do not expose frontend tools, arbitrary UI state, or injected A2UI configuration.
    # Reasoning is displayed by the client, but is not replayed as conversation input.
    return run.model_copy(
        update={
            "messages": [m for m in run.messages if m.role in {"user", "assistant", "tool"}],
            "tools": [],
            "context": [],
            "state": {},
            "forwarded_props": {},
            "resume": None,
        }
    )


async def agui_events(
    run: RunAgentInput,
    model_factory: Callable[[], Model],
    *,
    mcp: MCPTarget | None = None,
    timeout_seconds: float = 300,
) -> AsyncGenerator[Any, None]:
    """Stream one run. Every failure ends it once, with a fixed message for the client."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    started = finished = False
    try:
        # The cloud factory can fetch a SecureString. Keep that I/O off the event loop.
        model = await asyncio.to_thread(model_factory)
        async with exploration_agent(model, mcp) as template:
            adapter = _build_adapter(template, _app_loader(mcp))
            # run() is an async generator, although the adapter annotates an AsyncIterator.
            stream = cast(AsyncGenerator[Any, None], adapter.run(_trusted_input(run)))
            async with aclosing(stream):
                while True:
                    # The endpoint runs each step in its own task, so asyncio.timeout()
                    # cannot span steps.
                    try:
                        event = await asyncio.wait_for(anext(stream), deadline - loop.time())
                    except StopAsyncIteration:
                        break
                    if event.type == EventType.RUN_STARTED:
                        started = True
                    if event.type in {EventType.RAW, EventType.REASONING_ENCRYPTED_VALUE}:
                        continue
                    if event.type == EventType.RUN_ERROR:
                        logger.error(
                            "Agent run failed run_id=%s error=%s", run.run_id, event.message
                        )
                        break
                    if event.type == EventType.RUN_FINISHED:
                        finished = True
                    yield event
    except Exception:
        # The endpoint would send str(error) to the client. Log it and send a fixed message.
        logger.exception("Agent run failed run_id=%s", run.run_id)
    if finished:
        return
    if not started:
        yield RunStartedEvent(
            type=EventType.RUN_STARTED, thread_id=run.thread_id, run_id=run.run_id
        )
    yield RunErrorEvent(
        type=EventType.RUN_ERROR,
        code="AGENT_RUN_FAILED",
        message="実行に失敗しました。接続・設定・実行上限を確認してください。",
    )
