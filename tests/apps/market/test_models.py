from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from cryptovira.apps.market.models import Candle, Currency, Interval

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def _candle_kwargs(currency: Currency, **overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = {
        "currency": currency,
        "interval": Interval.ONE_MINUTE,
        "open_time": datetime(2026, 1, 1, tzinfo=UTC),
        "close_time": datetime(2026, 1, 1, 0, 1, tzinfo=UTC),
        "open": Decimal("100"),
        "high": Decimal("101"),
        "low": Decimal("99"),
        "close": Decimal("100.5"),
        "volume": Decimal("10"),
    }
    defaults.update(overrides)
    return defaults


def test_str_is_the_symbol() -> None:
    currency = Currency.objects.create(symbol="BTCUSDT")

    assert str(currency) == "BTCUSDT"


def test_symbol_uniqueness_is_a_real_database_constraint() -> None:
    """Mirrors `test_email_uniqueness_is_a_real_database_constraint` in the accounts app: the
    old system's `Currency.slug` was `unique=False` "because of future market" — proving this
    is a DB-level constraint, not just application-level validation, is what actually closes
    that gap."""
    Currency.objects.create(symbol="BTCUSDT")

    with pytest.raises(IntegrityError), transaction.atomic():
        Currency.objects.create(symbol="BTCUSDT")


def test_candle_uniqueness_is_a_real_database_constraint() -> None:
    """The idempotency mechanism the roadmap calls for: a redelivered ingest task re-attempting
    the same (currency, interval, open_time) must be rejected by the database, not merely
    avoided by application logic."""
    currency = Currency.objects.create(symbol="BTCUSDT")
    Candle.objects.create(**_candle_kwargs(currency))

    with pytest.raises(IntegrityError), transaction.atomic():
        Candle.objects.create(**_candle_kwargs(currency))


def test_candle_uniqueness_is_scoped_to_currency_and_interval() -> None:
    """The same open_time is fine for a different currency, or a different interval on the
    same currency — the constraint is on the triple, not `open_time` alone."""
    btc = Currency.objects.create(symbol="BTCUSDT")
    eth = Currency.objects.create(symbol="ETHUSDT")
    Candle.objects.create(**_candle_kwargs(btc))

    # Different currency, same interval/open_time.
    Candle.objects.create(**_candle_kwargs(eth))
    # Same currency, different interval.
    Candle.objects.create(**_candle_kwargs(btc, interval=Interval.FIVE_MINUTES))

    assert Candle.objects.count() == 3


def test_deleting_a_currency_with_candles_is_protected() -> None:
    """`on_delete=PROTECT`: currencies are decommissioned via `is_active=False`, never deleted —
    an accidental `.delete()` must fail loudly instead of silently erasing candle history."""
    currency = Currency.objects.create(symbol="BTCUSDT")
    Candle.objects.create(**_candle_kwargs(currency))

    with pytest.raises(ProtectedError):
        currency.delete()
