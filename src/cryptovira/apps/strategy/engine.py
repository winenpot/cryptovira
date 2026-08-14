"""Ties `schema.py`'s validated config to `indicators.py`/`operators.py`'s registries. No Django
imports — the only Django-aware code in this app is `models.py`/`tasks.py`, which convert a
`Strategy` row's `config` and a `QuerySet` of `Candle`s into the plain `numpy.ndarray` this module
actually needs.
"""

from __future__ import annotations

import math

import numpy as np

from cryptovira.apps.strategy.indicators import INDICATORS, InsufficientDataError
from cryptovira.apps.strategy.operators import OPERATORS
from cryptovira.apps.strategy.schema import Condition, StrategyConfig

#: The smallest series length every operator can safely read: level operators need `series[-1]`,
#: edge operators additionally need `series[-2]` to exist (its value may still be NaN — a NaN
#: comparison is simply `False`, not a crash — but the index itself must be valid).
_MIN_SERIES_LENGTH = 2


def evaluate(config: StrategyConfig, close: np.ndarray) -> bool:
    """True only if every condition holds (AND-chained — see `schema.py`'s docstring).

    Raises `InsufficientDataError` if any condition's indicator has no usable value yet for the
    given `close` history; the caller (`tasks.py`) is expected to catch this and write it into the
    evaluation's audit row rather than let the task fail outright.
    """
    return all(_evaluate_condition(condition, close) for condition in config.conditions)


def _evaluate_condition(condition: Condition, close: np.ndarray) -> bool:
    series = INDICATORS[condition.indicator](close, condition.variables)
    if len(series) < _MIN_SERIES_LENGTH or math.isnan(series[-1]):
        msg = (
            f"{condition.indicator}{condition.variables or ''} needs more historical candles "
            f"than the {len(close)} supplied."
        )
        raise InsufficientDataError(msg)
    return OPERATORS[condition.operator](series, condition.value)
