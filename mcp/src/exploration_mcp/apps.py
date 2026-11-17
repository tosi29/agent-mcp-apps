"""One MCP App; HTML is built from ui/ and served as a standard MCP resource."""

import asyncio
import json
from pathlib import Path
from typing import Literal

from mcp.server.apps import Apps, ResourceCsp
from mcp.types import CallToolResult, TextContent

from exploration_mcp.data import DataExplorer, Filters
from exploration_mcp.results import ResultStore, model_summary

DASHBOARD_URI = "ui://exploration/transaction-dashboard-v1.html"


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
        title="取引データのダッシュボード",
        csp=ResourceCsp(connect_domains=[], resource_domains=[], frame_domains=[]),
        prefers_border=True,
    )

    @apps.tool(resource_uri=DASHBOARD_URI, visibility=["model", "app"])
    async def show_transaction_dashboard(
        group_by: Literal["municipality", "year", "quarter"] = "year",
        municipality: str = "",
        year: int | None = None,
    ) -> CallToolResult:
        """合成取引を集計し、MCP Appsの棒グラフと表で表示する。グラフやダッシュボードの依頼に使う。

        group_byは地域・年・四半期。municipalityが空なら全地域、year未指定なら全年。
        quarterは対象期間の同じ四半期を合算する。年別比較にはyearを使う。
        UI非対応クライアントでも、件数と最大3行の要約を返す。
        """
        result = await asyncio.to_thread(explorer.aggregate, group_by, Filters(municipality, year))
        preview = store.put({"source": "mcp", "group_by": group_by, **result})
        summary = model_summary(result, preview["result_id"])
        return CallToolResult(
            content=[TextContent(text=json.dumps(summary, ensure_ascii=False, allow_nan=False))],
            structured_content=summary,
            _meta={"preview": preview},
        )

    return apps
