"""Backtest execution — a single, on-demand task per `Backtest` row, not the beat-scheduled
fan-out `apps/market`/`apps/strategy`'s periodic tasks use.

Reuses `apps/strategy/engine.py::evaluate` completely unchanged: a backtest is just a different
caller, walking a historical `Candle` range with a rolling window instead of `evaluate_strategy`'s
single "last 200 candles ending now" call — the same window size
(`apps/strategy/tasks.py::HISTORY_CANDLE_COUNT`, imported rather than redefined), so a candle's
warm-up context replaying inside a backtest is identical to what live evaluation would have seen
at that same point in history.

Win rate / total forward return are a side-agnostic forward-return *proxy*, not real position
P&L — see docs/adr/0010-backtest-forward-return-proxy.md for why, and for what this number does
and doesn't mean.

Not idempotent under redelivery the way `ingest_candles`/`evaluate_strategy` are (Steps 3-4): a
redelivered `run_backtest` simply reruns the same deterministic computation and overwrites the
row's own result fields with the same answer — correct and desired for a rerun, not a duplicate
side effect to guard against. No `UniqueConstraint`/`bulk_create(ignore_conflicts=True)` idiom
here for that reason.

No blanket `try/except Exception` around the run: matches every other task in this codebase in
trusting `task_acks_late` redelivery for genuine bugs rather than silently swallowing them into a
`FAILED` row. Only the two *expected*, user-input-shaped failures below (a bad date range, no
ingested candles for the range) get an explicit early return.
"""

from __future__ import annotations

import numpy as np

from cryptovira.apps.backtesting.models import Backtest, BacktestStatus
from cryptovira.apps.market.models import Candle
from cryptovira.apps.strategy.engine import evaluate
from cryptovira.apps.strategy.indicators import InsufficientDataError
from cryptovira.apps.strategy.schema import StrategyConfig
from cryptovira.apps.strategy.tasks import HISTORY_CANDLE_COUNT
from cryptovira.celery import app


@app.task(ignore_result=True)  # type: ignore[untyped-decorator]  # celery is untyped
def run_backtest(backtest_id: int) -> None:
    backtest = Backtest.objects.select_related("strategy", "strategy__currency").get(id=backtest_id)
    strategy = backtest.strategy

    if backtest.end_time <= backtest.start_time:
        backtest.status = BacktestStatus.FAILED
        backtest.error = "end_time must be after start_time"
        backtest.save(update_fields=["status", "error", "updated_at"])
        return

    warmup = list(
        Candle.objects.filter(
            currency=strategy.currency,
            interval=strategy.interval,
            open_time__lt=backtest.start_time,
        ).order_by("-open_time")[:HISTORY_CANDLE_COUNT]
    )
    warmup.reverse()  # ascending chronological order, oldest first

    in_range = list(
        Candle.objects.filter(
            currency=strategy.currency,
            interval=strategy.interval,
            open_time__gte=backtest.start_time,
            open_time__lt=backtest.end_time,
        ).order_by("open_time")
    )
    if not in_range:
        backtest.status = BacktestStatus.FAILED
        backtest.error = (
            f"no candles ingested for {strategy.currency.symbol} {strategy.interval} between "
            f"{backtest.start_time.isoformat()} and {backtest.end_time.isoformat()}"
        )
        backtest.save(update_fields=["status", "error", "updated_at"])
        return

    # Real future candles past end_time, so a trigger near the tail of the range can still be
    # scored against actual data rather than treated as unscoreable purely because it's close to
    # the range boundary.
    tail = list(
        Candle.objects.filter(
            currency=strategy.currency,
            interval=strategy.interval,
            open_time__gte=backtest.end_time,
        ).order_by("open_time")[: backtest.horizon_candles]
    )

    backtest.status = BacktestStatus.RUNNING
    backtest.progress = 0
    backtest.save(update_fields=["status", "progress", "updated_at"])

    series = warmup + in_range + tail
    start_index = len(warmup)
    config = StrategyConfig.model_validate(strategy.config)  # guaranteed valid by full_clean()

    trigger_count = 0
    scored_trigger_count = 0
    win_count = 0
    total_forward_return = 0.0
    # Cap DB writes to ~100 regardless of range size, rather than one per candle (the old
    # system's `backtest.save()`-every-iteration approach) — a multi-thousand-candle range
    # shouldn't cost a multi-thousand-row write pattern just to report progress.
    update_every = max(1, len(in_range) // 100)

    for offset, i in enumerate(range(start_index, start_index + len(in_range))):
        # Rolling last-HISTORY_CANDLE_COUNT window ending at candle i — not an ever-growing
        # array — so this matches exactly what evaluate_strategy would have seen as "now" at
        # this point in history, and stays cheap over a long date range.
        window = series[max(0, i - HISTORY_CANDLE_COUNT + 1) : i + 1]
        close = np.array([float(candle.close) for candle in window], dtype=float)
        try:
            triggered = evaluate(config, close)
        except InsufficientDataError:
            triggered = False

        if triggered:
            trigger_count += 1
            forward_index = i + backtest.horizon_candles
            if forward_index < len(series):
                entry_close = float(series[i].close)
                exit_close = float(series[forward_index].close)
                forward_return = (exit_close - entry_close) / entry_close * 100
                total_forward_return += forward_return
                scored_trigger_count += 1
                if forward_return > 0:
                    win_count += 1
            # else: trigger too close to end_time to have horizon_candles of real forward data —
            # counted in trigger_count but deliberately excluded from scored_trigger_count/
            # win_rate rather than fabricating a return from data that doesn't exist.

        if (offset + 1) % update_every == 0 or offset + 1 == len(in_range):
            backtest.progress = (offset + 1) * 100 // len(in_range)
            backtest.save(update_fields=["progress", "updated_at"])

    backtest.status = BacktestStatus.COMPLETED
    backtest.progress = 100
    backtest.trigger_count = trigger_count
    backtest.scored_trigger_count = scored_trigger_count
    backtest.win_count = win_count
    backtest.win_rate = win_count / scored_trigger_count * 100 if scored_trigger_count else None
    backtest.total_forward_return = total_forward_return if scored_trigger_count else None
    backtest.save(
        update_fields=[
            "status",
            "progress",
            "trigger_count",
            "scored_trigger_count",
            "win_count",
            "win_rate",
            "total_forward_return",
            "updated_at",
        ]
    )
