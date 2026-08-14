"""`record_signal`'s `transaction.on_commit(...)` callback never fires inside a plain
`@pytest.mark.django_db` test — pytest-django wraps each test in a transaction that gets rolled
back at the end, not committed, and `on_commit` callbacks only run on a real commit. These tests
use pytest-django's `django_capture_on_commit_callbacks` fixture (wrapping Django's own
`TestCase.captureOnCommitCallbacks`) to explicitly capture and execute them — without it, a test
asserting `dispatch_notifications` was called would silently see nothing happen, not a failure
pointing at the real cause.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from cryptovira.apps.accounts.models import User
from cryptovira.apps.market.models import Candle, Currency, Interval
from cryptovira.apps.signals.models import Signal
from cryptovira.apps.signals.services import build_message_context, record_signal
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


def test_record_signal_creates_a_signal_and_schedules_dispatch(
    django_capture_on_commit_callbacks: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispatched: list[int] = []
    monkeypatch.setattr(
        "cryptovira.apps.signals.tasks.dispatch_notifications.delay",
        lambda signal_id: dispatched.append(signal_id),
    )
    evaluation = _evaluation()

    with django_capture_on_commit_callbacks(execute=True):
        signal = record_signal(evaluation)

    assert Signal.objects.filter(evaluation=evaluation).count() == 1
    assert dispatched == [signal.id]


def test_record_signal_is_idempotent_under_redelivery(
    django_capture_on_commit_callbacks: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A redelivered `evaluate_strategy` call means `record_signal` runs again for the same
    evaluation — it must not raise, must not create a second `Signal`, and must still schedule
    dispatch (the gap a naive "only dispatch on the create path" version would have)."""
    dispatched: list[int] = []
    monkeypatch.setattr(
        "cryptovira.apps.signals.tasks.dispatch_notifications.delay",
        lambda signal_id: dispatched.append(signal_id),
    )
    evaluation = _evaluation()

    with django_capture_on_commit_callbacks(execute=True):
        first = record_signal(evaluation)
    with django_capture_on_commit_callbacks(execute=True):
        second = record_signal(evaluation)

    assert first.id == second.id
    assert Signal.objects.filter(evaluation=evaluation).count() == 1
    assert dispatched == [first.id, second.id]


def test_build_message_context_reads_through_to_the_triggering_candle() -> None:
    evaluation = _evaluation()
    strategy = evaluation.strategy
    Candle.objects.create(
        currency=strategy.currency,
        interval=strategy.interval,
        open_time=evaluation.candle_open_time,
        close_time=evaluation.candle_open_time,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("10"),
    )
    signal = Signal.objects.create(evaluation=evaluation)

    context = build_message_context(signal)

    assert context.strategy_name == strategy.name
    assert context.symbol == strategy.currency.symbol
    assert context.close_price == Decimal("100.5")
