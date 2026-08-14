"""`FakeMarketDataSource` is the test double `MarketDataSource` exists for: a plain class
implementing `get_klines` with no base class needed (it's a `Protocol`, structural typing).
Tests inject it by monkeypatching `get_market_data_source` itself, since a `MarketDataSource`
instance can't travel as a Celery task argument (task args must be JSON-serializable).

Deliberately not in `conftest.py`: pytest auto-discovers `conftest.py` by its own mechanism,
and a test file that also `import`s it directly as a regular module gives mypy two different
module paths for the same file ("apps.market.conftest" vs "tests.apps.market.conftest").
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from cryptovira.apps.market.models import Interval
from cryptovira.apps.market.sources.base import Kline


class FakeMarketDataSource:
    def __init__(self, klines: Sequence[Kline] = ()) -> None:
        self.klines = list(klines)
        self.calls: list[tuple[str, Interval]] = []

    def get_klines(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int = 500,
        start_time: datetime | None = None,
    ) -> Sequence[Kline]:
        self.calls.append((symbol, interval))
        return self.klines
