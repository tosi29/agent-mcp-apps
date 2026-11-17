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
        """オフィス市況データの項目・単位・地区候補・期間・合成データかを確認する。探索の最初に呼ぶ。"""
        return await asyncio.to_thread(explorer.describe)

    @server.tool()
    async def search_office_market(
        area: str = "",
        year_from: int | None = None,
        year_to: int | None = None,
        month: int | None = None,
        min_vacancy_rate_pct: float | None = None,
        max_vacancy_rate_pct: float | None = None,
        limit: int = 100,
    ) -> CallToolResult:
        """地区・月ごとの平均空室率（％）と平均賃料（円/坪）を検索する。

        areaは地区名の完全一致で、空なら全地区。year_from・year_toは両端を含む。
        monthは1〜12。空室率の範囲は以上／以下。未指定の条件では絞り込まない。
        結果は年・月の昇順。limitは1〜200。モデルには最大3行、画面には最大20行を返す。
        """
        result = await asyncio.to_thread(
            explorer.search,
            Filters(area, year_from, year_to, month, min_vacancy_rate_pct, max_vacancy_rate_pct),
            limit,
        )
        return publish(result)

    @server.tool()
    async def aggregate_office_market(
        group_by: Literal["area", "year", "month"],
        area: str = "",
        year_from: int | None = None,
        year_to: int | None = None,
        month: int | None = None,
        min_vacancy_rate_pct: float | None = None,
        max_vacancy_rate_pct: float | None = None,
    ) -> CallToolResult:
        """地区・年・月で集計し、月数と空室率・賃料の単純平均・最小・最大を返す。

        平均は月次値の単純平均で、面積加重ではない。monthは対象期間の同じ月を合算する。
        areaが空なら全地区を混ぜて集計するため、地区別の値が必要ならareaを指定する。
        """
        result = await asyncio.to_thread(
            explorer.aggregate,
            group_by,
            Filters(area, year_from, year_to, month, min_vacancy_rate_pct, max_vacancy_rate_pct),
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
