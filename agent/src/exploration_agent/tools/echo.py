"""A single ordinary Strands tool, independent of MCP and external services."""

from strands import tool


@tool
def echo_text(text: str) -> dict[str, str]:
    """接続検証用。入力をそのまま返す。データ検索や計算は行わない。"""
    return {"text": text}
