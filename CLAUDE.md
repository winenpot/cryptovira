# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working in this repository.

## Read this first

This repo holds **two codebases**:

| Path           | What it is                                                                            |
| -------------- | ------------------------------------------------------------------------------------- |
| repo root      | The **active rewrite** — Python 3.14 / Django 6.1 / uv. Everything new goes here.     |
| `old-version/` | The 2019 Django monolith, **reference only**. Not built, tested, linted, or imported. |

`old-version/` is the behavioural specification for features not yet ported. Read it to learn what
the system did; never import from it, never "fix" it, never add it to a lint/type/test path (it is
excluded in `pyproject.toml`, `.pre-commit-config.yaml`, and `.dockerignore`). Its own architecture
notes are in `docs/old-version-notes.md`.

Git state: `old-version/` is **gitignored** — it lives on disk as a local reference only, and its
history remains reachable through the pre-rewrite commits. HEAD still contains the old root layout,
so `git status` shows every old root file as deleted; that deletion is the rewrite and is intended,
but it has not been committed yet — confirm with the user before committing or discarding it.

## What this project is

Cryptovira: a platform that evaluates technical-analysis strategies against crypto market data,
emits **signals**, fans them out to subscribers by plan tier, and optionally executes orders on a
user's behalf through a broker API. Subscription billing sits alongside it.

The rewrite is deliberately incremental — see `docs/roadmap.md` for the ordered plan and the
current step. **Do not port domain code ahead of the roadmap**; each step lands with tests, types,
and docs before the next begins.

## Commands

Everything runs through `uv`; there is no system Python requirement and no `activate` step.

```bash
uv sync                              # create/refresh .venv from uv.lock
uv run manage.py <command>           # any Django management command
uv run pytest                        # full suite (needs the compose services)
uv run pytest -m "not integration"   # fast suite, no external services
uv run ruff check --fix . && uv run ruff format .
uv run mypy                          # strict, must stay clean
uv run pre-commit run --all-files

docker compose up -d db rabbitmq redis   # infrastructure only
docker compose up --build                # whole stack in containers
docker compose run --rm web migrate      # one-off management command
```

Celery, when running outside compose:

```bash
uv run celery -A cryptovira worker -l info -Q default,market,orders
uv run celery -A cryptovira beat -l info
```

Adding dependencies: `uv add <pkg>` / `uv add --group dev <pkg>` — never edit `pyproject.toml`
dependency lists by hand, and always commit the resulting `uv.lock`.

## Architecture

### Layout

```
manage.py                  # injects src/ onto sys.path, defaults DJANGO_SETTINGS_MODULE
src/cryptovira/
  config.py                # typed env config (pydantic-settings) — the only place env vars are read
  settings.py              # the single Django settings module, fed by config.py
  logging_config.py        # structlog + stdlib logging (JSON in deployed envs)
  celery.py                # Celery app, queue routing, beat schedule (declared in code)
  urls.py                  # root URLconf: /healthz, /readyz, /admin/, /api/v1/, /api/docs/
  api_v1.py                # aggregates each app's api/urls.py under the v1 namespace
  apps/common/             # health checks and shared base pieces
  apps/accounts/           # User model, JWT auth, /api/v1/accounts/*
tests/                     # pytest suite, mirrors src/; `integration` marker for service-backed tests
docker/                    # Dockerfile (multi-stage) + entrypoint.sh (web|worker|beat|migrate)
compose.yaml               # db (Postgres 18), rabbitmq (4.x), redis (8.x), web, worker, beat
.github/workflows/ci.yml   # the CI/CD pipeline: gates -> image build -> publish to GHCR
docs/adr/                  # architecture decision records — read before changing a core choice
docs/interview/            # concept drills tied to each decision (a stated goal of this rewrite)
```

### Rules that keep the rewrite clean

- **One settings module.** No `development.py` / `production.py` split. Environment differences are
  values in `.env` validated by `cryptovira.config.Settings`. If you need new configuration, add a
  typed field there and document it in `.env.example` — do not call `os.environ` anywhere else.
- **No secrets in the repo.** The old codebase hardcoded API keys in `settings/base.py`; that must
  never be reproduced. `gitleaks` runs in pre-commit.
- **Strict typing.** `mypy` runs in `strict` mode over `src/` and `tests/`. New code is typed; a
  needed escape hatch is a narrow `# type: ignore[code]` with a reason, not a loosened config.
- **Tests are not optional.** The old project had zero. Every new module lands with tests; anything
  needing Postgres/RabbitMQ gets `@pytest.mark.integration`.
- **Queues over threads.** Anything slow, external, or money-moving is a Celery task on a named
  queue (`market`, `orders`), never inline in a request.
- **Celery beat schedule lives in `celery.py`**, not in database rows. `django-celery-beat` is
  deliberately absent (it also still pins `django<6.1`).
- **Business logic out of views and models.** Pure calculation (indicators, sizing, risk) belongs in
  plain functions with no Django imports, so it is testable without a database.

### Signal lifecycle (target design, not yet built)

Beat fires a per-interval task → fan out one task per (strategy, symbol) → evaluate indicators over
a candle frame → on trigger, create a `Signal` in a transaction → dispatch notification and, if the
user has execution enabled, an order task on the `orders` queue. Every evaluation writes an audit
row. Ports of this flow must preserve idempotency: a redelivered task must not emit a second signal
or place a second order.

### Operational endpoints

`/healthz` is liveness — it must never touch a dependency. `/readyz` is readiness — it checks
database, cache, and broker and returns 503 when any is down. Keep them distinct; conflating them
turns a transient database blip into a restart loop.

## Conventions

- Python 3.14, line length 100, Ruff for both lint and format.
- Absolute imports from `cryptovira.*`; relative imports beyond the current package are banned.
- Comments explain **why**, not what. The docstrings in `config.py`, `celery.py`, and
  `apps/common/views.py` are the house style: state the trade-off, name the failure mode avoided.
- Migrations are reviewed like code; never edit an applied migration.
- `AUTH_USER_MODEL = "accounts.User"` is now locked in — Django cannot swap the user model once
  any migration has been applied against a real database. If a fresh local dev database ever
  drifts from the model state (stale local `migrate` runs, a rebased branch), `docker compose
  down -v` and re-`migrate` rather than fighting the migration graph; it's disposable local data.
