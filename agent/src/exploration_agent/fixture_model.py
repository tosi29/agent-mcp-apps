"""Explicit API-free transport check. This is not a natural-language model."""

import asyncio
import json
from typing import Any
from uuid import uuid4

from strands.models.model import Model


class FixtureModel(Model):
    """Demonstrate the ordinary echo tool, or use the MCP exploration tools."""

    def __init__(self, *, compare: bool = False):
        self.calls = 0
        self.compare = compare
        self.dashboard = False

    def get_config(self) -> dict:
        return {"model_id": "fixture-no-api"}

    def update_config(self, **model_config: Any) -> None:
        pass

    async def structured_output(self, *args: Any, **kwargs: Any):
        raise NotImplementedError("FixtureModel does not support structured output")
        yield  # pragma: no cover

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        self.calls += 1
        if self.calls == 1 and self.compare:
            # Two explicit canned scenarios; this does not understand natural language.
            text = json.dumps(messages[-1], ensure_ascii=False)
            self.dashboard = "ダッシュボード" in text or "グラフ" in text
        yield {"messageStart": {"role": "assistant"}}
        if self.calls == 1:
            yield {"contentBlockStart": {"start": {}}}
            for text in [
                "これは推論表示の接続検証用サンプルです。実際のモデルの推論ではありません。",
                "MCPの項目確認・年別集計を実行します。"
                if self.compare
                else "Pythonのecho_textを実行します。",
            ]:
                await asyncio.sleep(0.1)
                yield {"contentBlockDelta": {"delta": {"reasoningContent": {"text": text}}}}
            yield {"contentBlockStop": {}}
        tool_calls = 3 if self.compare else 1
        if self.calls <= tool_calls:
            name = "describe_dataset" if self.calls == 1 else "aggregate_transactions"
            args = {} if self.calls == 1 else {"municipality": "新宿区", "group_by": "year"}
            if self.calls == 2 and self.dashboard:
                name = "show_transaction_dashboard"
            if not self.compare:
                name, args = "echo_text", {"text": "接続テスト"}
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
            answer = (
                [
                    "これは接続検証用の固定シナリオです。合成データの新宿区を年別に集計しました。\n\n",
                    "| 年 | 件数 | 平均取引総額 |\n|---|---:|---:|\n",
                    "| 2023 | 40 | 42,500,000円 |\n",
                    "| 2024 | 40 | 42,500,000円 |\n",
                    "| 2025 | 40 | 42,500,000円 |\n\n",
                    "実際の不動産取引や市場価格ではありません。",
                ]
                if self.compare
                else ["通常のPythonツールecho_textを実行しました。", "返り値は「接続テスト」です。"]
            )
            for text in answer:
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
