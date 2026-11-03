"""CLI for explicit Sakura model calls; offline data utilities belong to mcp/."""

import argparse
import asyncio
import json
import logging

from exploration_agent.observability import configure_observability
from exploration_agent.runtime import SakuraSettings, stream_question

logger = logging.getLogger(__name__)


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
    commands = root.add_subparsers(dest="command", required=True)
    ask = commands.add_parser("ask", help="さくらへ質問。APIキーとモデルIDの設定が必要")
    ask.add_argument("prompt")
    ask.add_argument("--sse", action="store_true", help="HTTPではなく標準出力にSSEフレームを出す")
    ask.add_argument("--no-stream", action="store_true", help="非streamモードで互換性を切り分ける")
    mcp = ask.add_mutually_exclusive_group()
    mcp.add_argument("--mcp-url", help="ローカルMCPサーバーのURL")
    mcp.add_argument("--mcp-runtime-arn", help="IAM認証で接続する東京のMCP Runtime ARN")
    return root


async def ask(args: argparse.Namespace) -> int:
    model = SakuraSettings.from_env(stream=not args.no_stream).build_model()
    status = 1
    async for event in stream_question(
        args.prompt,
        model,
        mcp_url=args.mcp_url,
        mcp_runtime_arn=args.mcp_runtime_arn,
    ):
        output(event, args.sse)
        if event["type"] == "done":
            status = 0 if event["status"] == "success" else 1
    return status


def main() -> None:
    args = parser().parse_args()
    configure_observability()
    try:
        raise SystemExit(asyncio.run(ask(args)))
    except ValueError as error:
        logger.exception("Agent CLI input failed")
        output({"type": "error", "message": str(error)})
        raise SystemExit(1) from None
    except Exception:
        logger.exception("Agent CLI failed")
        output(
            {
                "type": "error",
                "message": "ローカル処理に失敗しました。ファイル・設定を確認してください。",
            }
        )
        raise SystemExit(1) from None
