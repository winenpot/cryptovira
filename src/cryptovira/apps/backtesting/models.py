"""`Backtest`: replay a `Strategy` against historical `Candle` data over a date range.

Design notes worth knowing cold for an interview — see
docs/adr/0010-backtest-forward-return-proxy.md and docs/interview/05.5-backtesting.md for the
full walkthrough:

- Unlike `Candle`/`StrategyEvaluation`/`Signal` (append-only, no `TimestampedModel`), a `Backtest`
  row is created once but mutated repeatedly by `apps/backtesting/tasks.py::run_backtest` as it
  runs (`status`, `progress`, then the result fields) — the same `TimestampedModel` fit as
  `NotificationDelivery` (ADR 0009): `updated_at` genuinely means "last time the system touched
  this row," not "last time a human edited config."
- No `strategy_json` config snapshot (the old model's approach). `StrategyEvaluation` already set
  the precedent of FK-only, no snapshot: a `Backtest` row records what happened when the task
  *ran*, not a reinterpretable reference to a config that might drift later. Editing
  `Strategy.config` after a `Backtest` has completed doesn't retroactively change its stored
  results.
- `win_rate`/`total_forward_return` are a side-agnostic forward-return *proxy*, not real position
  P&L — `StrategyConfig` (apps/strategy/schema.py) has no side/stop-loss/take-profit fields to
  simulate a real trade against. See ADR 0010 for why, and for what this number does and doesn't
  mean. `scored_trigger_count` is deliberately tracked separately from `trigger_count`: a trigger
  near `end_time` may not have `horizon_candles` of real future data to measure a return over, and
  silently scoring it anyway (e.g. treating a missing forward candle as a zero return) would
  fabricate a result from data that doesn't exist.
"""

from __future__ import annotations

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from cryptovira.apps.common.models import TimestampedModel
from cryptovira.apps.strategy.models import Strategy


class BacktestStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"


class Backtest(TimestampedModel):
    strategy = models.ForeignKey(Strategy, on_delete=models.CASCADE, related_name="backtests")
    start_time = models.DateTimeField(help_text="UTC, inclusive.")
    end_time = models.DateTimeField(help_text="UTC, exclusive.")
    horizon_candles = models.PositiveSmallIntegerField(
        default=10,
        validators=[MinValueValidator(1)],
        help_text="Candles forward from a trigger used to score its forward return (ADR 0010).",
    )

    status = models.CharField(
        max_length=10, choices=BacktestStatus.choices, default=BacktestStatus.PENDING
    )
    progress = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(100)])
    error = models.TextField(blank=True)

    trigger_count = models.PositiveIntegerField(null=True, blank=True)
    scored_trigger_count = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Triggers with enough forward candles to score; <= trigger_count. The gap is "
            "triggers too close to end_time to measure a full horizon."
        ),
    )
    win_count = models.PositiveIntegerField(null=True, blank=True)
    win_rate = models.FloatField(
        null=True, blank=True, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    total_forward_return = models.FloatField(
        null=True,
        blank=True,
        help_text="Sum of forward returns (%) over every scored trigger — the R/R proxy; see "
        "ADR 0010.",
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return (
            f"{self.strategy.name} {self.start_time:%Y-%m-%d}->{self.end_time:%Y-%m-%d} "
            f"({self.status})"
        )
