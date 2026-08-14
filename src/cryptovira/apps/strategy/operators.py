"""Condition operators. No Django imports — pure functions over an indicator's output array.

Explicit level vs. edge split, replacing the old system's undocumented behavior where `"bigger"`/
`"smaller"` silently also checked the *previous* candle, so a level-looking config key actually
behaved as edge-triggered with nothing in the code or the config schema saying so. Here, an author
who wants "RSI is above 70 right now" writes `gt`; an author who wants "RSI just crossed above
70" writes `crosses_above`. The two are genuinely different questions with different answers on
every candle after the crossing, and picking the wrong one silently re-fires a signal on every
candle a level check would have — worth two named operators, not one operator with a hidden mode.

Each operator takes the *full* indicator series, not just the latest value, because the edge
operators need to see the previous point too. `nan <= value` and `nan >= value` are both `False`
in Python/numpy, so the edge operators naturally return `False` (not an error) when the prior
point is still inside the indicator's warm-up window.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np

type OperatorFn = Callable[[np.ndarray, float], bool]


def _gt(series: np.ndarray, value: float) -> bool:
    return bool(series[-1] > value)


def _lt(series: np.ndarray, value: float) -> bool:
    return bool(series[-1] < value)


def _eq(series: np.ndarray, value: float) -> bool:
    return math.isclose(series[-1], value)


def _crosses_above(series: np.ndarray, value: float) -> bool:
    return bool(series[-2] <= value < series[-1])


def _crosses_below(series: np.ndarray, value: float) -> bool:
    return bool(series[-2] >= value > series[-1])


OPERATORS: dict[str, OperatorFn] = {
    "gt": _gt,
    "lt": _lt,
    "eq": _eq,
    "crosses_above": _crosses_above,
    "crosses_below": _crosses_below,
}
