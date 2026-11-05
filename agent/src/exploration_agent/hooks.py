"""Request-scoped counters and tool events."""

import logging
from collections.abc import Callable
from typing import Any

from strands.hooks import (
    AfterToolCallEvent,
    BeforeModelCallEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
)

logger = logging.getLogger(__name__)


class RequestHooks(HookProvider):
    def __init__(self, emit: Callable[..., None]):
        self.emit = emit
        self.model_calls = 0
        self.tool_calls = 0
        self.tool_errors = 0

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeModelCallEvent, self.before_model)
        registry.add_callback(BeforeToolCallEvent, self.before_tool)
        registry.add_callback(AfterToolCallEvent, self.after_tool)

    def before_model(self, event: BeforeModelCallEvent) -> None:
        self.model_calls += 1

    def before_tool(self, event: BeforeToolCallEvent) -> None:
        logger.info("tool_start %s", event.tool_use)
        self.tool_calls += 1

    def after_tool(self, event: AfterToolCallEvent) -> None:
        logger.info("tool_end %s", event.result)
        status = event.result.get("status", "error")
        self.tool_errors += status != "success"
        # Raw exceptions may contain paths, provider responses, or secrets. Do not forward them.
        self.emit(
            "tool_end",
            tool_call_id=event.tool_use["toolUseId"],
            name=event.tool_use["name"],
            status=status,
        )
