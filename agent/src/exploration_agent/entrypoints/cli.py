"""CLI for explicit Sakura model calls; offline data utilities belong to mcp/."""

import argparse
import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from functools import partial
from typing import Any
from uuid import uuid4

from strands.models.model import Model

from exploration_agent.agent import exploration_agent
from exploration_agent.hooks import RequestHooks
from exploration_agent.mcp_clients.apps import load_app_resources
from exploration_agent.mcp_clients.docs import DocsMCPHook
from exploration_agent.mcp_clients.exploration import MCPPreviewHook
from exploration_agent.model import SakuraSettings
from exploration_agent.observability import configure_observability

logger = logging.getLogger(__name__)


async def stream_question(
    prompt: str,
    model: Model,
    *,
    mcp_url: str | None = None,
    mcp_runtime_arn: str | None = None,
    timeout_seconds: float = 300,
) -> AsyncIterator[dict[str, Any]]:
    """One question per fresh agent. No durable sessions or raw SDK events on the wire."""
    configure_observability()
    if not prompt.strip() or len(prompt) > 4000:
        raise ValueError("prompt must contain 1–4000 characters")
    request_id, started = uuid4().hex, time.monotonic()
    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    sequence = 0

    def emit(event_type: str, **payload: Any) -> None:
        nonlocal sequence
        sequence += 1
        queue.put_nowait(
            {
                "version": 1,
                "request_id": request_id,
                "seq": sequence,
                "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
                "type": event_type,
                **payload,
            }
        )

    hooks = RequestHooks(emit)

    async def produce() -> None:
        try:
            stop_reason = None
            async with asyncio.timeout(timeout_seconds):
                async with exploration_agent(
                    model,
                    mcp_url=mcp_url,
                    mcp_runtime_arn=mcp_runtime_arn,
                    hooks=[
                        hooks,
                        MCPPreviewHook(emit, partial(load_app_resources, mcp_url, mcp_runtime_arn)),
                        DocsMCPHook(),
                    ],
                ) as agent:
                    async for event in agent.stream_async(prompt):
                        if isinstance(event.get("data"), str):
                            emit("text_delta", text=event["data"])
                        if "result" in event:
                            stop_reason = event["result"].stop_reason
            if stop_reason != "end_turn":
                raise RuntimeError("model did not complete its turn")
            emit(
                "done",
                status="success",
                model_calls=hooks.model_calls,
                tool_calls=hooks.tool_calls,
                tool_errors=hooks.tool_errors,
            )
        except Exception as error:
            logger.exception("Agent run failed request_id=%s", request_id)
            emit(
                "error",
                code=type(error).__name__,
                message="実行に失敗しました。設定・制限・接続を確認してください。",
            )
            emit(
                "done",
                status="error",
                model_calls=hooks.model_calls,
                tool_calls=hooks.tool_calls,
                tool_errors=hooks.tool_errors,
            )
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(produce())
    try:
        while (event := await queue.get()) is not None:
            yield event
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


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
