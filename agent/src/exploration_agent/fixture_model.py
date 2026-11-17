"""Explicit API-free transport check. This is not a natural-language model."""

import asyncio
import json
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from strands.models.model import Model
from strands.types.content import ContentBlockStartToolUse
from strands.types.streaming import StreamEvent

REASONING_NOTICE = "これは推論表示の接続検証用サンプルです。実際のモデルの推論ではありません。"
AGGREGATE_ARGS = {"area": "千代田区", "group_by": "year", "year_from": 2023, "year_to": 2025}
COMPARE_ARGS = {"baseline": 100, "current": 120}
MCP_REASONING = (REASONING_NOTICE, "MCPの項目確認・年別集計を実行します。")
# The data file can be synthetic or real, so the canned text never states data values.
MCP_ANSWER = (
    "これは接続検証用の固定シナリオです。千代田区の2023〜2025年を年別に集計しました。\n\n",
    "集計値は結果パネルを参照してください。",
    "この文章は固定応答で、モデルが集計結果を読んで書いたものではありません。\n",
    "比較ツールは固定値100と120で接続を確認しました（差分20、増減率20%）。",
)


@dataclass(frozen=True)
class Scenario:
    reasoning: tuple[str, ...]
    tool_calls: tuple[tuple[str, dict], ...]
    answer: tuple[str, ...]


def mcp_scenario(result_tool: str) -> Scenario:
    return Scenario(
        MCP_REASONING,
        (
            ("describe_dataset", {}),
            (result_tool, AGGREGATE_ARGS),
            ("compare_values", COMPARE_ARGS),
        ),
        MCP_ANSWER,
    )


ECHO = Scenario(
    (REASONING_NOTICE, "Pythonのecho_textを実行します。"),
    (("echo_text", {"text": "接続テスト"}),),
    ("通常のPythonツールecho_textを実行しました。", "返り値は「接続テスト」です。"),
)
AGGREGATE = mcp_scenario("aggregate_office_market")
DASHBOARD = mcp_scenario("show_office_market_dashboard")


def choose_scenario(messages, tool_specs) -> Scenario:
    if not any(spec["name"] == "describe_dataset" for spec in tool_specs or []):
        return ECHO
    # Two explicit canned scenarios; this does not understand natural language.
    text = json.dumps(messages[-1], ensure_ascii=False)
    return DASHBOARD if "ダッシュボード" in text or "グラフ" in text else AGGREGATE


class FixtureModel(Model):
    """Replay a canned scenario chosen from the first request of a run."""

    def __init__(self) -> None:
        self.calls = 0
        self.scenario: Scenario | None = None

    def get_config(self) -> dict:
        return {"model_id": "fixture-no-api"}

    def update_config(self, **model_config: Any) -> None:
        pass

    async def structured_output(self, *args: Any, **kwargs: Any):
        raise NotImplementedError("FixtureModel does not support structured output")
        yield  # pragma: no cover

    async def stream(
        self, messages, tool_specs=None, system_prompt=None, **kwargs
    ) -> AsyncGenerator[StreamEvent, None]:
        if self.scenario is None:
            self.scenario = choose_scenario(messages, tool_specs)
        call = self.calls
        self.calls += 1
        yield {"messageStart": {"role": "assistant"}}
        if call == 0:
            yield {"contentBlockStart": {"start": {}}}
            for text in self.scenario.reasoning:
                await asyncio.sleep(0.1)
                yield {"contentBlockDelta": {"delta": {"reasoningContent": {"text": text}}}}
            yield {"contentBlockStop": {}}
        if call < len(self.scenario.tool_calls):
            name, args = self.scenario.tool_calls[call]
            tool_use: ContentBlockStartToolUse = {
                "name": name,
                "toolUseId": "fixture-" + uuid4().hex,
            }
            yield {"contentBlockStart": {"start": {"toolUse": tool_use}}}
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}}}
            for text in self.scenario.answer:
                await asyncio.sleep(0.1)
                yield {"contentBlockDelta": {"delta": {"text": text}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
