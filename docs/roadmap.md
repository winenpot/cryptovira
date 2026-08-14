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

## Step 4 — Strategy engine

- Pure indicator/operator functions — no Django imports, property-testable
- ~~The TA-Lib decision (bundled wheels vs a pure-Python implementation) gets its own ADR~~ done
  early — [ADR 0006](adr/0006-ta-lib-packaging.md): `ta-lib` installs as a prebuilt wheel with the
  C library bundled in, no compiler needed on any target platform, verified in `tests/test_talib.py`.
  The indicator/operator layer itself is still this step's work, not done yet.
- `Strategy` model with a validated JSON config; evaluation writes an audit row every run

## Step 5 — Signals and notifications

- `Signal` creation inside a transaction, idempotent under task redelivery
- Notification fan-out per plan tier, retried with backoff, dead-lettered on permanent failure
- Templated messages, per-channel adapters (Telegram, SMS, webhook)

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
