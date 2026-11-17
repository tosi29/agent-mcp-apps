"""MCP wrappers: model summaries in content, bounded UI data in structuredContent."""

import asyncio
import json
from collections.abc import Mapping
from typing import Literal

from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent

from exploration_mcp.comparison import compare_values as compare
from exploration_mcp.data import DataExplorer, Filters
from exploration_mcp.results import ResultStore, model_summary


def register_tools(server: MCPServer, explorer: DataExplorer, store: ResultStore) -> None:
    def publish(result: dict, *, summary: Mapping[str, object] | None = None) -> CallToolResult:
        preview = store.put({"source": "mcp", **result})
        return CallToolResult(
            content=[
                TextContent(
                    text=json.dumps(
                        model_summary(result, preview["result_id"]) if summary is None else summary,
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                )
            ],
            structured_content=preview,
        )

    @server.tool()
    async def describe_dataset() -> dict:
        """合成データのスキーマ・単位・地域候補・件数を確認する。取引探索の最初に呼ぶ。"""
        return await asyncio.to_thread(explorer.describe)

    @server.tool()
    async def search_transactions(
        municipality: str = "",
        year: int | None = None,
        min_price_yen: int | None = None,
        max_price_yen: int | None = None,
        limit: int = 100,
    ) -> CallToolResult:
        """合成取引を地域の完全一致・年・価格範囲（円、以上／以下）で検索する。

        municipalityが空なら全地域。未指定の年・価格では絞り込まない。
        limitは1〜200。モデルには最大3行、画面には最大20行を返す。
        """
        result = await asyncio.to_thread(
            explorer.search, Filters(municipality, year, min_price_yen, max_price_yen), limit
        )
        return publish(result)

    @server.tool()
    async def aggregate_transactions(
        group_by: Literal["municipality", "year", "quarter"],
        municipality: str = "",
        year: int | None = None,
        min_price_yen: int | None = None,
        max_price_yen: int | None = None,
    ) -> CallToolResult:
        """合成取引を地域・年・四半期で集計し、件数と価格（円）の平均・最小・最大を返す。

        quarterは対象期間の同じ四半期を合算する。年別比較にはyearを指定する。
        municipalityが空なら全地域。未指定の年・価格では絞り込まない。
        """
        result = await asyncio.to_thread(
            explorer.aggregate, group_by, Filters(municipality, year, min_price_yen, max_price_yen)
        )
        return publish(result)

    @server.tool()
    async def compare_values(baseline: float, current: float) -> CallToolResult:
        """同じ単位の2数値の差分と増減率（%）を計算する。基準値が0なら増減率はnull。"""
        value = compare(baseline, current)
        result = publish(
            {
                "total_count": 1,
                "count_unit": "rows",
                "returned_count": 1,
                "truncated": False,
                "rows": [value],
            },
            summary=value,
        )
        # Keep the deployed comparison client usable while the two Runtimes update separately.
        result.structured_content.update(value)
        return result
