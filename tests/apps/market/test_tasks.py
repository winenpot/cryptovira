"""`monkeypatch` targets `cryptovira.apps.market.tasks.get_market_data_source` — the name as
`tasks.py` imported it — not `cryptovira.apps.market.sources.get_market_data_source` where it's
defined. `from x import y` binds a new reference at import time; patching the origin module
after that doesn't reach the copy `tasks.py` already holds. This is the standard "patch where
it's used, not where it's defined" mocking gotcha.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cryptovira.apps.market import tasks
from cryptovira.apps.market.models import Candle, Currency, Interval
from cryptovira.apps.market.sources.base import Kline
from tests.apps.market.fakes import FakeMarketDataSource

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _kline(open_minute: int, *, closed: bool = True) -> Kline:
    open_time = datetime(2026, 1, 1, 0, open_minute, tzinfo=UTC)
    close_time = datetime(2026, 1, 1, 0, open_minute + 1, tzinfo=UTC)
    if not closed:
        # Still-forming: close_time in the future relative to "now" at ingest time.
        close_time = datetime(2999, 1, 1, tzinfo=UTC)
    return Kline(
        symbol="BTCUSDT",
        interval="1m",
        open_time=open_time,
        close_time=close_time,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("10"),
    )


def test_ingest_candles_writes_closed_klines(
    monkeypatch: pytest.MonkeyPatch, eager_celery: None
) -> None:
    currency = Currency.objects.create(symbol="BTCUSDT")
    fake = FakeMarketDataSource(klines=[_kline(0), _kline(1)])
    monkeypatch.setattr(tasks, "get_market_data_source", lambda: fake)

    tasks.ingest_candles.delay("BTCUSDT", "1m")

    assert Candle.objects.filter(currency=currency).count() == 2


def test_ingest_candles_drops_the_still_forming_bar(
    monkeypatch: pytest.MonkeyPatch, eager_celery: None
) -> None:
    """A kline whose close_time hasn't passed yet is the in-progress bar Binance includes as the
    last element — writing it once would mean it could never be corrected on a later poll, since
    `bulk_create(ignore_conflicts=True)` silently skips rows that already exist."""
    Currency.objects.create(symbol="BTCUSDT")
    fake = FakeMarketDataSource(klines=[_kline(0), _kline(1, closed=False)])
    monkeypatch.setattr(tasks, "get_market_data_source", lambda: fake)

    tasks.ingest_candles.delay("BTCUSDT", "1m")

    assert Candle.objects.count() == 1


def test_ingest_candles_is_idempotent_under_redelivery(
    monkeypatch: pytest.MonkeyPatch, eager_celery: None
) -> None:
    """The concrete idempotency assertion the roadmap calls for: running the ingest task twice
    with an overlapping batch (as a redelivered task would) must not create duplicate rows, and
    must not raise despite the repeated rows colliding with the unique constraint."""
    Currency.objects.create(symbol="BTCUSDT")
    first_batch = [_kline(0), _kline(1)]
    second_batch = [_kline(1), _kline(2)]  # overlaps candle at minute 1
    fake = FakeMarketDataSource(klines=first_batch)
    monkeypatch.setattr(tasks, "get_market_data_source", lambda: fake)

    tasks.ingest_candles.delay("BTCUSDT", "1m")

    fake.klines = second_batch
    tasks.ingest_candles.delay("BTCUSDT", "1m")  # does not raise on the repeated row

    assert Candle.objects.count() == 3  # minutes 0, 1, 2 — not 4


def test_fan_out_ingest_candles_dispatches_one_task_per_active_currency(
    monkeypatch: pytest.MonkeyPatch, eager_celery: None
) -> None:
    Currency.objects.create(symbol="BTCUSDT")
    Currency.objects.create(symbol="ETHUSDT")
    Currency.objects.create(symbol="XRPUSDT", is_active=False)
    fake = FakeMarketDataSource(klines=[_kline(0)])
    monkeypatch.setattr(tasks, "get_market_data_source", lambda: fake)

    tasks.fan_out_ingest_candles.delay("1m")

    assert {call[0] for call in fake.calls} == {"BTCUSDT", "ETHUSDT"}


def test_ingest_candles_requests_the_given_interval(
    monkeypatch: pytest.MonkeyPatch, eager_celery: None
) -> None:
    Currency.objects.create(symbol="BTCUSDT")
    fake = FakeMarketDataSource(klines=[])
    monkeypatch.setattr(tasks, "get_market_data_source", lambda: fake)

    tasks.ingest_candles.delay("BTCUSDT", "5m")

    assert fake.calls == [("BTCUSDT", Interval.FIVE_MINUTES)]
