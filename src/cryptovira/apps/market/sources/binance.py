"""A thin client for Binance's public spot klines endpoint.

Not the vendored `python-binance` fork the old system carried, and not the `python-binance`
PyPI package either — see docs/adr/0007-market-data-source-interface.md for why: no auth is
needed for public market data, the wheel ships no type stubs (a `mypy` `ignore_missing_imports`
override this project would rather not add), and it wraps far more surface (futures, margin,
websockets) than one REST endpoint needs. `httpx` ships `py.typed` and needs no such override.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from cryptovira.apps.market.models import Interval
from cryptovira.apps.market.sources.base import Kline
from cryptovira.config import get_settings

KLINES_PATH = "/api/v3/klines"


class BinanceRestMarketDataSource:
    """Implements `MarketDataSource` (structurally — `Protocol`, no inheritance needed)."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        settings = get_settings()
        self._client = client or httpx.Client(
            base_url=settings.market_data_base_url,
            timeout=settings.market_data_request_timeout_seconds,
        )

    def get_klines(
        self,
        *,
        symbol: str,
        interval: Interval,
        limit: int = 500,
        start_time: datetime | None = None,
    ) -> Sequence[Kline]:
        params: dict[str, Any] = {"symbol": symbol, "interval": interval.value, "limit": limit}
        if start_time is not None:
            params["startTime"] = int(start_time.timestamp() * 1000)

        response = self._client.get(KLINES_PATH, params=params)
        response.raise_for_status()
        return [self._parse_kline(symbol, interval.value, row) for row in response.json()]

    @staticmethod
    def _parse_kline(symbol: str, interval: str, row: list[Any]) -> Kline:
        # Binance's documented positional shape: [openTime, open, high, low, close, volume,
        # closeTime, quoteVolume, trades, takerBuyBase, takerBuyQuote, ignore].
        open_time_ms, open_, high, low, close, volume, close_time_ms = row[:7]
        return Kline(
            symbol=symbol,
            interval=interval,
            open_time=_from_epoch_ms(open_time_ms),
            close_time=_from_epoch_ms(close_time_ms),
            open=Decimal(open_),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal(close),
            volume=Decimal(volume),
        )


def _from_epoch_ms(epoch_ms: int) -> datetime:
    # Explicit UTC conversion — the old system's `time.localtime(x / 1000)` silently stored
    # server-local time in a column `USE_TZ = True` promised was UTC. Never repeat that here.
    return datetime.fromtimestamp(epoch_ms / 1000, tz=UTC)
