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

## Step 2 — Accounts and API surface

- Custom `User` model (get this in *before* the first real migration — it cannot be retrofitted)
- Token/JWT authentication, permissions, throttling; OpenAPI schema published from the code
- Test fixtures and factories; the first `integration`-marked database tests

## Step 3 — Market data domain

- `Currency` / `Candle` models, timeframe handling, timezone-correct storage
- An exchange client behind an interface (`MarketDataSource`), so tests never hit the network
- Ingest task on the `market` queue, idempotent by `(symbol, interval, open_time)`

## Step 4 — Strategy engine

- Pure indicator/operator functions — no Django imports, property-testable
- The TA-Lib decision (bundled wheels vs a pure-Python implementation) gets its own ADR
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
