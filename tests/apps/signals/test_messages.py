"""No `integration` marker: pure computation, no database — `SignalMessageContext` is
hand-built, exactly like `apps/strategy`'s pure-layer tests build plain `numpy` arrays."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cryptovira.apps.signals.messages import SignalMessageContext, render_signal_message


def test_render_signal_message_includes_the_key_facts() -> None:
    context = SignalMessageContext(
        strategy_name="RSI oversold",
        symbol="BTCUSDT",
        interval="1h",
        candle_open_time=datetime(2026, 1, 1, tzinfo=UTC),
        close_price=Decimal("42000.50"),
    )

    message = render_signal_message(context)

    assert "RSI oversold" in message
    assert "BTCUSDT" in message
    assert "1h" in message
    assert "42000.50" in message
