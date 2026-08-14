"""Indicator computation. No Django imports — this module is pure `numpy` in, `numpy` out, so
it's testable without a database and reusable outside a Celery task (a backtest, a notebook).

One registry (`INDICATORS`), not the old system's two overlapping dispatchers: a dynamic
`talib.abstract.Function(name)` introspection layer *and* a set of hand-written wrapper functions
that sometimes bypassed it entirely (MACD/TRIX were hand-rolled instead of calling TA-Lib's own).
A plain `dict[str, IndicatorFn]` is the whole dispatch mechanism — explicit, typed, and adding an
indicator later is one registry entry, not a second code path to keep in sync with the first.

`talib` functions never raise on short or empty input — they return a NaN-padded array (or, for
empty input, a zero-length array) of the same length as the input. Checking the *output* for
`InsufficientDataError` is `engine.py`'s job, not this module's; a wrapper here always returns
whatever `talib` gives back.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import talib

type IndicatorFn = Callable[[np.ndarray, dict[str, int]], np.ndarray]


class InsufficientDataError(Exception):
    """Raised by `engine.py` when an indicator's output has no usable (non-NaN) value yet —
    fewer closes were supplied than the indicator's warm-up period requires."""


def _sma(close: np.ndarray, variables: dict[str, int]) -> np.ndarray:
    return talib.SMA(close, timeperiod=variables.get("timeperiod", 20))


def _ema(close: np.ndarray, variables: dict[str, int]) -> np.ndarray:
    return talib.EMA(close, timeperiod=variables.get("timeperiod", 20))


def _rsi(close: np.ndarray, variables: dict[str, int]) -> np.ndarray:
    return talib.RSI(close, timeperiod=variables.get("timeperiod", 14))


def _macd_line(close: np.ndarray, variables: dict[str, int]) -> np.ndarray:
    macd, _, _ = _macd(close, variables)
    return macd


def _macd_signal(close: np.ndarray, variables: dict[str, int]) -> np.ndarray:
    _, signal, _ = _macd(close, variables)
    return signal


def _macd_hist(close: np.ndarray, variables: dict[str, int]) -> np.ndarray:
    _, _, hist = _macd(close, variables)
    return hist


_MacdOutput = tuple[np.ndarray, np.ndarray, np.ndarray]


def _macd(close: np.ndarray, variables: dict[str, int]) -> _MacdOutput:
    return talib.MACD(
        close,
        fastperiod=variables.get("fastperiod", 12),
        slowperiod=variables.get("slowperiod", 26),
        signalperiod=variables.get("signalperiod", 9),
    )


INDICATORS: dict[str, IndicatorFn] = {
    "SMA": _sma,
    "EMA": _ema,
    "RSI": _rsi,
    "MACD": _macd_line,
    "MACD_SIGNAL": _macd_signal,
    "MACD_HIST": _macd_hist,
}
