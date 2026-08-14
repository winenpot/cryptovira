# Notes on the old system (`old-version/`)

Reference material for porting. Nothing here is maintained, imported, or run. Paths are relative
to `old-version/`.

## Shape

A Django monolith ("Cryptovira" / "Markepto") plus two side services:

- `core/` — the Django project. Split settings (`base` / `development` / `production` / `aws`) with
  hardcoded secrets in `base.py`; `core/urls/api.py` mounted at `/v1/` aggregating each app's
  `api/urls.py` (DRF, `NamespaceVersioning`, `drf-spectacular`).
- `core/algorithms/` — the part worth reading closely: pure technical analysis, decoupled from
  Django. `indicators.py` (candlestick patterns, OBV/AD/ADOSC/volume), `operators.py` (crossovers,
  RSI divergence, pattern matching), `strategy.py` (MACD, position sizing, risk maths).
  `core/apps/market/constants.py` wires these into `INDICATOR_MAPPER` / `OPERATOR_MAPPER` /
  `VOLUME_INDICATORS`, which strategy JSON configs reference **by name**.
- `core/apps/` — `account` (custom `User`, referral codes, Telegram/SMS senders as raw `requests`
  calls), `market` (`Strategy`, `Signal`, `Currency`, `Order`, `Backtest`, `Watchlist`,
  `StrategyLog`), `payment` (`Plan`/`PlanUser`, `Discount`, `ReferralPrize`, Cryptomus + BlockBee
  gateways), plus `message`, `notifications`, `blog`, `preferences`.
- `brokers/binance/` — execution: `BinanceProfile` (per-user API key/secret, stored in plain
  columns), `tasks/intervals.py` (beat fan-out per timeframe), `tasks/trade.py` (evaluation and
  order placement).
- `binance/` — a vendored 2019 fork of `python-binance`, imported as `binance.client`.
- `coingecko/` — market-cap ingestion app.
- `crypto-price/` (cryptofeed-based price streamer) and `telegram_server/` (standalone bot scripts)
  ran outside Django and duplicated logic that also existed inside it.

## The flow to reproduce

1. `watch_requested_strategy(time_interval)` runs per interval on beat, pulls active `Strategy`
   rows for that interval, and fans out with `celery.group`.
2. `check_for_available_position(strategy, currency)` pulls candles, evaluates the strategy's
   configured indicators/operators against a dataframe, and on trigger calls
   `Signal.objects.create_signal_from_strategy(...)`.
3. `Signal` computes trade details (entry, stop, targets, sizing), renders a message from
   `Plan.template`, and fans out by subscription tier — Bronze→bot 2, Silver→bot 3, Gold→bot 4,
   Platinum→bot 5 — plus optional SMS and a webhook.
4. `StrategyLog` records every evaluation, success or failure. This was the only observability.

## Known defects to not reproduce

- Secrets in source control (`core/settings/base.py`), broker API keys unencrypted at rest.
- No tests anywhere; every `tests.py` is the Django stub.
- Celery beat schedule written into DB rows from a `beat_init` handler — live schedule could drift
  from the repo silently.
- No idempotency on signal creation or order placement; a redelivered task could double-fire.
- `devops/migration-fixer.sh` and `devops/nuclear_fresh_start.sh` exist because the migration
  graph broke badly enough to need recovery scripts.
- Business logic in models and views (`Signal` owned messaging, notification fan-out, *and* trade
  maths), so nothing could be tested without a database.

## What is worth porting nearly verbatim

The algorithm layer. `core/algorithms/*` is pure functions over price series; it carries the
domain knowledge that is expensive to re-derive. Port it with tests attached, and decide the
TA-Lib question (bundled wheels now exist) in its own ADR at roadmap step 4.
