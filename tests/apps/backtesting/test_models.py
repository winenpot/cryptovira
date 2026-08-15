from __future__ import annotations

from datetime import UTC, datetime

import pytest

from cryptovira.apps.accounts.models import User
from cryptovira.apps.backtesting.models import Backtest, BacktestStatus
from cryptovira.apps.market.models import Currency, Interval
from cryptovira.apps.strategy.models import Strategy

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

_ALWAYS_TRUE_CONFIG = {
    "conditions": [
        {"indicator": "SMA", "variables": {"timeperiod": 1}, "operator": "gt", "value": 0}
    ]
}


def test_backtest_str() -> None:
    user = User.objects.create_user(email="trader@example.com", password="pw")
    currency = Currency.objects.create(symbol="BTCUSDT")
    strategy = Strategy.objects.create(
        user=user,
        currency=currency,
        interval=Interval.ONE_HOUR,
        name="my strategy",
        config=_ALWAYS_TRUE_CONFIG,
    )
    backtest = Backtest.objects.create(
        strategy=strategy,
        start_time=datetime(2026, 1, 1, tzinfo=UTC),
        end_time=datetime(2026, 1, 2, tzinfo=UTC),
    )

    assert str(backtest) == "my strategy 2026-01-01->2026-01-02 (pending)"
    assert backtest.status == BacktestStatus.PENDING
