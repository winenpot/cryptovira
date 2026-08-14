from __future__ import annotations

import itertools
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from cryptovira.apps.accounts.models import User
from cryptovira.apps.market.models import Candle, Currency, Interval
from cryptovira.apps.signals.models import Signal
from cryptovira.apps.strategy import tasks
from cryptovira.apps.strategy.models import Strategy, StrategyEvaluation

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

# A strategy that triggers whenever the latest close is above 0 — deliberately trivial so tests
# only need a handful of candles, not a real warm-up window.
_SMA_1 = {"indicator": "SMA", "variables": {"timeperiod": 1}}
ALWAYS_TRUE_CONFIG = {"conditions": [{**_SMA_1, "operator": "gt", "value": 0}]}
NEVER_TRUE_CONFIG = {"conditions": [{**_SMA_1, "operator": "gt", "value": 999999}]}
NEEDS_MORE_DATA_CONFIG = {
    "conditions": [
        {"indicator": "SMA", "variables": {"timeperiod": 50}, "operator": "gt", "value": 0}
    ]
}


_user_counter = itertools.count()


def _user() -> User:
    email = f"trader{next(_user_counter)}@example.com"
    return User.objects.create_user(email=email, password="pw")


def _currency(symbol: str = "BTCUSDT") -> Currency:
    return Currency.objects.create(symbol=symbol)


def _strategy(currency: Currency, config: Mapping[str, object], **overrides: object) -> Strategy:
    defaults: dict[str, object] = {
        "user": _user(),
        "currency": currency,
        "interval": Interval.ONE_HOUR,
        "name": "test",
        "config": config,
    }
    defaults.update(overrides)
    return Strategy.objects.create(**defaults)


def _make_candles(currency: Currency, count: int) -> None:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    Candle.objects.bulk_create(
        Candle(
            currency=currency,
            interval=Interval.ONE_HOUR,
            open_time=base + timedelta(hours=i),
            close_time=base + timedelta(hours=i, minutes=59),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("10"),
        )
        for i in range(count)
    )


def test_evaluate_strategy_writes_a_triggered_row(eager_celery: None) -> None:
    currency = _currency()
    _make_candles(currency, 5)
    strategy = _strategy(currency, ALWAYS_TRUE_CONFIG)

    tasks.evaluate_strategy.delay(strategy.id)

    evaluation = StrategyEvaluation.objects.get(strategy=strategy)
    assert evaluation.triggered is True
    assert evaluation.error == ""


def test_evaluate_strategy_writes_a_not_triggered_row(eager_celery: None) -> None:
    currency = _currency()
    _make_candles(currency, 5)
    strategy = _strategy(currency, NEVER_TRUE_CONFIG)

    tasks.evaluate_strategy.delay(strategy.id)

    evaluation = StrategyEvaluation.objects.get(strategy=strategy)
    assert evaluation.triggered is False
    assert evaluation.error == ""


def test_evaluate_strategy_writes_an_error_row_on_insufficient_data(eager_celery: None) -> None:
    currency = _currency()
    _make_candles(currency, 5)  # far fewer than the 50-period SMA needs
    strategy = _strategy(currency, NEEDS_MORE_DATA_CONFIG)

    tasks.evaluate_strategy.delay(strategy.id)

    evaluation = StrategyEvaluation.objects.get(strategy=strategy)
    assert evaluation.triggered is False
    assert evaluation.error != ""


def test_evaluate_strategy_writes_nothing_when_no_candles_exist(eager_celery: None) -> None:
    currency = _currency()
    strategy = _strategy(currency, ALWAYS_TRUE_CONFIG)

    tasks.evaluate_strategy.delay(strategy.id)

    assert StrategyEvaluation.objects.filter(strategy=strategy).count() == 0


def test_evaluate_strategy_is_idempotent_under_redelivery(eager_celery: None) -> None:
    """The concrete idempotency assertion the roadmap calls for, mirrored from
    `test_ingest_candles_is_idempotent_under_redelivery`: evaluating the same strategy twice
    against the same latest candle must not create a duplicate row or raise."""
    currency = _currency()
    _make_candles(currency, 5)
    strategy = _strategy(currency, ALWAYS_TRUE_CONFIG)

    tasks.evaluate_strategy.delay(strategy.id)
    tasks.evaluate_strategy.delay(strategy.id)  # does not raise on the repeated row

    assert StrategyEvaluation.objects.filter(strategy=strategy).count() == 1


def test_evaluate_strategy_records_a_signal_when_triggered(eager_celery: None) -> None:
    """Step 5's entry point into Step 4's task: a triggered evaluation must result in exactly
    one `Signal` — see apps/signals/services.py::record_signal for the transaction/idempotency
    mechanics; this test is the cross-app proof that evaluate_strategy actually calls it."""
    currency = _currency()
    _make_candles(currency, 5)
    strategy = _strategy(currency, ALWAYS_TRUE_CONFIG)

    tasks.evaluate_strategy.delay(strategy.id)

    evaluation = StrategyEvaluation.objects.get(strategy=strategy)
    assert Signal.objects.filter(evaluation=evaluation).count() == 1


def test_evaluate_strategy_does_not_record_a_signal_when_not_triggered(eager_celery: None) -> None:
    currency = _currency()
    _make_candles(currency, 5)
    strategy = _strategy(currency, NEVER_TRUE_CONFIG)

    tasks.evaluate_strategy.delay(strategy.id)

    assert Signal.objects.count() == 0


def test_evaluate_strategy_redelivery_still_yields_exactly_one_signal(
    eager_celery: None, django_capture_on_commit_callbacks: Any
) -> None:
    """The full cross-app idempotency chain, not just `StrategyEvaluation`'s own: redelivering
    the whole `evaluate_strategy` task — the realistic failure this codebase designs around,
    per `task_acks_late` — must still land exactly one `Signal`, and still (re-)schedule
    notification dispatch both times (see record_signal's own redelivery test for why that's
    deliberate, not a bug)."""
    currency = _currency()
    _make_candles(currency, 5)
    strategy = _strategy(currency, ALWAYS_TRUE_CONFIG)

    with django_capture_on_commit_callbacks(execute=True):
        tasks.evaluate_strategy.delay(strategy.id)
    with django_capture_on_commit_callbacks(execute=True):
        tasks.evaluate_strategy.delay(strategy.id)  # redelivered

    evaluation = StrategyEvaluation.objects.get(strategy=strategy)
    assert Signal.objects.filter(evaluation=evaluation).count() == 1


def test_fan_out_evaluate_strategies_dispatches_only_active_matching_interval(
    eager_celery: None,
) -> None:
    currency = _currency()
    _make_candles(currency, 5)
    matching = _strategy(currency, ALWAYS_TRUE_CONFIG, name="matching")
    _strategy(currency, ALWAYS_TRUE_CONFIG, name="wrong interval", interval=Interval.ONE_DAY)
    _strategy(currency, ALWAYS_TRUE_CONFIG, name="inactive", is_active=False)

    tasks.fan_out_evaluate_strategies.delay("1h")

    assert StrategyEvaluation.objects.filter(strategy=matching).exists()
    assert StrategyEvaluation.objects.count() == 1
