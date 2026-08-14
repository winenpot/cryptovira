from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.db import IntegrityError, transaction

from cryptovira.apps.accounts.models import User
from cryptovira.apps.market.models import Currency, Interval
from cryptovira.apps.signals.models import Channel, NotificationRecipient, Signal
from cryptovira.apps.strategy.models import Strategy, StrategyEvaluation

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

VALID_CONFIG = {"conditions": [{"indicator": "RSI", "operator": "lt", "value": 30}]}


def _evaluation() -> StrategyEvaluation:
    user = User.objects.create_user(email="trader@example.com", password="pw")
    currency = Currency.objects.create(symbol="BTCUSDT")
    strategy = Strategy.objects.create(
        user=user, currency=currency, interval=Interval.ONE_HOUR, name="X", config=VALID_CONFIG
    )
    return StrategyEvaluation.objects.create(
        strategy=strategy, candle_open_time=datetime(2026, 1, 1, tzinfo=UTC), triggered=True
    )


def test_signal_uniqueness_per_evaluation_is_a_real_database_constraint() -> None:
    """`Signal.evaluation` is a `OneToOneField` — its implicit unique index is the whole
    idempotency mechanism (see the models.py module docstring). Mirrors
    `StrategyEvaluation`'s own uniqueness test, one layer up the chain."""
    evaluation = _evaluation()
    Signal.objects.create(evaluation=evaluation)

    with pytest.raises(IntegrityError), transaction.atomic():
        Signal.objects.create(evaluation=evaluation)


def test_notification_recipient_uniqueness_per_user_and_channel() -> None:
    user = User.objects.create_user(email="trader@example.com", password="pw")
    NotificationRecipient.objects.create(user=user, channel=Channel.TELEGRAM, destination="123")

    with pytest.raises(IntegrityError), transaction.atomic():
        NotificationRecipient.objects.create(user=user, channel=Channel.TELEGRAM, destination="456")
