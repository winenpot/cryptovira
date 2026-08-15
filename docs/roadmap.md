# Rewrite roadmap

The old system worked, but it was undocumented, untested, and pinned to a 2019 toolchain. The
rewrite reproduces its *behaviour*, not its *structure*, one reviewable step at a time.

Rules for every step: it ends with the suite green, `mypy` clean, an ADR for any non-obvious
decision, and an interview module in [`interview/`](interview/) covering the concepts it introduced.

---

## Step 1 — Foundation ✅ done

Runnable, typed, tested, containerised skeleton. No domain code.

- uv + `pyproject.toml` + committed `uv.lock`; Python 3.14 pinned in `.python-version`
- Django 6.1 with a **single** settings module fed by typed `pydantic-settings` config
- Postgres 18, RabbitMQ 4 (Celery broker), Redis 8 (cache only) via `compose.yaml`
- Multi-stage Dockerfile, non-root runtime, one image with `web` / `worker` / `beat` roles
- `/healthz` + `/readyz`, structlog JSON logging, DRF + drf-spectacular mounted at `/api/v1/`
- Ruff, mypy (strict), pytest, pre-commit with gitleaks; GitHub Actions CI/CD

## Step 2 — Accounts and API surface ✅ done

Thin identity model, JWT auth, and the API surface to register/login/refresh/logout/view-profile.
Everything Telegram/referral/payment-shaped from the old `User` model stays out — see
[ADR 0005](adr/0005-custom-user-model.md).

- Custom `User` (`accounts.User`): `AbstractBaseUser` + `PermissionsMixin`, email as
  `USERNAME_FIELD` with a real DB-level `unique=True`, `uuid` as the public identifier
- JWT via `djangorestframework-simplejwt`: short-lived access tokens, rotating refresh tokens
  with blacklisting on rotation and on explicit logout
- `register/`, `token/`, `token/refresh/`, `token/verify/`, `logout/`, `me/` — scoped throttles
  on `register`/`token` (separate from the global anon rate); OpenAPI schema already covers them
  via drf-spectacular, nothing extra needed
- 53 tests: manager/model unit tests, full auth-flow integration tests (register → login →
  refresh → logout, including that a *blacklisted refresh token* still leaves the already-issued
  *access token* valid until it expires — the concrete shape of "JWT revocation is hard")

## Step 3 — Market data domain ✅ done

`Currency`/`Candle` models, an exchange client behind a `Protocol` interface, and an idempotent
Celery ingest task — real Postgres storage where the old system had none. See
[ADR 0007](adr/0007-market-data-source-interface.md).

- `Currency` (thin: symbol, name, `is_active`) and `Candle` (OHLCV as `Decimal`, UTC-aware
  `open_time`/`close_time`); one canonical `Interval` enum replacing the old system's two
  divergent timeframe representations
- `Candle.UniqueConstraint(currency, interval, open_time)` is the actual idempotency mechanism —
  `ingest_candles` writes via `bulk_create(..., ignore_conflicts=True)`, safe under Celery's
  `task_acks_late` redelivery; `on_delete=PROTECT` keeps an accidental `Currency` delete from
  silently erasing candle history
- `MarketDataSource` (`typing.Protocol`, the first interface in this codebase), implemented by a
  thin project-owned `httpx` client against Binance's public REST klines endpoint — no vendored
  fork, no `python-binance` dependency
