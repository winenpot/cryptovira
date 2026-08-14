"""The exchange-facing interface. This is the first `Protocol` in the codebase — structural
typing, not `abc.ABC`: a real implementation and a test fake need no inheritance relationship
to satisfy it, which is the point of "so tests never hit the network" (see docs/roadmap.md and
docs/adr/0007-market-data-source-interface.md).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import NamedTuple, Protocol

from cryptovira.apps.market.models import Interval


class Kline(NamedTuple):
    """One parsed OHLCV bar as returned by a `MarketDataSource` — the clean shape the rest of
    the app works with, independent of any one exchange's raw wire format (Binance's REST klines
    endpoint returns a 12-element positional array; this is what it gets parsed into)."""

    symbol: str
    interval: str
    open_time: datetime
    close_time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


class MarketDataSource(Protocol):
    def get_klines(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int = 500,
        start_time: datetime | None = None,
    ) -> Sequence[Kline]:
        """Fetch up to `limit` klines for `symbol`/`interval`, optionally starting at
        `start_time`. Implementations may include the still-forming (unclosed) bar as the last
        element — callers that write to `Candle` must filter it out themselves."""
        ...
