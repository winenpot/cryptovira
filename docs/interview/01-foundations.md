# Module 01 — Foundations

Covers roadmap step 1: packaging, configuration, containers, the message broker, health checks,
CI, typing, and testing. Every answer points at code in this repository.

---

## A. Packaging and environments

### A1. What problem does a lockfile solve that pinned `requirements.txt` versions do not?

Pinning direct dependencies leaves **transitive** dependencies floating: `django==6.1` still allows
any `asgiref`, and a patch release of a sub-dependency can break the build months later. A lockfile
records **the entire resolved graph with hashes**, so an install today and an install next year
produce byte-identical trees — and the hashes also defend against a compromised or re-uploaded
package. The complementary discipline is `--frozen` in CI: fail if the lock and manifest disagree,
rather than silently re-resolving and testing something different from what you'd deploy.

> **In this repo:** `uv.lock` is committed; CI runs `uv sync --frozen`
> (`.github/workflows/ci.yml`); a pre-commit `uv-lock` hook rejects drift.

### A2. Why `[dependency-groups]` instead of listing dev tools in `dependencies`?

Anything in `dependencies` is installed **in production**. pytest, mypy, and ruff in the runtime
image mean a bigger image, a bigger attack surface, and more CVEs to triage for code that never
runs there. PEP 735 groups are the standard mechanism; `uv sync --no-dev` in the Docker builder is
what makes it concrete.

> **In this repo:** `pyproject.toml` `[dependency-groups] dev = [...]`; `docker/Dockerfile` uses
> `uv sync --frozen --no-dev`.

### A3. `pip`, `pip-tools`, `Poetry`, `uv` — how would you choose?

Say what each solves rather than picking a favourite: pip installs but does not lock; pip-tools adds
locking on top of pip; Poetry/PDM add project management and locking with their own resolvers; uv
does all of that **plus interpreter management**, as a single static binary, fast enough that CI can
afford a cold install. The deciding criteria are: is the lockfile **cross-platform**, does CI have a
**one-command reproducible install**, and does the tool leave you on **standard formats** so you can
leave later. Red flag answer: "Poetry because it's popular."

> **In this repo:** [ADR 0002](../adr/0002-uv-for-packaging.md).

### A4. Your project requires Python 3.14 but the server has 3.11. What are your options and their trade-offs?

Options: build a container with the right interpreter (best — the runtime becomes part of the
artefact); use a version manager (pyenv/uv) on the host; or lower the project's floor. The real
point to make is that **the interpreter is a dependency**: if it is not pinned and shipped, you get
environment drift that no lockfile can protect you from.

> **In this repo:** `.python-version` + `requires-python` pin it; the Dockerfile bakes it in. The
> machine this was built on has no system Python at all.

**Drill:** run `uv run python -c "import sys; print(sys.version)"` and then delete `.venv` and run
it again. Explain what uv did and how long it took.

---

## B. Configuration and secrets

### B1. What is the twelve-factor rule about config, and what does violating it look like?

Config is **everything that differs between deploys** — credentials, hostnames, feature flags — and
it belongs in the **environment**, not in code. Violations look exactly like the old codebase:
secrets committed in `settings/base.py`, a `production.py` nobody can run locally, and a settings
module whose effective values depend on which of four files won. The practical test: could you open
the repository publicly without rotating a single credential? Could you deploy the same artefact to
staging and production, changing only environment variables?

### B2. Why validate configuration with a typed model instead of reading `os.environ` where you need it?

