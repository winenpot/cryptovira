"""Proves the TA-Lib C library is actually present and computing correctly — not just that the
Python package imported. See docs/adr/0006-ta-lib-packaging.md for why this needed no compiler,
no system packages, and no multi-stage cleanup: the wheel bundles the C library.

No `integration` marker: this is pure computation, no database/broker/cache involved.
"""

from __future__ import annotations

import numpy as np
import talib


def test_talib_reports_the_full_function_set() -> None:
    # A stub/partial install (e.g. the C library missing) surfaces here as an import failure or
    # a near-empty function table — TA-Lib 0.7.1 reports 161 indicator/pattern/math functions;
    # a threshold well below that (not an exact match) tolerates future TA-Lib releases adding
    # a handful more without this test needing an update every bump.
    # talib ships `py.typed` and real stubs for the indicator functions (SMA, RSI, ...) — but
    # `get_functions()` itself is a plain, unannotated function in talib/__init__.py, a genuine
    # upstream gap rather than a "no stubs at all" situation `ignore_missing_imports` is for.
    assert len(talib.get_functions()) >= 150  # type: ignore[no-untyped-call]


def test_sma_matches_a_hand_computed_value() -> None:
    # Not "does it return something" — does it compute the *right* number. A 3-period SMA
    # needs 2 warm-up values (TA-Lib returns NaN, not zeros, for the unfilled window).
    close = np.array([1, 2, 3, 4, 5], dtype=float)

    sma = talib.SMA(close, timeperiod=3)

    assert np.isnan(sma[0])
    assert np.isnan(sma[1])
    assert sma[2] == 2.0  # mean(1, 2, 3)
    assert sma[3] == 3.0  # mean(2, 3, 4)
    assert sma[4] == 4.0  # mean(3, 4, 5)


def test_rsi_stays_within_its_defined_bounds() -> None:
    # RSI is defined on [0, 100] by construction; this is the kind of invariant that catches a
    # bad build (wrong C library version, ABI mismatch) even without a hand-computed reference.
    prices = np.cumsum(np.random.default_rng(seed=0).normal(size=200)) + 100

    rsi = talib.RSI(prices, timeperiod=14)
    valid = rsi[~np.isnan(rsi)]

    assert len(valid) > 0
    assert valid.min() >= 0.0
    assert valid.max() <= 100.0
