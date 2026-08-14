"""Pure unit tests — no `integration` marker, no database. `httpx.MockTransport` (built into
httpx) stands in for the network, so this only exercises `BinanceRestMarketDataSource`'s
response parsing."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import httpx

from cryptovira.apps.market.models import Interval
from cryptovira.apps.market.sources.binance import BinanceRestMarketDataSource

# One real row from Binance's documented kline response shape:
# [openTime, open, high, low, close, volume, closeTime, quoteVolume, trades, takerBuyBase,
#  takerBuyQuote, ignore]
RAW_KLINE = [
    1499040000000,
    "0.01634790",
    "0.80000000",
    "0.01575800",
    "0.01577100",
    "148976.11427815",
    1499644799999,
    "2434.19055334",
    308,
    "1756.87402397",
    "28.46694368",
    "17928899.62484339",
]


def _source_with_response(payload: list[object]) -> BinanceRestMarketDataSource:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v3/klines"
        assert request.url.params["symbol"] == "BTCUSDT"
        assert request.url.params["interval"] == "1h"
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test")
    return BinanceRestMarketDataSource(client=client)


def test_get_klines_parses_the_documented_response_shape() -> None:
    source = _source_with_response([RAW_KLINE])

    klines = source.get_klines(symbol="BTCUSDT", interval=Interval.ONE_HOUR)

    assert len(klines) == 1
    kline = klines[0]
    assert kline.symbol == "BTCUSDT"
    assert kline.interval == "1h"
    assert kline.open_time == datetime.fromtimestamp(1499040000, tz=UTC)
    assert kline.close_time == datetime.fromtimestamp(1499644799.999, tz=UTC)
    assert kline.open == Decimal("0.01634790")
    assert kline.high == Decimal("0.80000000")
    assert kline.low == Decimal("0.01575800")
    assert kline.close == Decimal("0.01577100")
    assert kline.volume == Decimal("148976.11427815")


def test_get_klines_parses_prices_as_decimal_not_float() -> None:
    """Prices come off the wire as strings specifically so a client can avoid float rounding —
    parsing straight through `Decimal(str)` is what actually captures that guarantee."""
    source = _source_with_response([RAW_KLINE])

    kline = source.get_klines(symbol="BTCUSDT", interval=Interval.ONE_HOUR)[0]

    assert isinstance(kline.open, Decimal)


def test_get_klines_returns_empty_for_an_empty_response() -> None:
    source = _source_with_response([])

    assert source.get_klines(symbol="BTCUSDT", interval=Interval.ONE_HOUR) == []
