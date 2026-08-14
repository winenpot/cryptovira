"""Message content. No Django imports — mirrors `apps/strategy/engine.py`'s purity: this module
only knows how to turn a plain value into text, never how to fetch one.

`SignalMessageContext` is the seam, the same role `Kline` plays for market data (Step 3): the
Django-touching assembly (FK traversal, a `Candle` lookup for the close price) lives in
`services.py::build_message_context`, so this module stays testable with a hand-built value and
no database.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import NamedTuple


class SignalMessageContext(NamedTuple):
    strategy_name: str
    symbol: str
    interval: str
    candle_open_time: datetime
    close_price: Decimal


def render_signal_message(context: SignalMessageContext) -> str:
    return (
        f"Signal: {context.strategy_name}\n"
        f"{context.symbol} ({context.interval})\n"
        f"Candle {context.candle_open_time.isoformat()} closed at {context.close_price}"
    )
