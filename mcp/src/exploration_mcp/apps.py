"""One MCP App; HTML is built from ui/ and served as a standard MCP resource."""

import asyncio
import json
from pathlib import Path
from typing import Literal

from mcp.server.apps import Apps, ResourceCsp
from mcp.types import CallToolResult, TextContent

from exploration_mcp.data import DataExplorer, Filters
from exploration_mcp.results import ResultStore, model_summary

DASHBOARD_URI = "ui://exploration/office-market-dashboard-v1.html"


def dashboard_app(explorer: DataExplorer, store: ResultStore) -> Apps:
    apps = Apps()
    html_path = Path(__file__).parent / "ui/dashboard.html"
    if not html_path.is_file():
        raise ValueError(
            "MCP AppのHTMLがありません。mcp/uiでnpm ciとnpm run buildを実行してください"
        )
    apps.add_html_resource(
        DASHBOARD_URI,
        html_path.read_text(encoding="utf-8"),
        title="オフィス市況のダッシュボード",
        csp=ResourceCsp(connect_domains=[], resource_domains=[], frame_domains=[]),
        prefers_border=True,
    )

    @apps.tool(resource_uri=DASHBOARD_URI, visibility=["model", "app"])
    async def show_office_market_dashboard(
        group_by: Literal["area", "year", "month"] = "year",
        area: str = "",
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> CallToolResult:
        """空室率・賃料を集計し、MCP Appsの棒グラフと表で表示する。グラフ・ダッシュボード用。

        group_byは地区・年・月。areaが空なら全地区を混ぜて集計し、year_from・year_toは両端を含む。
        画面に出るのは先頭20区分まで。年別で20年を超える場合はyear_fromで期間を絞る。
        UI非対応クライアントでも、件数と最大3行の要約を返す。
        """
        result = await asyncio.to_thread(
            explorer.aggregate, group_by, Filters(area, year_from, year_to)
        )
        preview = store.put({"source": "mcp", "group_by": group_by, **result})
        summary = model_summary(result, preview["result_id"])
        return CallToolResult(
            content=[TextContent(text=json.dumps(summary, ensure_ascii=False, allow_nan=False))],
            structured_content=summary,
            _meta={"preview": preview},
        )

    return apps
