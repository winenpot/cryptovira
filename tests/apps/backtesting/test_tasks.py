from __future__ import annotations

import itertools
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cryptovira.apps.accounts.models import User
from cryptovira.apps.backtesting import tasks
from cryptovira.apps.backtesting.models import Backtest, BacktestStatus
from cryptovira.apps.market.models import Candle, Currency, Interval
from cryptovira.apps.strategy.models import Strategy

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

# SMA(1) is just the input value itself, so this triggers on every candle with a positive close —
# deliberately trivial, same trick tests/apps/strategy/test_tasks.py uses.
_SMA_1 = {"indicator": "SMA", "variables": {"timeperiod": 1}}
ALWAYS_TRUE_CONFIG = {"conditions": [{**_SMA_1, "operator": "gt", "value": 0}]}
NEVER_TRUE_CONFIG = {"conditions": [{**_SMA_1, "operator": "gt", "value": 999999}]}

_user_counter = itertools.count()


def _user() -> User:
    email = f"trader{next(_user_counter)}@example.com"
    return User.objects.create_user(email=email, password="pw")


def _currency(symbol: str = "BTCUSDT") -> Currency:
    return Currency.objects.create(symbol=symbol)


def _strategy(currency: Currency, config: Mapping[str, object]) -> Strategy:
    return Strategy.objects.create(
        user=_user(),
        currency=currency,
        interval=Interval.ONE_HOUR,
        name="test",
        config=config,
    )


def _make_growth_candles(currency: Currency, count: int, growth: Decimal = Decimal("1.1")) -> None:
    """`count` hourly candles, each candle's close exactly `growth`x the previous one — so the
    close-to-close forward return between any two consecutive candles is always the same known
    percentage, letting tests assert an exact `total_forward_return`/`win_rate` rather than just
    a sign."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    Candle.objects.bulk_create(
        Candle(
            currency=currency,
            interval=Interval.ONE_HOUR,
            open_time=base + timedelta(hours=i),
            close_time=base + timedelta(hours=i, minutes=59),
            open=(Decimal("100") * growth**i).quantize(Decimal("0.00000001")),
            high=(Decimal("100") * growth**i).quantize(Decimal("0.00000001")),
            low=(Decimal("100") * growth**i).quantize(Decimal("0.00000001")),
            close=(Decimal("100") * growth**i).quantize(Decimal("0.00000001")),
            volume=Decimal("10"),
        )
        for i in range(count)
    )


def test_run_backtest_scores_every_trigger_when_tail_covers_the_horizon(eager_celery: None) -> None:
    """17 candles: 5 warmup, 10 in-range (all trigger), 2 tail — horizon_candles=1 needs only 1
    tail candle, so every in-range trigger is scoreable. Each candle is exactly 10% above the
    last, so every scored trigger has a forward_return of exactly 10.0."""
    currency = _currency()
    _make_growth_candles(currency, count=17)
    strategy = _strategy(currency, ALWAYS_TRUE_CONFIG)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    backtest = Backtest.objects.create(
        strategy=strategy,
        start_time=base + timedelta(hours=5),
        end_time=base + timedelta(hours=15),
        horizon_candles=1,
    )

    tasks.run_backtest.delay(backtest.id)

    backtest.refresh_from_db()
    assert backtest.status == BacktestStatus.COMPLETED
    assert backtest.progress == 100
    assert backtest.trigger_count == 10
    assert backtest.scored_trigger_count == 10
    assert backtest.win_count == 10
    assert backtest.win_rate == pytest.approx(100.0)
    assert backtest.total_forward_return == pytest.approx(100.0, rel=1e-3)


def test_run_backtest_never_triggering_strategy_completes_with_no_results(
    eager_celery: None,
) -> None:
    currency = _currency()
    _make_growth_candles(currency, count=17)
    strategy = _strategy(currency, NEVER_TRUE_CONFIG)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    backtest = Backtest.objects.create(
        strategy=strategy,
        start_time=base + timedelta(hours=5),
        end_time=base + timedelta(hours=15),
    )

    tasks.run_backtest.delay(backtest.id)

    backtest.refresh_from_db()
    assert backtest.status == BacktestStatus.COMPLETED
    assert backtest.trigger_count == 0
    assert backtest.scored_trigger_count == 0
    assert backtest.win_count == 0
    assert backtest.win_rate is None
    assert backtest.total_forward_return is None


def test_run_backtest_excludes_triggers_too_close_to_end_time_from_scoring(
    eager_celery: None,
) -> None:
    """No tail candles at all and horizon_candles=3: the last 3 of 10 in-range triggers can't be
    scored (not enough real future data), but the first 7 can."""
    currency = _currency()
    _make_growth_candles(currency, count=15)  # 5 warmup + 10 in-range, no tail
    strategy = _strategy(currency, ALWAYS_TRUE_CONFIG)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    backtest = Backtest.objects.create(
        strategy=strategy,
        start_time=base + timedelta(hours=5),
        end_time=base + timedelta(hours=15),
        horizon_candles=3,
    )

    tasks.run_backtest.delay(backtest.id)

    backtest.refresh_from_db()
    assert backtest.status == BacktestStatus.COMPLETED
    assert backtest.trigger_count == 10
    assert backtest.scored_trigger_count == 7
    assert backtest.win_count == 7


def test_run_backtest_fails_when_end_time_is_not_after_start_time(eager_celery: None) -> None:
    currency = _currency()
    strategy = _strategy(currency, ALWAYS_TRUE_CONFIG)
    same_time = datetime(2026, 1, 1, tzinfo=UTC)
    backtest = Backtest.objects.create(strategy=strategy, start_time=same_time, end_time=same_time)

    tasks.run_backtest.delay(backtest.id)

    backtest.refresh_from_db()
    assert backtest.status == BacktestStatus.FAILED
    assert "end_time" in backtest.error
    assert backtest.trigger_count is None


def test_run_backtest_fails_when_no_candles_exist_in_range(eager_celery: None) -> None:
    currency = _currency()
    strategy = _strategy(currency, ALWAYS_TRUE_CONFIG)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    backtest = Backtest.objects.create(
        strategy=strategy, start_time=base, end_time=base + timedelta(hours=10)
    )

    tasks.run_backtest.delay(backtest.id)

    backtest.refresh_from_db()
    assert backtest.status == BacktestStatus.FAILED
    assert "no candles ingested" in backtest.error
