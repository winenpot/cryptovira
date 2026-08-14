"""`Strategy` (user-authored configuration) and `StrategyEvaluation` (the audit row every
evaluation run writes — see `apps/strategy/tasks.py`).

Design notes worth knowing cold for an interview:

- `Strategy.save()` always calls `full_clean()` — the one model in this codebase that pays that
  cost on every save. An invalid `config` isn't cosmetically wrong the way a blank optional field
  would be: it silently breaks every future `evaluate_strategy` run for this strategy, discovered
  one audit row at a time instead of at the point of authorship. That asymmetry is why this model
  gets the stronger guarantee `Currency`/`Candle` don't need.
- `StrategyEvaluation`'s `UniqueConstraint(strategy, candle_open_time)` mirrors `Candle`'s own
  `(currency, interval, open_time)` constraint exactly — "this strategy, this closed candle" is
  the natural once-only unit of work, same DB-constraint-over-check-then-save principle as
  ADR 0005's email constraint and ADR 0007's candle idempotency.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import models
from pydantic import ValidationError as PydanticValidationError

from cryptovira.apps.accounts.models import User
from cryptovira.apps.common.models import TimestampedModel
from cryptovira.apps.market.models import Currency, Interval
from cryptovira.apps.strategy.schema import StrategyConfig


class Strategy(TimestampedModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="strategies")
    # PROTECT, not CASCADE: mirrors Candle.currency — a Currency is a shared market-data fact,
    # decommissioned via is_active=False, never deleted out from under a strategy that names it.
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="strategies")
    interval = models.CharField(max_length=3, choices=Interval.choices)
    name = models.CharField(max_length=200)
    config = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        super().clean()
        try:
            StrategyConfig.model_validate(self.config)
        except PydanticValidationError as exc:
            # Same shape as RegisterSerializer.validate_password (apps/accounts/api/serializers.py):
            # catch the framework-specific error, re-raise the framework-native one.
            raise DjangoValidationError({"config": str(exc)}) from exc

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.full_clean()
        super().save(*args, **kwargs)


class StrategyEvaluation(models.Model):
    """Append-only, like `Candle` — not `TimestampedModel`: a completed evaluation is a
    historical fact, never edited after the fact."""

    strategy = models.ForeignKey(Strategy, on_delete=models.CASCADE, related_name="evaluations")
    candle_open_time = models.DateTimeField()
    evaluated_at = models.DateTimeField(auto_now_add=True)
    triggered = models.BooleanField(default=False)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ("-evaluated_at",)
        constraints = (
            models.UniqueConstraint(
                fields=("strategy", "candle_open_time"),
                name="unique_strategy_evaluation_per_candle",
            ),
        )

    def __str__(self) -> str:
        return f"{self.strategy.name} @ {self.candle_open_time.isoformat()}"
