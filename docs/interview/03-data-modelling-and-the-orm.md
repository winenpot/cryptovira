# Module 03 — Data modelling & the ORM

Covers roadmap step 3: `Currency`/`Candle` modelling, DB-level idempotency, `on_delete` semantics,
structural typing for an exchange interface, and a real Celery configuration bug this build hit
mid-way through — one of the best kind of interview questions, because the answer is "here's the
exact failure and why," not a textbook paragraph.

---

## A. Abstract base models — when to reach for one

### A1. `TimestampedModel` (`apps/common/models.py`) is a two-field abstract base used by `Currency`. Why is this not the premature abstraction CLAUDE.md warns against ("don't design for hypothetical future requirements")?

Because it isn't hypothetical: it has two concrete consumers in the same change (`Currency` now,
and — by name, in `docs/roadmap.md` — `Strategy`, `Signal`, `Order`, `Plan`, `Subscription` in
steps 4 through 7). The rule against premature abstraction is about designing for imagined future
requirements; this is a documented one. The bar isn't "could this be reused," it's "is there a
second real consumer today, or a named one on the roadmap."

> **In this repo:** `apps/common/models.py`'s docstring states this reasoning inline, the same
> house style as `config.py`/`celery.py`.

### A2. `Candle` deliberately does *not* inherit `TimestampedModel`, even though it's a model created via `bulk_create`. Why?

`TimestampedModel` gives you `created_at` (`auto_now_add`) *and* `updated_at` (`auto_now` — reset
on every `.save()`). A closed candle's OHLCV values never change after insert — there is no code
path that updates one. An `updated_at` column that always equals `created_at` doesn't describe
anything real about the row; it's a column that exists because the base class was reached for
without asking whether *both* fields applied. `Candle` gets a plain `created_at` only.

**Drill:** find a model in a codebase you've worked on that inherited a shared "audit fields"
base class without using every field on it. What would you have to check before removing the
unused field — and what breaks if some other model's `queryset.order_by("-updated_at")` was
quietly relying on it always existing, even if never meaningfully changing?

---

## B. One canonical representation of a timeframe

### B1. `Interval` is a single `models.TextChoices` (`"1m"`, `"5m"`, ... `"1w"`). What was wrong with how the old system modelled the same concept?

Two independent, divergent representations of the same fifteen timeframes:
`core/apps/market/models/strategy.py`'s `INTERVALS` tuple stored them as **seconds-as-strings**
(`"60"` → `"1m"`, `"3600"` → `"1h"`), duplicated verbatim across three separate models
(`ParentStrategy`, `Strategy`, `Signal`) — so a new timeframe meant editing the tuple in three
places and hoping they stayed in sync. Separately, `crypto-price/app.py`'s real-time ingestion
service hardcoded the *same* fifteen timeframes again, this time as Binance-style strings
(`"1m"`, `"3m"`, ...) for its WebSocket subscriptions — a second spelling of the same domain
concept, decoupled from the first with nothing enforcing they'd ever agree.

