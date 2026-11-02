"""Small numeric operation independent from MCP and the agent."""

import math
from typing import TypedDict


class Comparison(TypedDict):
    baseline: float
    current: float
    difference: float
    percent_change: float | None


def compare_values(baseline: float, current: float) -> Comparison:
    """2つの値の差分と増減率を計算する。同じ単位の値を渡す。

    Args:
        baseline: 比較の基準値。
        current: 比較する現在の値。

    増減率は (current - baseline) / baseline * 100（%）。小数点以下6桁に丸める。
    基準値が0の場合は増減率をnullにし、差分だけを返す。
    """
    if not all(math.isfinite(value) for value in (baseline, current)):
        raise ValueError("有限の数値を指定してください")
    difference = current - baseline
    percent_change = difference / baseline * 100 if baseline != 0 else None
    if not math.isfinite(difference) or (
        percent_change is not None and not math.isfinite(percent_change)
    ):
        raise ValueError("計算結果が数値の範囲を超えました")
    return {
        "baseline": baseline,
        "current": current,
        "difference": difference,
        "percent_change": round(percent_change, 6) if percent_change is not None else None,
    }
