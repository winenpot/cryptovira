"""Django-touching orchestration that isn't a model method and isn't a Celery task.

`record_signal` doesn't belong in `models.py` (definitions, not orchestration) and can't be a
task itself — see docs/interview/05-concurrency-and-correctness.md, section C: it must run
*inline*, in the same process and transaction as `apps/strategy/tasks.py::evaluate_strategy`,
so that `transaction.on_commit` can defer notification dispatch until the `Signal` row it
depends on has actually committed.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction

from cryptovira.apps.market.models import Candle
from cryptovira.apps.signals.messages import SignalMessageContext
from cryptovira.apps.signals.models import Signal
from cryptovira.apps.strategy.models import StrategyEvaluation


def record_signal(evaluation: StrategyEvaluation) -> Signal:
    """Create the `Signal` for a triggered evaluation, or return the existing one if this is a
    redelivered `evaluate_strategy` call. Either way, (re-)schedules notification dispatch —
    see the module 05 interview notes for why that has to happen unconditionally, not just on
    the "just created" path.
    """
    # Local import: tasks.py needs build_message_context (below) at module load time, so a
    # top-level import here would be circular. By the time record_signal is actually *called*,
    # both modules are fully loaded — this is the standard way to break a two-file Celery
    # task/service cycle, not a workaround for a design mistake.
    from cryptovira.apps.signals.tasks import dispatch_notifications

    try:
        with transaction.atomic():
            signal = Signal.objects.create(evaluation=evaluation)
    except IntegrityError:
        signal = Signal.objects.get(evaluation=evaluation)
    transaction.on_commit(lambda: dispatch_notifications.delay(signal.id))
    return signal


def build_message_context(signal: Signal) -> SignalMessageContext:
    evaluation = signal.evaluation
    strategy = evaluation.strategy
    candle = Candle.objects.get(
        currency=strategy.currency,
        interval=strategy.interval,
        open_time=evaluation.candle_open_time,
    )
    return SignalMessageContext(
        strategy_name=strategy.name,
        symbol=strategy.currency.symbol,
        interval=strategy.interval,
        candle_open_time=candle.open_time,
        close_price=candle.close,
    )
