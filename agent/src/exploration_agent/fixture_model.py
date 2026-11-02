"""Explicit API-free transport check. This is not a natural-language model."""

import asyncio
import json
from typing import Any
from uuid import uuid4

from strands.models.model import Model


class FixtureModel(Model):
    """Inspect and aggregate Shinjuku; optionally compare values through MCP, then answer."""

    def __init__(self, *, compare: bool = False):
        self.calls = 0
        self.compare = compare

    def get_config(self) -> dict:
        return {"model_id": "fixture-no-api"}

    def update_config(self, **model_config: Any) -> None:
        pass

    async def structured_output(self, *args: Any, **kwargs: Any):
        raise NotImplementedError("FixtureModel does not support structured output")
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.calls += 1
        yield {"messageStart": {"role": "assistant"}}
        if self.calls == 1:
            yield {"contentBlockStart": {"start": {}}}
            for text in [
                "これは推論表示の接続検証用サンプルです。実際のモデルの推論ではありません。",
                "データ項目を確認してから、新宿区の年別集計を実行します。",
            ]:
                await asyncio.sleep(0.1)
                yield {"contentBlockDelta": {"delta": {"reasoningContent": {"text": text}}}}
            yield {"contentBlockStop": {}}
        if self.calls <= (3 if self.compare else 2):
            name = "describe_dataset" if self.calls == 1 else "aggregate_transactions"
            args = {} if self.calls == 1 else {"municipality": "新宿区", "group_by": "year"}
            if self.calls == 3:
                name = "compare_values"
                args = {"baseline": 42_500_000, "current": 42_500_000}
            yield {
                "contentBlockStart": {
                    "start": {
                        "toolUse": {
                            "name": name,
                            "toolUseId": "fixture-" + uuid4().hex,
                        }
                    }
                }
            }
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"contentBlockStart": {"start": {}}}
            for text in [
                "これは接続検証用の固定シナリオです。合成データの新宿区を年別に集計しました。\n\n",
                "| 年 | 件数 | 平均取引総額 |\n|---|---:|---:|\n",
                "| 2023 | 40 | 42,500,000円 |\n",
                "| 2024 | 40 | 42,500,000円 |\n",
                "| 2025 | 40 | 42,500,000円 |\n\n",
                "実際の不動産取引や市場価格ではありません。",
            ]:
                await asyncio.sleep(0.1)
                yield {"contentBlockDelta": {"delta": {"text": text}}}
            if self.compare:
                yield {
                    "contentBlockDelta": {
                        "delta": {
                            "text": (
                                "\nMCPツールで平均取引総額を比較しました。"
                                "差分は0円、増減率は0%です。"
                            )
                        }
                    }
                }
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}
