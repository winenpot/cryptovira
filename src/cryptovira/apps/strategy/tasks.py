"""Strategy evaluation. Two tasks, mirroring `apps/market/tasks.py`'s fan-out shape exactly:

- `fan_out_evaluate_strategies` runs on a beat schedule, one entry per interval cadence, timed a
  few minutes after that interval's `market-ingest-*` entry so the candle it needs has actually
  landed (see `cryptovira.celery`). It dispatches one `evaluate_strategy` per active `Strategy`
  matching that interval via `group()`, so one strategy's failure/redelivery stays isolated.
- `evaluate_strategy` writes with `bulk_create([...], ignore_conflicts=True)`, relying on
  `StrategyEvaluation`'s `UniqueConstraint(strategy, candle_open_time)` — the same
  redelivery-safe idiom `ingest_candles` already established, reused rather than reinvented.
"""

from __future__ import annotations

from typing import Final

import numpy as np
from celery import group

from cryptovira.apps.market.models import Candle
from cryptovira.apps.strategy.engine import evaluate
from cryptovira.apps.strategy.indicators import InsufficientDataError
from cryptovira.apps.strategy.models import Strategy, StrategyEvaluation
from cryptovira.apps.strategy.schema import StrategyConfig
from cryptovira.celery import app

#: Comfortably covers this app's slowest indicator warm-up (MACD's default ~35 candles) and
#: matches the old system's own sample strategy configs (`"count": 200`). Not a per-strategy
#: config field — nothing has asked for tuning it yet.
HISTORY_CANDLE_COUNT: Final[int] = 200


@app.task(ignore_result=True)  # type: ignore[untyped-decorator]  # celery is untyped
def fan_out_evaluate_strategies(interval: str) -> None:
    strategy_ids = list(
        Strategy.objects.filter(is_active=True, interval=interval).values_list("id", flat=True)
    )
    group(evaluate_strategy.s(strategy_id) for strategy_id in strategy_ids)()


@app.task(ignore_result=True)  # type: ignore[untyped-decorator]  # celery is untyped
def evaluate_strategy(strategy_id: int) -> None:
    strategy = Strategy.objects.select_related("currency").get(id=strategy_id)
    candles = list(
        Candle.objects.filter(currency=strategy.currency, interval=strategy.interval).order_by(
            "-open_time"
        )[:HISTORY_CANDLE_COUNT]
    )
    if not candles:
        # Nothing ingested yet for this (currency, interval) — no real candle exists to key an
        # audit row on, so there is nothing to record. Distinct from "candles exist but too few
        # for warm-up," which does write a row (below).
        return
    candles.reverse()  # ascending chronological order, oldest first

    close = np.array([float(candle.close) for candle in candles], dtype=float)
    config = StrategyConfig.model_validate(strategy.config)  # guaranteed valid by full_clean()

    try:
        triggered, error = evaluate(config, close), ""
    except InsufficientDataError as exc:
        triggered, error = False, str(exc)

    StrategyEvaluation.objects.bulk_create(
        [
            StrategyEvaluation(
                strategy=strategy,
                candle_open_time=candles[-1].open_time,
                triggered=triggered,
                error=error,
            )
        ],
        ignore_conflicts=True,
    )
