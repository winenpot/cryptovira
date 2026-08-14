"""No `integration` marker: pure computation."""

from __future__ import annotations

import numpy as np
import pytest

from cryptovira.apps.strategy.engine import evaluate
from cryptovira.apps.strategy.indicators import InsufficientDataError
from cryptovira.apps.strategy.schema import StrategyConfig


def _config(**conditions: object) -> StrategyConfig:
    return StrategyConfig.model_validate({"conditions": [conditions]})


def test_a_single_true_condition_triggers() -> None:
    close = np.full(30, 10.0)
    config = _config(indicator="SMA", variables={"timeperiod": 5}, operator="eq", value=10.0)

    assert evaluate(config, close) is True


def test_all_conditions_must_hold_and_chained_not_or() -> None:
    """Matches the old system's *actual* behaviour (loop-and-break-on-first-failure), made
    explicit here rather than left undocumented."""
    close = np.full(30, 10.0)
    sma_5 = {"indicator": "SMA", "variables": {"timeperiod": 5}}
    config = StrategyConfig.model_validate(
        {
            "conditions": [
                {**sma_5, "operator": "eq", "value": 10.0},
                {**sma_5, "operator": "gt", "value": 999.0},
            ]
        }
    )

    assert evaluate(config, close) is False


def test_insufficient_data_raises_rather_than_returning_false() -> None:
    """A strategy that hasn't seen enough candles yet is a distinct outcome from "conditions
    evaluated and didn't hold" — the caller (tasks.py) is expected to record this separately
    (`StrategyEvaluation.error`), not silently record `triggered=False`."""
    close = np.arange(3.0)
    config = _config(indicator="SMA", variables={"timeperiod": 14}, operator="gt", value=0.0)

    with pytest.raises(InsufficientDataError):
        evaluate(config, close)


def test_crosses_above_end_to_end_through_the_engine() -> None:
    # SMA(timeperiod=1) is the identity function, so the indicator series equals `close` — the
    # last two points (8, 12) straddle the threshold, a crossing on the final candle.
    close = np.array([5.0, 8.0, 12.0])
    config = _config(
        indicator="SMA", variables={"timeperiod": 1}, operator="crosses_above", value=10.0
    )

    assert evaluate(config, close) is True
