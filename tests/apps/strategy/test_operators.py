"""No `integration` marker: pure computation."""

from __future__ import annotations

import numpy as np

from cryptovira.apps.strategy.operators import OPERATORS


def test_gt_is_a_level_check_true_on_every_candle_above_threshold() -> None:
    series = np.array([10.0, 20.0, 30.0])

    assert OPERATORS["gt"](series[:2], 15.0) is True  # 20 > 15
    assert OPERATORS["gt"](series, 15.0) is True  # 30 > 15, still true


def test_lt_is_a_level_check() -> None:
    series = np.array([30.0, 20.0, 10.0])

    assert OPERATORS["lt"](series, 15.0) is True
    assert OPERATORS["lt"](series[:2], 15.0) is False


def test_eq_uses_a_tolerance_not_exact_float_equality() -> None:
    series = np.array([1.0, 0.1 + 0.2])  # 0.30000000000000004 in binary float

    assert OPERATORS["eq"](series, 0.3) is True


def test_crosses_above_fires_only_on_the_transition_candle() -> None:
    """The direct regression test for the old system's bug: `"bigger"` silently behaved as
    edge-triggered by also checking the previous candle, with nothing documenting it as such.
    Here `crosses_above` is the operator that does that — and only that — on purpose, and `gt`
    (tested above) stays a true level check with no hidden crossing behaviour."""
    series = np.array([5.0, 8.0, 12.0, 15.0])  # crosses 10 between index 1 and 2

    assert OPERATORS["crosses_above"](series[:2], 10.0) is False  # 5 -> 8, not yet
    assert OPERATORS["crosses_above"](series[:3], 10.0) is True  # 8 -> 12, crosses here
    assert OPERATORS["crosses_above"](series[:4], 10.0) is False  # 12 -> 15, already above


def test_crosses_below_fires_only_on_the_transition_candle() -> None:
    series = np.array([15.0, 12.0, 8.0, 5.0])

    assert OPERATORS["crosses_below"](series[:2], 10.0) is False
    assert OPERATORS["crosses_below"](series[:3], 10.0) is True
    assert OPERATORS["crosses_below"](series[:4], 10.0) is False


def test_edge_operators_treat_a_nan_previous_point_as_not_crossed() -> None:
    series = np.array([np.nan, 12.0])

    assert OPERATORS["crosses_above"](series, 10.0) is False
    assert OPERATORS["crosses_below"](series, 10.0) is False
