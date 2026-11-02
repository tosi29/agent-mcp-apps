"""Local CLI. Default commands never contact an LLM."""

import argparse
import asyncio
import json
import logging
import re
from pathlib import Path

from exploration_agent.data import DataExplorer, Filters, prepare_sample
from exploration_agent.results import ResultStore
from exploration_agent.runtime import SakuraSettings, stream_question


def output(value: dict, sse: bool = False) -> None:
    body = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if sse:
        print(
            f"id: {value['request_id']}:{value['seq']}\nevent: {value['type']}\ndata: {body}\n",
            flush=True,
        )
    else:
        print(body, flush=True)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Strands + さくらAI Engine + DuckDB ローカルPoC")
    root.add_argument("--data", type=Path, default=Path("data/synthetic.parquet"))
    root.add_argument("--results", type=Path, default=Path("results"))
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("prepare-sample", help="架空データ360行をParquetに生成（API不要）")
    commands.add_parser("inspect", help="スキーマを確認（API不要）")
    commands.add_parser("query-demo", help="年別集計を直接実行（API不要）")
    result = commands.add_parser("result", help="保存した上限付き結果を取得（API不要）")
    result.add_argument("request_id")
    result.add_argument("result_id")
    ask = commands.add_parser("ask", help="さくらへ質問。APIキーとモデルIDの設定が必要")
    ask.add_argument("prompt")
    ask.add_argument("--sse", action="store_true", help="HTTPではなく標準出力にSSEフレームを出す")
    ask.add_argument("--no-stream", action="store_true", help="非streamモードで互換性を切り分ける")
    ask.add_argument("--mcp-url", help="ローカルMCPサーバーのURL")
    return root


async def ask(args: argparse.Namespace) -> int:
    model = SakuraSettings.from_env(stream=not args.no_stream).build_model()
    status = 1
    async for event in stream_question(
        args.prompt, model, args.data, args.results, mcp_url=args.mcp_url
    ):
        output(event, args.sse)
        if event["type"] == "done":
            status = 0 if event["status"] == "success" else 1
    return status


def main() -> None:
    args = parser().parse_args()
    # Provider/library debug logging can include entire requests or responses.
    logging.disable(logging.CRITICAL)
    try:
        if args.command == "prepare-sample":
            prepare_sample(args.data)
            output({"synthetic": True, "row_count": 360, "path": str(args.data)})
        elif args.command == "inspect":
            output(DataExplorer(args.data).describe())
        elif args.command == "query-demo":
            output(DataExplorer(args.data).aggregate("year", Filters(municipality="新宿区")))
        elif args.command == "result":
            # Validate both identifiers before resolving any paths.
            if not re.fullmatch(r"[0-9a-f]{32}", args.request_id):
                raise ValueError("invalid request_id")
            output(ResultStore(args.results / args.request_id).get(args.result_id))
        else:
            raise SystemExit(asyncio.run(ask(args)))
    except (ValueError, FileExistsError) as error:
        output({"type": "error", "message": str(error)})
        raise SystemExit(1) from None
    except Exception:
        output(
            {
                "type": "error",
                "message": "ローカル処理に失敗しました。ファイル・設定を確認してください。",
            }
        )
        raise SystemExit(1) from None
