"""A single ordinary Strands tool, independent of MCP and external services."""

from strands import tool


@tool
def echo_text(text: str) -> dict[str, str]:
    """接続検証用。200文字以内の入力をそのまま返す。データ検索や計算は行わない。"""
    if not isinstance(text, str) or len(text) > 200:
        raise ValueError("textは200文字以内の文字列にしてください")
    return {"text": text}