> **In this repo:** `apps/market/models.py::Interval` — every place a timeframe is needed
> (`Candle.interval`, `MarketDataSource.get_klines`'s `interval` parameter, the Celery beat
> schedule's `kwargs`) imports this one enum. There is no second spelling to drift.

### B2. Why is the choices list a *subset* of what Binance actually supports (eight values, not fifteen), and why is that a safe choice rather than a limitation?

Because `choices=` on a `CharField` is not a database-level constraint — Postgres doesn't reject
a row for having an interval value outside the Python-side list (unless you additionally added a
`CHECK` constraint, which this model doesn't). Extending the enum later is a pure Python change:
add a member, no migration required, because the column type (`CharField(max_length=3)`) doesn't
change. Starting narrow (the timeframes step 4's strategy engine will actually evaluate) costs
nothing to widen later, and avoids ingesting/storing candle data nobody queries in the meantime.

**Drill:** if `Candle.interval` instead used Postgres's native `ENUM` type
(`django.contrib.postgres.fields.CharField` isn't it — you'd reach for a raw `CREATE TYPE ... AS
ENUM` via a migration, or a package like `django-enum`), would adding a new interval still be a
no-migration change? What does that trade-off buy you, and what does it cost?

---

## C. Idempotency is a database constraint, not application logic

### C1. `Candle` has `UniqueConstraint(fields=["currency", "interval", "open_time"])`. Walk through *why* this specific constraint is what makes candle ingestion safe under Celery's `task_acks_late` + `task_reject_on_worker_lost`.

Those two settings (`celery.py`) mean: a worker acknowledges a task only *after* it finishes, and
if the worker dies mid-task, the broker redelivers the message to another worker. That's a
correctness feature for tasks that place real orders — but it also guarantees, as a matter of
when (not if), that `ingest_candles` will sometimes run twice for the same `(symbol, interval)`
batch: once that appeared to fail (worker died after writing rows but before acking), and once on
redelivery. Without a database constraint, the redelivered run would either duplicate every row
it already wrote, or need its own bespoke "have I seen this batch before" check — exactly the
check-then-save race ADR 0005 already rejected for `User.email`. The constraint makes the
database itself the single source of truth for "does this row already exist," which is atomic
under concurrent writers in a way that no application-level check can be.

> **In this repo:** `tests/apps/market/test_tasks.py::test_ingest_candles_is_idempotent_under_redelivery`
> proves this directly — it runs the same ingest task twice with an overlapping batch and asserts
> both that no duplicate rows land *and* that the second run doesn't raise.

### C2. The ingest task writes with `Candle.objects.bulk_create(candles, ignore_conflicts=True)` rather than looping `update_or_create()` per candle. What's actually being traded off?

`update_or_create()` is a `SELECT` (or an `INSERT ... ON CONFLICT DO UPDATE` under the hood,
depending on backend) per row — safe, but it implies there's something to *update*. A closed
candle's OHLCV values are immutable facts from the exchange; there is nothing to update on a
redelivered write, only a duplicate to reject. `bulk_create(ignore_conflicts=True)` compiles to a
single `INSERT ... ON CONFLICT DO NOTHING` (Postgres), letting the database silently discard rows
that collide with the unique constraint in one round trip, instead of one query per row. The
trade-off: `ignore_conflicts=True` can't tell you *which* rows were skipped versus inserted (no
partial-failure detail comes back), and if a row's non-key columns ever needed correcting after
the fact, this write path can't do that — it would need a real `update_or_create` or a manual
`UPDATE`. That's fine here because candles don't get corrected; it would be the wrong choice for
a model where they did.

### C3. What happens if `ingest_candles` writes a candle whose bar hasn't actually closed yet?

Binance's klines endpoint can return the currently-forming bar as the last element of the
response — a low/high/volume that's still accumulating, not final. If that row got written once,
`ignore_conflicts=True` means it can **never be corrected** on a later poll: the second, accurate
version of that same `(currency, interval, open_time)` triple collides with the unique
constraint and is silently discarded, leaving the first, wrong values in place permanently. This
is why `ingest_candles` explicitly drops any kline whose `close_time` is still in the future
relative to "now" before writing — the filter isn't defensive-programming noise, it's the one
thing standing between "eventually consistent" and "permanently wrong."

> **In this repo:** `tests/apps/market/test_tasks.py::test_ingest_candles_drops_the_still_forming_bar`.

**Drill:** `Candle.objects.bulk_create(candles, ignore_conflicts=True)` silently discards
conflicting rows with no log line, no metric, nothing. In production, how would you tell the
difference between "ingestion is healthy, most polls just re-fetch a mostly-overlapping window by
design" and "ingestion has been silently failing to write anything new for six hours"? What would
you add, and where?

---

## D. `on_delete` is a modelling decision, not a default to leave alone

### D1. `Candle.currency` uses `on_delete=models.PROTECT`. Every other FK you've likely written defaults to `CASCADE` without thinking about it. What does `PROTECT` buy here, concretely?

`CASCADE` would mean deleting a `Currency` silently deletes every candle ever ingested for it —
years of historical data a strategy backtest (step 4) might still need, gone in one call, with no
prompt. `PROTECT` raises `django.db.models.ProtectedError` instead of deleting anything, the
moment a `Currency` with existing candles is targeted. The intended way to stop tracking a symbol
is `Currency.is_active = False` — ingestion stops, history stays. `PROTECT` makes the *wrong* way
(an accidental `Currency.objects.get(...).delete()`) fail loudly instead of quietly succeeding.

> **In this repo:** `tests/apps/market/test_models.py::test_deleting_a_currency_with_candles_is_protected`.

**Drill:** name the four other `on_delete` options (`SET_NULL`, `SET_DEFAULT`, `DO_NOTHING`,
`RESTRICT`) and, for each, describe a model relationship elsewhere in a system like this one
(strategies, signals, orders, subscriptions) where it would be the right choice — not just where
it's merely acceptable.

---

## E. `Protocol` — the first structural-typing interface in this codebase

### E1. `MarketDataSource` is a `typing.Protocol`, not an `abc.ABC`. `BinanceRestMarketDataSource` and `tests/apps/market/fakes.py::FakeMarketDataSource` both "implement" it — show what actually makes that true, given neither one imports or subclasses `MarketDataSource`.

Structural typing: a `Protocol` is satisfied by *any* object whose methods match the declared
signature, with zero inheritance relationship required. `FakeMarketDataSource.get_klines(self, *,
symbol, interval, limit=500, start_time=None)` matches `MarketDataSource.get_klines`'s signature
exactly, so mypy accepts it wherever a `MarketDataSource` is expected — the check is "does the
shape match," not "is this a subclass." Compare to `abc.ABC`, where you'd need
`class FakeMarketDataSource(MarketDataSource, ...)` and Python would enforce every abstract
method is overridden *at class-definition time*, with a real inheritance edge in the MRO.

### E2. Given E1, why `Protocol` here specifically, rather than `abc.ABC`?

There's exactly one production implementation and one test double — the ceremony `ABC` buys
(enforced subclassing, `@abstractmethod` decorators, a shared base class both real code and test
fakes must import) has no payoff yet. `Protocol` gets the same "tests never hit the network"
guarantee — swap in an object matching the shape — with less coupling: a fake never needs to
import the real interface module at all, only match its shape. If a second real exchange
implementation and genuinely shared logic between them emerged, that would be the point to
reconsider — not before.

### E3. `BinanceRestMarketDataSource`'s tests use `httpx.MockTransport`, not a mocking library. What does that actually replace, and what's the failure mode it protects against that patching `httpx.get` wouldn't?

`MockTransport` replaces the actual network transport `httpx.Client` uses to send a request —
everything above that (URL building, query param encoding, response parsing) still runs for
real. Patching `httpx.Client.get` directly would skip all of that and only prove the *parsing*
code works on hand-constructed input; it couldn't catch a bug in how request params are built
(e.g. `interval.value` vs `str(interval)`, or a typo'd query key). `MockTransport`'s handler
receives a real `httpx.Request` object built by the real client, so the assertions in
`test_binance.py` (`request.url.params["interval"] == "1h"`) are checking what the client *would
actually send* over the wire, not a mock's idea of it.

> **In this repo:** `tests/apps/market/sources/test_binance.py` — no `integration` marker, no
> database, no real network, and it still exercises the full request-building path.

---

## F. A real bug this build hit: Celery's config-key prefix resolution

### F1. `tests/conftest.py`'s `eager_celery` fixture originally did `current_app.conf.task_always_eager = True`. It looked correct, ran without error, and silently did nothing — every market-data task test failed with zero side effects and no exception. What was actually happening?

`settings.py` defines `CELERY_TASK_ALWAYS_EAGER = env.celery_task_always_eager` as a real Django
constant, which `app.config_from_object("django.conf:settings", namespace="CELERY")` loads into
one of Celery's internal configuration layers under that exact **prefixed** key
(`CELERY_TASK_ALWAYS_EAGER`). Celery's `ConfigurationView` (the object behind `app.conf`) is a
layered mapping: attribute access like `conf.task_always_eager = True` writes the **unprefixed**
key into the top "changes" layer. But *reads* — including the read the fixture itself performs a
moment later — try the **prefixed** key first, checked across every layer before ever falling
back to the unprefixed one. Since a lower-priority layer already has
`CELERY_TASK_ALWAYS_EAGER: False` (from the Django settings default), that's what gets found
first — the fixture's unprefixed override sits in a layer that's checked, but for a key nothing
ever reads. No exception anywhere in that chain, because every individual operation succeeds;
only the net effect is wrong.

The observable symptom was exactly as confusing as that description: `.delay()` didn't run the
task inline, it published to the *real* RabbitMQ broker running in `docker compose`, and the test
process moved on to its assertions before (if ever, from the test's perspective) a real worker
picked the message up. No traceback, just empty query results.

### F2. What's the fix, and why does writing the *prefixed* key directly work when attribute assignment didn't?

```python
current_app.conf["CELERY_TASK_ALWAYS_EAGER"] = True
```

Writing the literal key that the read path checks first, in the same top-priority "changes"
layer, means the override is now visible via *both* the prefixed key (read directly) and the
unprefixed one (Celery's lookup falls back to the prefixed variant before the unprefixed one
regardless of which layer it's in — the layer order matters, but so does trying the prefixed key
first at every layer). The general lesson: when a Django-Celery project defines a `CELERY_*`
setting explicitly (most tutorials don't — they only set what's *different* from Celery's
defaults, e.g. this project's own `task_acks_late`/`task_routes`/`beat_schedule` never appear as
Django constants, only in `app.conf.update(...)` inside `celery.py`), any runtime override of
*that specific setting* needs to go through the same prefixed-key path or it silently loses.

> **In this repo:** `tests/conftest.py::eager_celery`'s docstring is written as the postmortem of
> this exact failure, the same way `docs/interview/02-accounts-and-jwt.md`'s throttling section
> documents the `THROTTLE_RATES`-bound-at-import gotcha.

**Drill:** `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` are *also* explicit Django constants
in `settings.py`. Write a test that tries to override `CELERY_RESULT_BACKEND` at runtime via
plain attribute assignment (`current_app.conf.result_backend = "cache"`) and confirm it has the
same silent-no-op failure mode as `task_always_eager` did. Then explain why `task_acks_late`
*doesn't* have this problem — check `settings.py` for whether a `CELERY_TASK_ACKS_LATE` constant
exists there at all.

---

## G. Questions you should be able to ask back

1. `Candle.open`/`high`/`low`/`close`/`volume` are `DecimalField(max_digits=20, decimal_places=8)`
   — is 8 decimal places enough for every asset this system might ever list, and what actually
   breaks (silently rounds, or loudly errors) the day it isn't?
2. `bulk_create(ignore_conflicts=True)` gives no visibility into how many rows were actually new
   versus skipped. If ingestion silently stopped producing new candles for one symbol, how would
   you find out — before a strategy backtest quietly ran against stale data?
3. `fan_out_ingest_candles` dispatches one Celery task per active `Currency` via `group()`. What
   happens to the beat schedule's next tick if the previous fan-out for that interval hasn't
   finished — do runs overlap, queue up, or does something need to change before this scales past
   a handful of symbols?
4. `MarketDataSource.get_klines` has no retry or backoff. The first time Binance rate-limits this
   process, what's the actual failure mode under `task_acks_late` — does the task's own exception
   trigger redelivery, and is that redelivery immediate (a retry storm) or backed off?
