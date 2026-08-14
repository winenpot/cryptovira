# Cryptovira

Crypto trading-signal platform: evaluate technical strategies against exchange market data, emit
signals, fan them out to subscribers, and (optionally) execute orders on a user's behalf.

This is a **ground-up rewrite** of the 2019-era Django monolith that now lives, read-only, in
[`old-version/`](old-version/). The rewrite is being built in small, reviewable steps; see
[`docs/roadmap.md`](docs/roadmap.md) for what is done and what is next.

> **Status: step 1 — foundation.** The project boots, is fully typed and linted, has CI, and has a
> reproducible container stack. No trading domain code has been ported yet.

---

## Stack

| Concern         | Choice                          | Why (short version)                                             |
| --------------- | ------------------------------- | --------------------------------------------------------------- |
| Language        | Python 3.14                     | Current stable; free-threaded builds available if ever needed    |
| Packaging       | uv + `pyproject.toml` + `uv.lock` | One resolver, one lockfile, installs in seconds, no `venv` rituals |
| Web framework   | Django 6.1 + DRF 3.18           | Batteries-included ORM/admin/migrations; DRF for the API surface |
| Database        | PostgreSQL 18                   | Transactions, `SELECT … FOR UPDATE`, JSONB for strategy configs  |
| Task queue      | Celery 5.6 on **RabbitMQ 4**    | Real acknowledgements, redelivery, and DLQs for money-moving tasks |
| Cache           | Redis 8                         | Cache and short-lived locks only — *not* the broker              |
| Config          | pydantic-settings               | One settings module, validated env vars, boot-time failure       |
| Logging         | structlog (JSON)                | Queryable fields instead of grep-able prose                      |
| Lint/format     | Ruff 0.16                       | Replaces black + isort + flake8 + autoflake in one binary        |
| Types           | mypy 2.3 (strict) + django-stubs | Strict from day one — cheap now, impossible to retrofit later    |
| Tests           | pytest + pytest-django          | The old project had zero real tests                              |
| CI/CD           | GitHub Actions                  | Lint/type/test gates, image build, publish to GHCR from `main`   |

Every choice has a written rationale in [`docs/adr/`](docs/adr/), and the concepts behind them are
drilled as interview questions in [`docs/interview/`](docs/interview/).

---

## Quick start

Prerequisites: [uv](https://docs.astral.sh/uv/) and Docker. No system Python needed — uv fetches
the interpreter pinned in `.python-version`.

```bash
cp .env.example .env          # defaults already match the compose stack
docker compose up -d db rabbitmq redis
uv sync                       # creates .venv from uv.lock
uv run manage.py migrate
uv run manage.py runserver
```

Check it:

```bash
curl localhost:8000/healthz   # {"status": "ok"}
curl localhost:8000/readyz    # per-dependency status, 503 if anything is down
```

Or run the whole stack in containers:

```bash
docker compose up --build     # web + worker + beat + db + rabbitmq + redis
```

RabbitMQ's management UI is at <http://localhost:15672> (`cryptovira` / `cryptovira`).

---

## Everyday commands

```bash
uv sync                            # install/refresh the environment from uv.lock
uv add <package>                   # add a dependency (updates pyproject + lock)
uv add --group dev <package>       # add a dev-only dependency
uv lock --upgrade                  # bump the lockfile deliberately

uv run manage.py <command>         # any Django management command
uv run pytest                      # test suite with coverage
uv run pytest -m "not integration" # skip tests that need Postgres/RabbitMQ
uv run ruff check --fix .          # lint
uv run ruff format .               # format
uv run mypy                        # strict type check

uv run celery -A cryptovira worker -l info -Q default,market,orders
uv run celery -A cryptovira beat -l info
```

Install the git hooks once so CI never fails on formatting:

```bash
uv run pre-commit install
```

---

## Layout

```
manage.py                 # entrypoint; injects src/ onto sys.path
pyproject.toml            # deps, ruff, mypy, pytest, coverage — one config file
uv.lock                   # exact resolved versions, committed
compose.yaml              # dev stack: db, rabbitmq, redis, web, worker, beat
docker/                   # Dockerfile + entrypoint
src/cryptovira/
  config.py               # typed env settings (pydantic-settings)
  settings.py             # the single Django settings module
  logging_config.py       # structlog + stdlib logging wiring
  celery.py               # Celery app, queues, beat schedule (in code)
  urls.py / api_v1.py     # root URLconf; versioned API aggregation
  apps/common/            # health checks, shared base models
tests/                    # pytest suite, mirrors src/
docs/
  adr/                    # architecture decision records
  interview/              # concept drills tied to each decision
  roadmap.md              # step-by-step rewrite plan
old-version/              # the 2019 codebase, kept for reference only
```

---

## Troubleshooting

Three failures worth knowing about, all fixed in the committed config — if you hit them after
changing something, this is why:

| Symptom                                                     | Cause                                                                                                  |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `db` container unhealthy, log mentions `pg_ctlcluster`      | Postgres 18+ stores data in `/var/lib/postgresql/<major>/docker`. Mount the volume at `/var/lib/postgresql`, not `.../data`. |
| Worker exits with `Feature transient_nonexcl_queues is deprecated` | RabbitMQ 4 blocks Celery's control queues; `docker/rabbitmq/10-cryptovira.conf` permits that one feature. |
| Beat crash-loops on `PermissionError: 'celerybeat-schedule'` | The container runs as non-root and `/app` is not writable. Beat writes to `/app/run` instead.            |

If the database volume was created by a broken run, `docker compose down -v` discards it — that
deletes local data, so check before running it against anything you care about.

## Reading the old code

`old-version/` is not built, tested, linted, or imported. It is the specification of what the
system used to do — consult it when porting a behaviour, then delete nothing until the
replacement is tested. Its own notes are in [`old-version/Readme.md`](old-version/Readme.md).
