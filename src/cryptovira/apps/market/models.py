"""Market data: which symbols to track, and the candles ingested for them.

Design notes worth knowing cold for an interview:

- ``Interval`` is deliberately the *one* place a timeframe is spelled out. The old system had two
  divergent representations of the same fifteen timeframes — a seconds-as-string choices tuple
  duplicated across three models, and a second, separately hardcoded Binance-string list in its
  streaming service. One canonical enum, reused everywhere a timeframe is needed, makes that class
  of drift impossible.
- ``Candle.open_time``/``close_time`` are always built from an explicit UTC epoch conversion
  (``datetime.fromtimestamp(ms / 1000, tz=UTC)``), never ``time.localtime`` — the old system
  silently stored server-local time in a column that ``USE_TZ = True`` promised was UTC.
- ``Candle``'s uniqueness constraint is the actual idempotency mechanism the roadmap calls for: a
  redelivered ingest task (``task_acks_late`` guarantees redelivery happens) re-attempts the same
  insert and the database silently rejects the duplicate — the same DB-constraint-over-check-then-
  save principle as ``accounts.User.email`` (see docs/adr/0005-custom-user-model.md).
"""

from __future__ import annotations

from django.db import models

from cryptovira.apps.common.models import TimestampedModel


class Interval(models.TextChoices):
    """The timeframes a strategy might actually evaluate — not full parity with every interval
    an exchange offers. Binance alone supports fifteen; nothing in this roadmap has a consumer
    for `1s`, `3d`, `6h`, `8h`, `12h`, or `1M` yet, and adding a value later is a non-breaking
    `choices=` change, not a migration."""

    ONE_MINUTE = "1m", "1 minute"
    FIVE_MINUTES = "5m", "5 minutes"
    FIFTEEN_MINUTES = "15m", "15 minutes"
    THIRTY_MINUTES = "30m", "30 minutes"
    ONE_HOUR = "1h", "1 hour"
    FOUR_HOURS = "4h", "4 hours"
    ONE_DAY = "1d", "1 day"
    ONE_WEEK = "1w", "1 week"


class Currency(TimestampedModel):
    """A tradeable symbol, e.g. ``BTCUSDT``. Deliberately thin: no price/market-cap/precision
    tracking (that was old-model bloat with no consumer here), and no spot/futures ``market``
    field — the old system added one *without* making it part of the uniqueness constraint
    ("unique=False because of future market"), so `symbol` alone stayed non-unique even though
    only spot ever shipped. Adding a real second market later is a straightforward
    `unique_together` migration; adding an unused field today just to avoid that migration
    repeats the exact mistake."""

    symbol = models.CharField(
        max_length=20, unique=True, help_text='Exchange symbol, e.g. "BTCUSDT".'
    )
    name = models.CharField(
        max_length=100, blank=True, help_text='Display name, e.g. "Bitcoin / USDT".'
    )
    is_active = models.BooleanField(
        default=True, help_text="Whether the ingest task fans out to this symbol."
    )

    class Meta:
        ordering = ("symbol",)

    def __str__(self) -> str:
        return self.symbol


class Candle(models.Model):
    """One OHLCV bar. Append-only — a closed candle's values never change, so unlike `Currency`
    this does not inherit `TimestampedModel`: an `updated_at` that always equals `created_at`
    would misrepresent the row as something that gets edited."""

    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="candles")
    interval = models.CharField(max_length=3, choices=Interval.choices)
    open_time = models.DateTimeField()
    close_time = models.DateTimeField()
    open = models.DecimalField(max_digits=20, decimal_places=8)
    high = models.DecimalField(max_digits=20, decimal_places=8)
    low = models.DecimalField(max_digits=20, decimal_places=8)
    close = models.DecimalField(max_digits=20, decimal_places=8)
    volume = models.DecimalField(max_digits=20, decimal_places=8)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("currency", "interval", "open_time")
        constraints = (
            models.UniqueConstraint(
                fields=("currency", "interval", "open_time"),
                name="unique_candle_per_currency_interval_open_time",
            ),
        )

    def __str__(self) -> str:
        return f"{self.currency.symbol} {self.interval} @ {self.open_time.isoformat()}"
