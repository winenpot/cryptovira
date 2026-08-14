from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from cryptovira.apps.accounts.models import User
from cryptovira.apps.market.models import Currency, Interval
from cryptovira.apps.strategy.models import Strategy, StrategyEvaluation

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

VALID_CONFIG = {"conditions": [{"indicator": "RSI", "operator": "lt", "value": 30}]}


def _user() -> User:
    return User.objects.create_user(email="trader@example.com", password="pw")


def _currency() -> Currency:
    return Currency.objects.create(symbol="BTCUSDT")


def test_save_accepts_a_valid_config() -> None:
    strategy = Strategy.objects.create(
        user=_user(),
        currency=_currency(),
        interval=Interval.ONE_HOUR,
        name="RSI oversold",
        config=VALID_CONFIG,
    )

    assert strategy.pk is not None


def test_save_rejects_an_invalid_config() -> None:
    """`Strategy.save()` always calls `full_clean()` — an invalid config must never reach the
    database, since it would silently break every future `evaluate_strategy` run for this row."""
    with pytest.raises(ValidationError):
        Strategy.objects.create(
            user=_user(),
            currency=_currency(),
            interval=Interval.ONE_HOUR,
            name="Broken",
            config={"conditions": [{"indicator": "NOT_REAL", "operator": "lt", "value": 30}]},
        )


def test_save_rejects_a_config_with_an_unknown_key() -> None:
    with pytest.raises(ValidationError):
        Strategy.objects.create(
            user=_user(),
            currency=_currency(),
            interval=Interval.ONE_HOUR,
            name="Typo'd",
            config={"conditions": [{"indicator": "RSI", "opreator": "lt", "value": 30}]},
        )


def test_deleting_a_user_cascades_to_their_strategies() -> None:
    user = _user()
    Strategy.objects.create(
        user=user, currency=_currency(), interval=Interval.ONE_HOUR, name="X", config=VALID_CONFIG
    )

    user.delete()

    assert Strategy.objects.count() == 0


def test_strategy_evaluation_uniqueness_is_a_real_database_constraint() -> None:
    """Mirrors `Candle`'s own unique-constraint test: the idempotency mechanism the ingest task
    already relies on, applied here to evaluation audit rows."""
    strategy = Strategy.objects.create(
        user=_user(),
        currency=_currency(),
        interval=Interval.ONE_HOUR,
        name="X",
        config=VALID_CONFIG,
    )
    open_time = datetime(2026, 1, 1, tzinfo=UTC)
    StrategyEvaluation.objects.create(strategy=strategy, candle_open_time=open_time, triggered=True)

    with pytest.raises(IntegrityError), transaction.atomic():
        StrategyEvaluation.objects.create(
            strategy=strategy, candle_open_time=open_time, triggered=False
        )
