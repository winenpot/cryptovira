"""The swap point tests use to avoid the network: `get_market_data_source()` is what
`tasks.py` calls, and tests `monkeypatch.setattr` this exact name to inject a fake. There is
deliberately no settings-driven "which backend" toggle — one real implementation exists, and a
config-driven strategy pattern guarding a single concrete class would be speculative.
"""

from __future__ import annotations

from cryptovira.apps.market.sources.base import Kline, MarketDataSource
from cryptovira.apps.market.sources.binance import BinanceRestMarketDataSource

__all__ = ["Kline", "MarketDataSource", "get_market_data_source"]


def get_market_data_source() -> MarketDataSource:
    return BinanceRestMarketDataSource()
