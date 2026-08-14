"""No `integration` marker: pure computation, same posture as `tests/test_talib.py`."""

from __future__ import annotations

import numpy as np

from cryptovira.apps.strategy.indicators import INDICATORS


def test_sma_matches_a_hand_computed_value() -> None:
    close = np.array([1, 2, 3, 4, 5], dtype=float)

    sma = INDICATORS["SMA"](close, {"timeperiod": 3})

    assert np.isnan(sma[0])
    assert np.isnan(sma[1])
    assert sma[2] == 2.0
    assert sma[4] == 4.0


def test_sma_default_timeperiod_is_twenty_when_variables_omit_it() -> None:
    close = np.arange(1.0, 26.0)  # 25 points

    sma = INDICATORS["SMA"](close, {})

    assert np.isnan(sma[18])  # index 18 -> only 19 points seen, still warming up
    assert not np.isnan(sma[19])  # index 19 -> exactly 20 points seen


def test_rsi_stays_within_its_defined_bounds() -> None:
    prices = np.cumsum(np.random.default_rng(seed=0).normal(size=200)) + 100

    rsi = INDICATORS["RSI"](prices, {"timeperiod": 14})
    valid = rsi[~np.isnan(rsi)]

    assert len(valid) > 0
    assert valid.min() >= 0.0
    assert valid.max() <= 100.0


def test_short_input_returns_nan_padding_not_an_exception() -> None:
    close = np.arange(5.0)

    sma = INDICATORS["SMA"](close, {"timeperiod": 14})

    assert len(sma) == len(close)
    assert np.isnan(sma).all()


def test_macd_line_signal_and_histogram_are_independently_addressable() -> None:
    prices = np.cumsum(np.random.default_rng(seed=1).normal(size=100)) + 100
    variables: dict[str, int] = {}

    macd = INDICATORS["MACD"](prices, variables)
    signal = INDICATORS["MACD_SIGNAL"](prices, variables)
    hist = INDICATORS["MACD_HIST"](prices, variables)

    # hist is defined as macd - signal wherever both are valid.
    valid = ~np.isnan(macd) & ~np.isnan(signal)
    assert np.allclose(hist[valid], macd[valid] - signal[valid])