- 13 new tests: model constraints, response-parsing against Binance's documented kline shape via
  `httpx.MockTransport`, and task idempotency (redelivery produces no duplicate rows); along the
  way, found and fixed a real bug in the shared `eager_celery` test fixture (a Celery
  config-key prefix resolution gotcha that silently no-op'd `task_always_eager`) — see
  [interview module 03](interview/03-data-modelling-and-the-orm.md)

## Step 4 — Strategy engine ✅ done

Pure indicator/operator functions, a `pydantic`-validated `Strategy.config`, and an idempotent
evaluation task that writes an audit row every run — deliberately not carrying forward the old
system's three overlapping indicator dispatchers or its undocumented edge-triggered comparison
operators. Signal creation stays out of scope; that's step 5. See
[ADR 0008](adr/0008-strategy-config-validation.md).

- ~~The TA-Lib decision (bundled wheels vs a pure-Python implementation) gets its own ADR~~ done
  early — [ADR 0006](adr/0006-ta-lib-packaging.md): `ta-lib` installs as a prebuilt wheel with the
  C library bundled in, no compiler needed on any target platform, verified in `tests/test_talib.py`.
- `apps/strategy/{indicators,operators,schema,engine}.py` — zero Django imports: a typed `dict`
  registry for `SMA`/`EMA`/`RSI`/`MACD` (replacing the old system's two overlapping dispatchers),
  explicit level (`gt`/`lt`/`eq`) vs. edge (`crosses_above`/`crosses_below`) operators (replacing
  its undocumented behavior where a level-looking config key silently also checked the previous
  candle), and a `pydantic` `StrategyConfig`/`Condition` schema (`extra="forbid"`, AND-chained
  conditions matching the old system's *actual*, if undocumented, semantics)
- `Strategy.save()` always calls `full_clean()` — the one model in this codebase that pays that
  cost on every save, because an invalid config would otherwise silently break every future
  evaluation run rather than fail at the point of authorship
- `StrategyEvaluation.UniqueConstraint(strategy, candle_open_time)` + `bulk_create(...,
  ignore_conflicts=True)` — the same redelivery-safe idiom `Candle`'s constraint already
  established, reused rather than reinvented; a new `strategy` Celery queue, beat-scheduled a few
  minutes after each interval's `market-ingest-*` entry so the candle it needs has landed first
- 32 new tests (21 pure — no `django_db`, no `integration` marker — plus 11 integration, including
  the redelivery-idempotency case); manually verified end-to-end against the real `BTCUSDT`
  candles ingested in step 3 — see [interview module 04](interview/04-strategy-engine.md)

## Step 5 — Signals and notifications ✅ done

`Signal` creation reuses `StrategyEvaluation`'s own idempotency rather than duplicating it,
`transaction.on_commit` gates notification dispatch on the row actually being durable, and
`send_notification` is the first task needing Celery's task-level retry on top of the
broker-level redelivery every task since step 3 already had. See
[ADR 0009](adr/0009-signal-idempotency-and-notification-delivery.md).

- `Signal.evaluation` is a `OneToOneField(StrategyEvaluation)` — inherits ADR 0008's
  `(strategy, candle_open_time)` uniqueness transitively instead of a second constraint;
  `record_signal()` (a plain function, not a task, called inline from `evaluate_strategy`) wraps
  creation in its own `atomic()` savepoint and always calls `transaction.on_commit(...)` after —
  including on the "already recorded" redelivery path, closing a silent-no-dispatch gap a naive
  version would have
- `NotificationRecipient` (Telegram/webhook destination per user) is the model ADR 0005 deferred
  all the way back in step 2; `NotificationDelivery` is the first model here where
  `TimestampedModel`'s `updated_at` reflects the system itself mutating a row across retries, not
  a human editing config
- `send_notification`: explicit `bind=True` + `self.retry(...)`, not `autoretry_for` — deliberately
  legible over automatic. Manual verification against the real running stack caught a genuine bug
  this shape invites: `retry_backoff`/`retry_backoff_max`/`retry_jitter` are only auto-applied by
  `autoretry_for`'s wrapper, so the first version silently retried at a flat 180s every time;
  fixed by computing the countdown with Celery's own `get_exponential_backoff_interval`, the same
  function `autoretry_for` calls internally. Once `max_retries` is exhausted, writes
  `NotificationDelivery.status = FAILED` — a Postgres-visible, admin-actionable dead letter,
  not a RabbitMQ DLX (a named, deliberate scope cut, not an oversight)
- "Fan-out per plan tier" honestly degrades to "the strategy's owning user" — no `Plan` model
  exists yet (step 7); `TelegramChannel`/`WebhookChannel` are thin `httpx` clients reusing the
  ADR-0007 precedent, `SMS` deliberately has no channel value (no chosen provider, would be dead
  code)
- 21 new tests (channels' request/response shape via `httpx.MockTransport`, `record_signal`'s
  transaction/idempotency behavior via pytest-django's `django_capture_on_commit_callbacks` — a
  real testing gotcha in its own right, since `on_commit` callbacks never fire in a normal rolled-
  back test transaction — and `send_notification`'s retry-then-dead-letter path); manually
  verified end-to-end against the real `BTCUSDT` strategy from steps 3–4, including a real webhook
  delivery and the corrected exponential backoff — see
  [interview module 05](interview/05-concurrency-and-correctness.md)

## Step 5.5 — Backtesting ✅ done

Not in the original 8-step plan — noticed missing during step 5 planning.
`old-version/core/apps/market/models/backtest.py` is a real, substantial old feature (a `Backtest`
model, a dedicated Celery task in `brokers/binance/tasks/backtest.py`, admin, forms, templates)
with no slot anywhere above. Depends only on steps 3–4 (`Candle` history, the strategy evaluation
engine), not on broker execution/billing/production hardening — slotted in here, right after
signals/notifications, rather than at the end, since it's ready to build as soon as step 5 lands
and there's no reason to make it wait behind steps 6–8. Numbered 5.5 rather than renumbering
steps 6–8, which ADRs/interview modules already reference by number. See
[ADR 0010](adr/0010-backtest-forward-return-proxy.md).

- A new `apps/backtesting` app, one model (`Backtest`) and one task (`run_backtest`) — replays a
  `Strategy` against historical `Candle` data over a date range, reusing `apps/strategy/engine.py`
  unchanged (a backtest is just a different caller than `evaluate_strategy`, walking a rolling
  last-`HISTORY_CANDLE_COUNT`-candle window per historical candle instead of one live "now")
- The old system's win-rate/`total_r_r` came from `side`/stop-loss/take-profit fields that don't
  exist anywhere in `StrategyConfig` (ADR 0008) — reproducing them verbatim would mean pulling a
  position model into Step 4's schema two steps ahead of the roadmap. Instead: a side-agnostic
  **forward-return proxy** — on each trigger, the close-to-close % move `horizon_candles` later;
  `win_rate`/`total_forward_return` aggregate it, `scored_trigger_count` (tracked separately from
  `trigger_count`) excludes triggers too close to `end_time` to have real forward data, the same
  "don't fabricate a result from missing data" principle `InsufficientDataError` already applies
  at the other edge of a candle window
- Progress tracking via periodic `Backtest.progress` writes (capped to ~100 DB writes regardless
  of range size, not one per candle as the old system did); `/admin/`-only surface (no API,
  matching steps 3–5's precedent), with a "Run backtest" action reusing `run_backtest` itself —
  the same shape as `NotificationDelivery`'s "Retry now" (ADR 0009)
- Its own `backtesting` Celery queue, not `strategy` — a long-range backtest is genuinely heavy
  and open-ended; sharing `strategy`'s queue would risk delaying time-sensitive live evaluation
  ticks behind it, the same reasoning `orders` already gets its own queue for
- 6 new tests (a growth-rate candle fixture makes forward-return assertions exact rather than
  just sign-checked, plus the end_time/no-candles failure paths and the tail-scoring-exclusion
  case); no new idempotency mechanism — unlike steps 3–5, a redelivered `run_backtest` simply
  recomputes and overwrites the same row's results, which is correct for a rerun rather than a
  duplicate side effect to guard against — see
  [interview module 05.5](interview/05.5-backtesting.md)

## Step 6 — Broker execution

- Per-user API credentials, encrypted at rest — never plaintext columns as in the old schema
- Order placement with idempotency keys, `SELECT … FOR UPDATE` around balance changes
- Reconciliation task: the exchange, not our database, is the source of truth for fills

## Step 7 — Billing

- Plans, subscriptions, discounts; payment-gateway webhooks verified by signature and replay-safe
- Money as `Decimal`/integer minor units — never `float`

## Step 8 — Production hardening

- Sentry, metrics, structured request/task correlation IDs end to end
- Deployment pipeline and infrastructure as code; backup/restore runbook
- Load and failure testing: broker down, exchange rate-limited, worker killed mid-task

---

## Deliberately dropped from the old system

| Dropped                              | Why                                                                     |
| ------------------------------------ | ----------------------------------------------------------------------- |
| Vendored `binance/` client fork      | Pin a maintained client instead of carrying a 2019 fork                  |
| webpack/React admin bundle           | Django admin plus the OpenAPI schema covers it; revisit if a UI is needed |
| `django-celery-beat` DB scheduler    | Schedule belongs in version control, and it still pins `django<6.1`      |
| Four docker-compose overlay files    | One compose file; differences are environment variables                 |
| GitLab CI                            | Project moves to GitHub; one Actions workflow covers gates and publishing |
| `crypto-price/` + `telegram_server/` | Fold into Celery tasks/adapters unless a genuine separate service is needed |