Environment variables are **strings**. Scattered `os.environ.get("MAX_RETRIES", 3)` calls produce a
`str` where an `int` was assumed, a missing variable that only surfaces on the code path nobody
tested, and a default silently applied in production. A typed model **parses at boot**: types are
coerced and checked, missing required values abort startup, and cross-field rules ("production may
not use the dev secret key") are expressible. **Fail fast, fail loud, fail at deploy time.**

> **In this repo:** `src/cryptovira/config.py`; the rules are tested in `tests/test_config.py`.

### B3. How do you keep a secret out of logs and tracebacks?

Wrap it in a type whose `repr` redacts (pydantic's `SecretStr`), never interpolate it into log
messages or exception text, and scrub connection strings before they leave the process — a
`ConnectionRefusedError` from AMQP happily contains `amqp://user:password@host`. Then add
defence in depth: secret scanning in pre-commit, and scrubbing in the error reporter.

> **In this repo:** `Settings.secret_key` is a `SecretStr`; `_describe()` in
> `apps/common/views.py` returns only the exception **type**, and a test asserts the password
> never appears in probe output.

### B4. Split settings modules (`base/dev/prod`) are a Django convention. Why avoid them here?

They fail in one specific way: **the effective configuration of production is not readable from any
single file**. Combine that with import-time side effects and you get settings that differ between
`manage.py`, gunicorn, and Celery. One module plus environment variables keeps configuration
inspectable (`env | sort`) and makes the artefact identical across environments — which is what
makes staging a meaningful rehearsal for production.

> **In this repo:** [ADR 0004](../adr/0004-single-settings-module.md).

**Drill:** set `ENVIRONMENT=production` with no other change and run `uv run manage.py check`.
Explain the error and why failing here is better than booting.

---

## C. Containers

### C1. Explain the layer order in `docker/Dockerfile`. Why are dependencies installed before the source is copied?

Docker caches per layer and invalidates every layer after the first change. Application code changes
many times an hour; the dependency set changes weekly. Copying `pyproject.toml` + `uv.lock` and
installing **before** copying `src/` means a code edit reuses the cached dependency layer, turning a
three-minute rebuild into ten seconds. `--mount=type=cache` goes further: the package cache survives
even when the layer is invalidated.

### C2. Why a multi-stage build, and what exactly is left behind?

The builder needs uv, a compiler toolchain, the lockfile, and package caches. The runtime needs
none of that — only the interpreter, the virtualenv, and the source. Multi-stage means the final
image copies just `/app/.venv` and `src/`, so it is smaller (faster pulls, faster autoscaling) and
has **less to exploit**: no build tools for an attacker who gets code execution, and no lockfile or
build secrets sitting in a published layer.

### C3. Why does the container run as a non-root user?

Container isolation is not a security boundary you should bet on. Root in the container is root in
the kernel namespace, so a container escape or a writable bind mount becomes host compromise. A
dedicated UID also catches mistakes early: code that tries to write outside its own directories
fails in development instead of quietly succeeding.

### C4. Why does `entrypoint.sh` not run migrations?

Because it runs in every replica. Three pods starting simultaneously run three concurrent
`migrate` commands; Django's migration lock is per-connection, not global, so you get lock waits at
best and a half-applied schema at worst. Migrations are a **deploy step**, run exactly once, before
or after the rollout depending on whether the change is backwards-compatible.

> **In this repo:** the comment at the top of `docker/entrypoint.sh`; `docker compose run --rm web
> migrate` is the one-off path.

### C5. `/healthz` and `/readyz` — what is the difference, and why does conflating them cause outages?

**Liveness** answers "is this process wedged?"; failing it gets the container **killed**.
**Readiness** answers "should traffic go here right now?"; failing it removes the pod from the load
balancer but leaves it running. If liveness checks the database, a 30-second database blip kills
every pod simultaneously — and they all restart into the same blip, with cold caches and a
thundering herd of reconnections. Liveness must therefore depend on **nothing external**.

> **In this repo:** `src/cryptovira/apps/common/views.py`; `healthz` returns immediately, `readyz`
> reports per-dependency status and returns 503 when any dependency is down. Tests assert that
> `healthz` never calls a dependency probe.

### C6. A database container that worked last month refuses to start after a base-image bump. How do you diagnose it, and what class of bug is this?

Read the container's own logs first — image maintainers usually explain the refusal — then compare
the **volume mount path** against what the new image expects. This exact case happened here:
Postgres 18 moved its data directory to `/var/lib/postgresql/<major>/docker` so that
`pg_upgrade --link` does not cross a mount boundary, and a volume still mounted at
`/var/lib/postgresql/data` makes the container **refuse to start rather than silently ignore your
data** — the safe behaviour. The general class is *stateful service upgrades*: the image is
disposable, the volume is not, and the contract between them can change across majors. The
lesson for production is that a database major upgrade is a planned migration with a rehearsal
and a rollback, never a tag bump in compose.

### C7. Your worker container reports unhealthy while its logs clearly say the worker is ready. Where do you look?

At the health check, not the app. Two failure modes cover most cases: **the check runs in the wrong
form** — Docker's `CMD` exec form runs no shell, so `$HOSTNAME` in the command is passed literally
and never expands (`CMD-SHELL` is required) — and **the check is inherited from the image** by a
container playing a different role, e.g. a `beat` container running the image's
`curl /healthz` check when it serves no HTTP at all. Both happened in this repo; the fixes are in
`compose.yaml`. The wider point: a health check is code, and an incorrect one is worse than none,
because orchestrators act on it.

**Drill:** stop the RabbitMQ container and call both endpoints. Explain what an orchestrator would
do with each response.

---

## D. Queues and the broker

### D1. Redis vs RabbitMQ as a Celery broker — argue both sides, then decide.

Redis: one fewer service if you already run it, very fast, simple mental model. But it is a
**data store being used as a queue** — acknowledgement is emulated with a visibility timeout,
in-flight messages are lost on failover (replication is asynchronous), and there is no dead-letter
concept. RabbitMQ is a **broker**: per-message ack, broker-side redelivery when a consumer drops,
publisher confirms, durable and quorum queues, dead-letter exchanges. The decision follows from the
cost of losing a message. For notifications, Redis is fine. For **orders**, it is not.

> **In this repo:** [ADR 0003](../adr/0003-rabbitmq-as-broker.md). Redis is kept, restricted to
> cache, with persistence off and `allkeys-lru` eviction.

### D2. What does `task_acks_late=True` change, and what does it oblige you to do?

By default Celery acks a message **when it is delivered**; if the worker then dies, the work is
lost. With `acks_late`, the ack happens **after the task returns**, so a crashed worker's message is
redelivered. The obligation: at-least-once delivery means a task may run **twice**, so every task
that writes must be **idempotent** — natural keys, idempotency keys, `get_or_create`, or a
uniqueness constraint the second run trips over. Pair it with `task_reject_on_worker_lost=True`,
or a `SIGKILL`ed worker's task still vanishes.

### D3. Why `worker_prefetch_multiplier=1`?

Prefetch is how many messages a worker reserves beyond the ones it is executing. The default (4×
concurrency) is a throughput optimisation for short tasks; with long, uneven tasks it causes **head
-of-line blocking** — one worker sits on twenty messages it will not get to for ten minutes while
another worker idles. For tasks measured in seconds-to-minutes, reserve one at a time and let the
broker do the load balancing.

### D4. Why separate `market` and `orders` queues instead of one `default`?

**Blast radius and independent scaling.** A flood of price-ingest work must not delay order
placement, and a wedged exchange client must not consume the workers that send notifications.
Separate queues let you run separate worker pools, size them differently, alert on their depths
separately, and stop one without stopping the other.

> **In this repo:** `task_routes` in `src/cryptovira/celery.py`.

### D5. Why is the beat schedule in code rather than in `django-celery-beat`'s database tables?

A DB-backed schedule is editable at runtime, which sounds useful until the live schedule silently
diverges from the repository with no history of who changed it or when. In code, the schedule is
reviewed, diffed, and rolled back like anything else. Runtime editability is a real requirement for
some products — but then it needs an audit trail, not an admin form nobody watches. (The package
also still pins `django<6.1`, which forced the decision here.)

**Drill:** describe, concretely, what happens to an in-flight `place_order` task if you
`docker kill` the worker — under Redis, and under RabbitMQ with the settings in `celery.py`.

---

## E. Quality gates

### E1. Ruff replaces black, isort, flake8, and autoflake. What is the argument beyond speed?

**One tool, one config, one version to pin.** The old project ran four tools that each had opinions
about imports and line breaks, so a pre-commit run could produce a file the next tool wanted to
change back. Speed matters too, but the real benefit is that formatting and linting can run on
every save and in CI with identical results.

### E2. Why `mypy --strict` from day one? Is it worth it on a Django project?

Retrofitting types onto an untyped codebase is far more expensive than starting strict, because
every unannotated function you add becomes another thing to fix later. On Django specifically,
`django-stubs` turns model field access, queryset methods, and settings into checked code, which
catches the classic `None`-handling and wrong-type bugs before they reach a test. The honest caveat
to raise in an interview: some third-party libraries ship no types (Celery, kombu), so you list
those explicitly as `ignore_missing_imports` rather than switching it on globally — the escape
hatch stays **narrow and visible**.

> **In this repo:** `[tool.mypy]` in `pyproject.toml`; the untyped packages are enumerated one by
> one, and the single `# type: ignore[untyped-decorator]` in `celery.py` carries a reason.

### E3. Your pytest config sets `filterwarnings = ["error"]`. Why, and what is the cost?

A `DeprecationWarning` is a bug with a due date. Turning warnings into errors means you fix them
when the library warns you, not on the day the next major release removes the feature and your
deploy breaks. The cost is that a noisy third-party warning can block CI, which is why the ignore
list is explicit, per-warning, and commented — never a blanket `ignore`.

### E4. What belongs in pre-commit and what belongs in CI?

Pre-commit gets **fast, deterministic, auto-fixable** checks: formatting, lint, secret scanning,
lockfile drift. Anything slow (the full suite, image builds, integration tests) belongs in CI,
because a 30-second hook is a hook developers bypass with `--no-verify`. CI must re-run everything
pre-commit does, since hooks are advisory — a check that only exists locally does not exist.

### E5. How is the test suite structured so it can run without Postgres or RabbitMQ?

Tests that need real services are marked `integration` and deselected by default; the fast suite
substitutes dependency probes with mocks and constructs configuration objects directly. That gives
a sub-second inner loop and still exercises the real thing in CI, where the services exist. The
principle: **the default test command must never require a running environment**, or people stop
running it.

> **In this repo:** the `integration` marker in `pyproject.toml`; `tests/test_health.py` has both
> kinds side by side.

**Drill:** add a failing assertion to `tests/test_config.py`, then run `uv run ruff check`,
`uv run mypy`, and `uv run pytest -m "not integration"`. Note which gate catches what — and how
long each takes.

---

## F. Questions you should be able to ask back

Interviewers weight these heavily; they are also the questions to ask yourself before step 2.

1. What is the cost of losing a single message here — a cent, a customer, or a compliance incident?
2. What is the deploy story: how does a migration that renames a column go out without downtime?
3. Who gets paged when `readyz` goes red, and what does the runbook say?
4. Where is the source of truth for money — our database, or the exchange?
5. What is the oldest dependency in the tree, and who upgrades it?
