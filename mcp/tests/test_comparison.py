import math

import pytest

from exploration_mcp.comparison import compare_values


@pytest.mark.parametrize(
    ("baseline", "current", "difference", "percent"),
    [(100, 120, 20, 20), (100, 80, -20, -20), (0, 120, 120, None), (10, 10, 0, 0)],
)
def test_comparison(baseline, current, difference, percent):
    result = compare_values(baseline, current)
    assert result["difference"] == difference
    assert result["percent_change"] == percent


@pytest.mark.parametrize("values", [(math.nan, 1), (1, math.inf), (-1e308, 1e308)])
def test_nonfinite_input_and_overflow_are_errors(values):
    with pytest.raises(ValueError):
        compare_values(*values)
