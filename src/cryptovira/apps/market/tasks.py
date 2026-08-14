"""Candle ingestion. Two tasks, both idempotent under Celery's `task_acks_late` +
`task_reject_on_worker_lost` redelivery (see `cryptovira.celery`):

- `fan_out_ingest_candles` runs on a beat schedule, one entry per interval cadence — never per
  (currency, interval) pair, so toggling a currency's `is_active` flag in admin never requires
  touching `celery.py`. It dispatches one `ingest_candles` per active symbol via `group()`, so
  one symbol's redelivery/failure stays isolated from the rest.
- `ingest_candles` writes with `bulk_create(..., ignore_conflicts=True)`, relying on `Candle`'s
  `UniqueConstraint` rather than `update_or_create`: a closed candle is an immutable fact, so a
  redelivered task has nothing to *update*, only a duplicate insert to have silently rejected.
"""

from __future__ import annotations

from datetime import UTC, datetime

from celery import group

from cryptovira.apps.market.models import Candle, Currency, Interval
from cryptovira.apps.market.sources import get_market_data_source
from cryptovira.celery import app


@app.task(ignore_result=True)  # type: ignore[untyped-decorator]  # celery is untyped
def fan_out_ingest_candles(interval: str) -> None:
    symbols = list(Currency.objects.filter(is_active=True).values_list("symbol", flat=True))
    group(ingest_candles.s(symbol, interval) for symbol in symbols)()


@app.task(ignore_result=True)  # type: ignore[untyped-decorator]  # celery is untyped
def ingest_candles(symbol: str, interval: str) -> None:
    currency = Currency.objects.get(symbol=symbol)
    source = get_market_data_source()
    klines = source.get_klines(symbol=symbol, interval=Interval(interval))

    # Binance's klines response can include the still-forming bar as the last element. Written
    # once, it could never be corrected on a later poll under `ignore_conflicts=True` — drop any
    # bar that hasn't closed yet.
    now = datetime.now(UTC)
    candles = [
        Candle(
            currency=currency,
            interval=kline.interval,
            open_time=kline.open_time,
            close_time=kline.close_time,
            open=kline.open,
            high=kline.high,
            low=kline.low,
            close=kline.close,
            volume=kline.volume,
        )
        for kline in klines
        if kline.close_time < now
    ]
    Candle.objects.bulk_create(candles, ignore_conflicts=True)
