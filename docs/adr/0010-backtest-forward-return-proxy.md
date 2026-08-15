# ADR 0010 — Backtest results as a side-agnostic forward-return proxy

**Status:** Accepted · 2026-08-14

## Context

Step 5.5 (not in the original 8-step plan — noticed missing during Step 5 planning) needs to
replay a `Strategy` against historical `Candle` data and report a results summary, reusing
`apps/strategy/engine.py::evaluate` unchanged. `old-version/core/apps/market/models/backtest.py`
and `old-version/brokers/binance/tasks/backtest.py` are the behavioural spec, not the schema to
copy verbatim — and the gap between them is real, not cosmetic:

- The old backtest's `total_r_r`/`result` (win rate) came from simulating an actual trade per
  trigger: a `side` (`BUY`/`SELL`), a `stop_loss_threshold`, fibonacci-level take-profit prices, a
  `user_risk_reward` cutoff, all read off `strategy.data` and a bound `BinanceProfile` for
  position sizing.
- None of that exists in this codebase. `StrategyConfig` (`apps/strategy/schema.py`, ADR 0008) is
  a flat, side-agnostic AND-chain of `indicator`/`operator`/`value` conditions. It has no notion
  of a trade at all — a triggered condition means "this logical expression is currently true,"
  not "go long here with this stop and this target." Broker execution (order/position modelling)
  is Step 6, not yet built.

Reproducing the old `total_r_r` exactly would mean pulling stop-loss/take-profit/side fields into
`StrategyConfig` two steps ahead of the roadmap's own ordering, entangling Step 4's pure
condition-evaluation schema with Step 6's not-yet-designed position model. Dropping win-rate/R:R
entirely was the other option on the table, deferring all backtest economics until Step 6 ships.

## Decision

**A forward-return proxy, computed independently of any notion of side.** For every candle where
`evaluate()` returns `True`, look forward `Backtest.horizon_candles` candles and compute the
close-to-close percentage move: `(exit_close - entry_close) / entry_close * 100`. A "win" is a
positive forward return; `Backtest.total_forward_return` is the sum of forward returns over every
*scored* trigger (see below); `Backtest.win_rate` is `win_count / scored_trigger_count * 100`.

This number is explicitly **not** real position P&L. It answers "after this condition became
true, did price move up over the next N candles?" — nothing about whether a real trader would
have opened a long or a short here, what stop would have been hit first intraday, or what size
they'd have risked. A momentum-style condition (e.g. "RSI crosses above 70") and a
mean-reversion-style condition (e.g. "RSI crosses below 30") are scored by the identical rule,
even though a real strategy author very plausibly intends opposite positions for the two. The
proxy is deliberately blind to that intent because `StrategyConfig` currently has nowhere to
express it.

**`scored_trigger_count` is tracked separately from `trigger_count`.** A trigger within
`horizon_candles` of `end_time` may not have `horizon_candles` of *real* future candle data to
measure a return over. Rather than substitute a synthetic value (zero, or an average of other
triggers) for the missing forward candle, that trigger is counted in `trigger_count` but excluded
from `scored_trigger_count`/`win_rate`/`total_forward_return` — the same "don't fabricate a result
from data that doesn't exist" principle `InsufficientDataError` already applies to live evaluation
(ADR 0008), applied here to the tail of a date range instead of the front of a candle history.

**Replay reuses `evaluate()` unchanged, via a rolling window matching live evaluation exactly.**
`apps/backtesting/tasks.py::run_backtest` walks every in-range candle and, for each one, builds
the same shape of input `evaluate_strategy` (`apps/strategy/tasks.py`) builds for "now": the last
`HISTORY_CANDLE_COUNT` (200) candles ending at that point, as a plain `numpy` array — imported
from `apps/strategy/tasks.py`, not redefined, so the two paths can't silently drift apart. A
backtest is a different *caller* of `evaluate()`, not a reason to touch the pure evaluation layer
at all, exactly as the roadmap specifies.

**A dedicated `backtesting` Celery queue**, not `strategy`. A backtest over a long date range is a
genuinely heavy, long-running task (potentially thousands of rolling-window evaluations); sharing
the `strategy` queue would risk a live, time-sensitive `evaluate_strategy` tick queuing up behind
one. Same reasoning `orders` already gets its own queue for.

**No `strategy_json` config snapshot column**, unlike the old model. `StrategyEvaluation` already
established the precedent (ADR 0008 area): a completed audit/result row means "what happened when
this ran," not a live-reinterpreted reference to a config that might have since changed. A
`Backtest` row's stored results stay correct even if `Strategy.config` is edited afterward.

## Consequences

- **Backtest results are honestly a proxy, not a backtest of an actual trading strategy's P&L.**
  This is stated in the model's own docstring and this ADR, not left implicit. A user comparing
  two strategies' `win_rate` is comparing "how often did price move favourably afterward,"
  side-agnostically — genuinely useful signal for iterating on a condition, but not a substitute
  for what Step 6 will eventually be able to simulate once real order/position data exists.
- `horizon_candles` is a per-`Backtest` field, not a fixed constant — different strategies (a
  scalping 1m condition vs. a 1d swing condition) reasonably want different forward-looking
  windows, and nothing here assumes one horizon fits every strategy.
- `run_backtest` is **not** idempotent under redelivery the way `ingest_candles`/`evaluate_strategy`
  are (Steps 3-4). A redelivered run recomputes the same deterministic result and overwrites the
  same row — correct and desired behaviour for a rerun, not a duplicate side effect needing a
  `UniqueConstraint`/`bulk_create(ignore_conflicts=True)` guard. There is intentionally no new
  idempotency mechanism introduced by this step.
- No CSV/report-file generation carried forward from the old system's `Backtest.file`/
  `csv_content` — no concrete consumer for it in this codebase yet, and the result fields
  (`trigger_count`, `win_rate`, `total_forward_return`) are queryable directly.

## We would revisit if

Step 6 ships a real order/position model. At that point, backtesting should grow a second, real
P&L mode that simulates an actual position (entry, stop, target, size) per trigger, superseding
this proxy for any strategy that has enough config to support it — while this forward-return proxy
likely stays available as a fast, side-agnostic first pass for a condition that hasn't been given
trade-sizing parameters yet.
