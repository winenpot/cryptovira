from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from cryptovira.apps.accounts.models import User
from cryptovira.apps.market.models import Candle, Currency, Interval
from cryptovira.apps.signals import tasks
from cryptovira.apps.signals.models import (
    Channel,
    DeliveryStatus,
    NotificationDelivery,
    NotificationRecipient,
    Signal,
)
from cryptovira.apps.strategy.models import Strategy, StrategyEvaluation
from tests.apps.signals.fakes import FakeChannel

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

VALID_CONFIG = {"conditions": [{"indicator": "RSI", "operator": "lt", "value": 30}]}


def _signal(user: User) -> Signal:
    currency = Currency.objects.create(symbol="BTCUSDT")
    strategy = Strategy.objects.create(
        user=user, currency=currency, interval=Interval.ONE_HOUR, name="X", config=VALID_CONFIG
    )
    open_time = datetime(2026, 1, 1, tzinfo=UTC)
    evaluation = StrategyEvaluation.objects.create(
        strategy=strategy, candle_open_time=open_time, triggered=True
    )
    Candle.objects.create(
        currency=currency,
        interval=strategy.interval,
        open_time=open_time,
        close_time=open_time,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("10"),
    )
    return Signal.objects.create(evaluation=evaluation)


def _user() -> User:
    return User.objects.create_user(email="trader@example.com", password="pw")


def test_dispatch_notifications_creates_one_delivery_per_active_recipient(
    eager_celery: None,
) -> None:
    user = _user()
    NotificationRecipient.objects.create(user=user, channel=Channel.TELEGRAM, destination="1")
    NotificationRecipient.objects.create(user=user, channel=Channel.WEBHOOK, destination="2")
    signal = _signal(user)

    tasks.dispatch_notifications(signal.id)

    assert NotificationDelivery.objects.filter(signal=signal).count() == 2


def test_dispatch_notifications_skips_inactive_recipients(eager_celery: None) -> None:
    # A user can have at most one destination per channel (unique_recipient_per_user_channel),
    # so "inactive" is tested as its own recipient, not a second row on the same channel.
    user = _user()
    NotificationRecipient.objects.create(
        user=user, channel=Channel.TELEGRAM, destination="1", is_active=False
    )
    signal = _signal(user)

    tasks.dispatch_notifications(signal.id)

    assert NotificationDelivery.objects.filter(signal=signal).count() == 0


def test_dispatch_notifications_is_idempotent_under_redelivery(eager_celery: None) -> None:
    user = _user()
    NotificationRecipient.objects.create(user=user, channel=Channel.TELEGRAM, destination="1")
    signal = _signal(user)

    tasks.dispatch_notifications(signal.id)
    tasks.dispatch_notifications(signal.id)  # does not raise, does not duplicate

    assert NotificationDelivery.objects.filter(signal=signal).count() == 1


def test_send_notification_marks_delivery_sent_on_success(
    monkeypatch: pytest.MonkeyPatch, eager_celery: None
) -> None:
    user = _user()
    recipient = NotificationRecipient.objects.create(
        user=user, channel=Channel.TELEGRAM, destination="1"
    )
    signal = _signal(user)
    delivery = NotificationDelivery.objects.create(signal=signal, recipient=recipient)
    fake = FakeChannel()
    monkeypatch.setattr(tasks, "get_channel", lambda _channel: fake)

    tasks.send_notification.delay(delivery.id)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.SENT
    assert delivery.attempts == 1
    assert len(fake.sent) == 1
    assert fake.sent[0][0] == "1"


def test_send_notification_is_a_noop_if_already_sent(
    monkeypatch: pytest.MonkeyPatch, eager_celery: None
) -> None:
    user = _user()
    recipient = NotificationRecipient.objects.create(
        user=user, channel=Channel.TELEGRAM, destination="1"
    )
    signal = _signal(user)
    delivery = NotificationDelivery.objects.create(
        signal=signal, recipient=recipient, status=DeliveryStatus.SENT, attempts=1
    )
    fake = FakeChannel()
    monkeypatch.setattr(tasks, "get_channel", lambda _channel: fake)

    tasks.send_notification.delay(delivery.id)

    assert fake.sent == []  # never called — the redelivery guard short-circuited first


def test_send_notification_retries_then_dead_letters_on_permanent_failure(
    monkeypatch: pytest.MonkeyPatch, eager_celery: None
) -> None:
    """Under `eager_celery`, `self.retry()` executes inline/recursively — this proves the retry
    *count* and *end state* (reaches FAILED after exactly `max_retries` retries), not real
    backoff timing. See docs/interview/05-concurrency-and-correctness.md for what a manual check
    against the real running stack additionally needs to confirm."""
    user = _user()
    recipient = NotificationRecipient.objects.create(
        user=user, channel=Channel.TELEGRAM, destination="1"
    )
    signal = _signal(user)
    delivery = NotificationDelivery.objects.create(signal=signal, recipient=recipient)
    fake = FakeChannel(always_fails=True)
    monkeypatch.setattr(tasks, "get_channel", lambda _channel: fake)

    tasks.send_notification.delay(delivery.id)

    delivery.refresh_from_db()
    assert delivery.status == DeliveryStatus.FAILED
    assert delivery.attempts == tasks.send_notification.max_retries + 1
    assert delivery.last_error != ""
