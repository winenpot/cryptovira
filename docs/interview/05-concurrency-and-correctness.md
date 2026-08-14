# Module 05 — Concurrency and correctness

Covers roadmap step 5's slice of "Step 5–6": Celery's two different failure-recovery mechanisms,
idempotency built three different ways on the same underlying principle, `transaction.on_commit`
as the boundary between "committed" and "a task can safely see it," and the honest limits of
at-least-once delivery. Step 6 will extend this module with order idempotency and
`SELECT ... FOR UPDATE` — the same lock this module previews without building.

---

## A. Two kinds of "it happened again" — not one

### A1. `task_acks_late=True` has protected every task since Step 3. What does it actually do, at the RabbitMQ protocol level, and why does it have no computed delay?

A worker only tells RabbitMQ "this message is done" (acks it) *after* the task function returns
successfully — not when it starts consuming the message. If the worker process itself dies
mid-task (OOM-killed, `docker compose restart`, a hard crash), RabbitMQ notices the connection
drop, sees the message was never acked, and redelivers the *exact same message* to another (or
the same, once restarted) consumer — immediately. There's no delay to compute because nothing
about this is a *decision*; it's a property of the queue protocol firing when a consumer
disappears, not something task code opts into or can observe happening.

> **In this repo:** `celery.py`'s `task_acks_late=True` + `task_reject_on_worker_lost=True`, in
> place since Step 1, before any task existed to test it against. `ingest_candles`,
> `evaluate_strategy`, and `send_notification` are all protected by this identically — none of
> them had to add anything to get it.

### A2. `send_notification` (this step) is the first task to also use `self.retry(...)`. What's actually different about this mechanism versus A1?

The task *runs to completion of its own logic*, catches an exception itself, and explicitly asks
Celery to publish a **new** message with a computed delay — incrementing
`self.request.retries`, which travels in that new message's headers. This requires the task's
code to reach the `except` block and call `self.retry()`; A1 requires nothing from the task at
all, because the broker acts on connection loss, not on anything the task observed. They handle
different failure classes: A2 is for "the external call failed, but will probably succeed on a
later attempt" (Telegram briefly down) — a judgment only the task's own code can make. A1 is for
"the process running this task no longer exists" — something no amount of `except` blocks inside
that (now-dead) process can catch.

> **In this repo:** `apps/signals/tasks.py::send_notification` — `bind=True` and an explicit
> `raise self.retry(exc=exc, countdown=...) from exc` inside the `except ChannelDeliveryError`
> branch, not the `autoretry_for` decorator shortcut. The mechanism is deliberately visible in the
> function body: catch, decide (retry or dead-letter), compute the countdown, call `self.retry()`
> — not hidden behind a decorator argument that expands into equivalent machinery you have to
> already know about to recognize.

### A2b. A real bug manual verification against the running stack caught: the first version of `send_notification` set `retry_backoff=True`/`retry_backoff_max=600`/`retry_jitter=True` on the task decorator, called `self.retry(exc=exc)` with no `countdown=`, and every retry waited a flat 180 seconds — not the intended exponential curve. Why?

Those three options are only *automatically* consumed by Celery's `autoretry_for` decorator
wrapper (`celery/app/autoretry.py::add_autoretry_behaviour`) — it's the one that computes
`get_exponential_backoff_interval(...)` and passes the result as `countdown=` into
`task.retry()`. `Task.retry()`'s own source (`celery/app/task.py`) never reads
`self.retry_backoff` at all: `if not eta and countdown is None: countdown =
self.default_retry_delay` — and Celery's built-in `default_retry_delay` is 180 seconds. Calling
`self.retry()` explicitly, the way this task deliberately does for legibility (A2), silently
opts out of the decorator options that look like they configure it — they're real task
attributes (`self.retry_backoff_max`, `self.retry_jitter` are readable), just never consulted by
the code path this task actually calls.

> **In this repo:** caught by watching real worker logs during manual verification, not by a
> unit test — `eager_celery`-based tests only prove retry *count* and *end state* (A2's own
> caveat), never real timing, so this class of bug is invisible to the fast suite by design. The
> fix, in `apps/signals/tasks.py::send_notification`: compute the countdown explicitly with the
> *same* function `autoretry_for` would have used —
> `celery.utils.time.get_exponential_backoff_interval(factor=1, retries=self.request.retries,
> maximum=self.retry_backoff_max, full_jitter=self.retry_jitter)` — and pass it to
> `self.retry(exc=exc, countdown=countdown)`. Re-verified afterward: real jittered delays in the
> worker log (`Retry in 7s`, `Retry in 14s`, ...), not a flat repeat.

**Drill:** `dispatch_notifications` has no retry logic of its own — it's a plain `@app.task`, no
`bind=True`, no `self.retry()` anywhere. If it raises an uncaught exception (a database
connectivity blip, say), what actually happens under `task_acks_late`? Is that the right
behavior for a fan-out task specifically, or does it need the same explicit-retry treatment
`send_notification` got — and if not, what's the actual difference between the two tasks that
makes broker-level redelivery (A1) sufficient for one but not the other?

### A3. Concretely: does `send_notification` still need A1, given it now has A2?

Yes — and this is the part worth being able to say precisely, not just "redundancy is good."
A2 only engages if the task's own `except` block runs, which requires the *process* to still be
alive at the moment `channel.send()` raises. If the worker is killed *during* `channel.send()`
itself (network call hangs, `task_time_limit` sends `SIGKILL`), no exception is ever caught, no
`self.retry()` ever called, and A2 never gets a chance to protect anything. A1 is what still
guarantees the message isn't silently lost in that specific window — RabbitMQ redelivers the
original, un-acked message, and a fresh worker gets a clean attempt. Neither mechanism alone
covers both failure classes.

**Drill:** `ingest_candles` and `evaluate_strategy` (steps 3–4) rely on A1 only, never A2. Name a
concrete, realistic failure for each where adding `self.retry()` would actually help — not "it
couldn't hurt," but a specific transient failure mode A1's immediate-redelivery-of-the-same-work
doesn't handle well (hint: think about what happens if Binance's API itself starts returning 429
rate-limit responses to `ingest_candles` — does immediate redelivery make that better or worse?).

---

## B. Idempotency by construction, three times over

### B1. `User.email` (step 2), `Candle` (step 3), `StrategyEvaluation` (step 4), and `Signal` (this step) all solve "don't create a duplicate under redelivery" with the same underlying tool. Name it, and say why a `OneToOneField` counts as an instance of it rather than something different.

A **database-level uniqueness constraint** — never a check-then-save (`if not
Model.objects.filter(...).exists(): create(...)`), which has a race two concurrent transactions
can both pass before either commits. `Signal.evaluation = OneToOneField(StrategyEvaluation)` is
exactly this: Django creates a real `UNIQUE` index on the `evaluation_id` column underneath a
`OneToOneField` — the "one-to-one" relationship *is* a unique foreign key with ORM sugar on top
(a `.signal` reverse-accessor, a Python-level `RelatedObjectDoesNotExist` instead of a bare
`DoesNotExist`), not a separate mechanism from `UniqueConstraint`.

### B2. Why did `Signal` get a `OneToOneField` instead of its own `UniqueConstraint(strategy, candle_open_time)`, matching `StrategyEvaluation`'s shape directly?

Because `StrategyEvaluation` already carries that exact constraint. A `Signal` naming its own,
independent `(strategy, candle_open_time)` uniqueness would be a *second* constraint expressing
the *same* fact as the first, with no mechanism keeping them in sync if one ever changed — two
places to update, one to forget. `OneToOneField(StrategyEvaluation)` inherits the guarantee
transitively: at most one `Signal` per evaluation, and each evaluation is already at most one per
`(strategy, candle_open_time)`, so composing the two facts gives the original guarantee for free.
It's also the more honest model of what a `Signal` *is* — a decision made about an evaluation
that already exists, not an independent fact that happens to reference one.

> **In this repo:** `apps/signals/models.py`'s module docstring states this reasoning inline, and
> `tests/apps/signals/test_models.py::test_signal_uniqueness_per_evaluation_is_a_real_database_constraint`
> proves it the same way `test_email_uniqueness_is_a_real_database_constraint` (module 02) does —
> attempt the duplicate directly through the manager, inside `transaction.atomic()`, expect
> `IntegrityError`.

**Drill:** `NotificationDelivery` has `UniqueConstraint(signal, recipient)` — a *fourth* instance
of the same principle, this time not via `OneToOneField`. Why does *this* relationship need a
real `ManyToOneField`-shaped pair (`signal`, `recipient`) with a composite constraint, rather than
a `OneToOneField` the way `Signal` did? What would break if `NotificationDelivery.signal` were
made `OneToOneField` instead of a plain `ForeignKey`?

---

## C. `transaction.on_commit` — the boundary between "committed" and "safe for a task to see"

### C1. Walk through, concretely, what goes wrong if `record_signal` called `dispatch_notifications.delay(signal.id)` directly inside the `with transaction.atomic():` block, instead of via `transaction.on_commit(...)`.

`.delay()` publishes a message to RabbitMQ *immediately* — Celery has no idea a Django
transaction is open, because it isn't a Django-aware API. A worker, possibly on another machine
entirely, can pick that message up and start running `dispatch_notifications` — which begins with
`Signal.objects.get(id=signal_id)` — **before** the transaction that created that row has
actually committed. Depending on timing, that `.get()` either raises `DoesNotExist` (the row
genuinely isn't visible yet to other connections) or, worse, the surrounding transaction later
hits an unrelated error and rolls back entirely — at which point a task has already been
dispatched for a `Signal` that will never exist at all. The task doesn't get a do-over; the
message is already irrevocably in the queue.

### C2. What does `transaction.on_commit(...)` actually guarantee, and why does `record_signal`'s `except IntegrityError` branch still work correctly even though it's naturally *outside* the `atomic()` block that raised?

It registers a callback to run only once the *enclosing* transaction actually commits — and, the
detail that makes the `except` branch work, if there is **no transaction currently open**, Django
treats that as "already committed" and runs the callback immediately. `record_signal`'s `except`
branch executes after the inner `atomic()` block has already exited (successfully rolled back to
its savepoint on the expected `IntegrityError`) — at that point, whether there's an *ambient*
transaction still open depends entirely on the caller (`evaluate_strategy` doesn't wrap its whole
body in `atomic()` today), so `on_commit` correctly does the right thing either way without
`record_signal` needing to know which situation it's in.

> **In this repo:** `apps/signals/services.py::record_signal`'s docstring and ADR 0009's Decision
> section both write this out explicitly — it's the kind of correctness argument worth being able
> to reconstruct from first principles, not memorize as a rule.

### C3. A real testing gotcha this step hit directly: why did the first version of `test_record_signal_creates_a_signal_and_schedules_dispatch` see nothing happen, with no error?

`pytest-django`'s `@pytest.mark.django_db` wraps each test in a transaction that gets **rolled
back** at the end, for isolation between tests — it never actually commits. `on_commit` callbacks
only run on a real commit, so a callback registered during a normal `django_db` test is captured
by Django's connection machinery and then simply discarded when the rollback happens — no
exception, no failure, just silence. The fix is pytest-django's `django_capture_on_commit_callbacks`
fixture (wrapping Django's own `TestCase.captureOnCommitCallbacks`), used as a context manager
around the code under test with `execute=True`, which explicitly runs whatever callbacks were
registered inside it once the `with` block exits — simulating the commit a real request or task
would eventually produce, without actually needing one.

> **In this repo:** `tests/apps/signals/test_services.py`'s module docstring is written as the
> postmortem of exactly this — the same "confusing silent gap, then a specific fix" shape as
> module 02's `THROTTLE_RATES`-bound-at-import gotcha and module 03's `eager_celery` config-prefix
> bug.

**Drill:** `test_evaluate_strategy_redelivery_still_yields_exactly_one_signal`
(`tests/apps/strategy/test_tasks.py`) also needs `django_capture_on_commit_callbacks`, even though
it's testing a *different* app's task (`evaluate_strategy`) than the one that actually calls
`transaction.on_commit` (`record_signal`, in `apps/signals`). Explain why the fixture requirement
follows the *call*, not the app boundary — i.e., why any test exercising a code path that reaches
`record_signal`, regardless of which task or app initiated it, has the same gap.

---

## D. At-least-once, not exactly-once — say the actual guarantee out loud

### D1. `dispatch_notifications` re-queries `NotificationDelivery.objects.filter(status=PENDING)` after its `bulk_create`, rather than just dispatching the objects it just built in memory. Why does that specific choice matter for redelivery?

If `dispatch_notifications` itself is redelivered (crashed after the `bulk_create` committed but
before every `send_notification.delay()` call fired), a version that only iterated the in-memory
list of freshly-constructed objects would have nothing left to iterate on the second run —
`bulk_create(ignore_conflicts=True)` silently no-ops because the rows already exist, and there's
no "list of what I just created" to fall back on. Re-querying `status=PENDING` doesn't care
whether this is the first run or the fifth; it acts on "what currently needs sending," which is
exactly the question a redelivery needs answered, and it also happens to cover a `FAILED` row an
admin manually flips back via the "Retry now" action.

### D2. `send_notification` checks `if delivery.status == SENT: return` at the top. What does this guard actually prevent, and what does it *not* prevent?

It prevents **recording** a duplicate send — a second invocation that reaches this check after
the first has already written `status = SENT` returns immediately without touching the channel
again. It does **not** prevent two *concurrent* invocations from both reading `PENDING` before
either has written anything — both pass the guard, both call `channel.send()`, and (for Telegram)
the user receives the same message twice. That window requires two specific things to overlap: a
crash-triggered redelivery of `dispatch_notifications`, and a still-in-flight `send_notification`
call at that exact moment — rare, but real, and worth stating rather than implying the guard
closes it completely.

### D3. What would actually close that race, and why isn't it built here?

A claim step — `SELECT ... FOR UPDATE` to lock the delivery row and move it to some `CLAIMED`/
`IN_PROGRESS` state *before* calling the channel, so a second concurrent invocation blocks on the
lock (or observes the claimed state) instead of racing past the same `PENDING` check. This is
deliberately out of scope for this step: it's real complexity for a genuinely rare window, and
it's a preview, not a coincidence — Step 6 needs the identical lock for balance changes around
order placement, so this module previews the tool without spending the complexity budget on it
yet.

> **In this repo:** ADR 0009's Consequences section states the guarantee plainly: "this pipeline
> gives at-least-once delivery, not exactly-once." That sentence is doing real work — it's the
> difference between a system that's honest about what it guarantees and one that quietly hopes
> nobody notices the gap.

**Drill:** Telegram's `sendMessage` API has no idempotency-key parameter — there's no way to tell
it "only deliver this once even if I call you twice with the same content." Design (in words, not
code) what a `SELECT ... FOR UPDATE`-based claim step would need to look like to make the D2 race
actually safe, and identify the one thing it *still* couldn't protect against even with a perfect
lock (hint: the lock protects the database's bookkeeping — what protects the moment between
"lock acquired" and "external API call actually completes"?).

---

## E. Dead-lettering: what a database row buys you, and what it doesn't

### E1. Why is `NotificationDelivery.status = FAILED` (a Postgres row) the chosen mechanism here, rather than a RabbitMQ dead-letter exchange?

Nothing in `celery.py` declares `task_queues`/`kombu.Queue(...)` topology today — a real DLX means
new broker infrastructure (a second exchange, a second queue, `x-dead-letter-exchange` arguments
on the primary queue) for a guarantee a DB row already gives, at far lower implementation cost,
for exactly the failure mode this step needs to handle: the task ran, the external call failed
repeatedly, retries are exhausted. A DB row is also strictly *more* useful here specifically,
because it's queryable and admin-actionable ("Retry now") without needing RabbitMQ's own
management UI or API.

### E2. What's the one failure mode a DB-row dead letter genuinely can't cover, and why?

It depends entirely on the task's own Python code reaching its `except` block and executing far
enough to call `.save()`. A hard worker kill — OOM, or `task_time_limit`'s `SIGKILL` after
`task_soft_time_limit`'s gentler warning is ignored, or a crash-loop before the task body ever
runs — means no exception is ever caught and no row is ever written. Broker redelivery (section A)
takes over instead, redelivering the *original* message with whatever retry count it already
carried — and if the same hard failure recurs every time, the task loops under broker redelivery
forever, because the `>= max_retries` check living inside the function body never gets a chance to
run. A real DLX is broker-native and acts on message redelivery counts directly, independent of
whether the consuming process behaves — this is the concrete reason it's the "real world" answer
for hardening against that specific failure class.

> **In this repo:** ADR 0009 names this limit explicitly rather than presenting the DB-row
> approach as if it had no gap, and maps it forward to Step 8's "load and failure testing: ...
> worker killed mid-task" — a deliberate scope boundary, not an oversight discovered later.

---

## F. A short, concrete aside: `Signal` (this app) vs. `django.dispatch.Signal`

Django ships its own, completely unrelated concept also called a "Signal" — `django.dispatch.Signal`,
the framework underneath `pre_save`/`post_save`/`post_delete` and friends, used to let decoupled
code react to model events. **This codebase's `Signal` model has nothing to do with it** — no
`post_save` receiver, no `django.dispatch` import anywhere in `apps/signals/`. The name was kept
anyway, deliberately, because "Signal" is the term `docs/roadmap.md`, `CLAUDE.md`'s target-design
section, and ADR 0005's own forward-reference all already use consistently for the trading-alert
domain concept — inventing a synonym to dodge the collision would cost more (a codebase-wide
vocabulary mismatch with the roadmap that named this step "Signals and notifications") than the
collision itself costs (a `grep Signal` returning two unrelated things, distinguishable by import
path). Know both exist; don't confuse a domain model for a framework hook.

---

## G. Questions you should be able to ask back

1. `record_signal` is called *inline*, inside `evaluate_strategy`, rather than as its own
   dispatched task. What would change about the transaction/idempotency story in this module if
   it were instead `record_signal.delay(evaluation.id)` — a separate task, its own broker
   round-trip? What specifically would you lose?
2. `send_notification`'s `retry_backoff_max=600` caps the delay at 10 minutes. For a trading
   signal specifically — as opposed to a generic notification — is a worst-case 10-minute-plus
   delay before dead-lettering actually acceptable, or does the *content* of what's being
   retried matter for what "reasonable backoff" means?
3. `dispatch_notifications` resolves recipients via `strategy.user` — a single user per signal.
   When Step 7 ships `Plan`/`Subscription` and "fan-out per plan tier" becomes real, what has to
   change in `NotificationDelivery`'s uniqueness constraint (`signal`, `recipient`) once a single
   signal can have dozens or hundreds of recipients instead of at most two?
4. `ChannelDeliveryError` is the one exception type `send_notification`'s retry logic reacts to —
   both a non-2xx HTTP response and a connection timeout get folded into it. Is there a failure
   `TelegramChannel`/`WebhookChannel` could raise that *shouldn't* be retried at all (a genuinely
   permanent failure, not a transient one) — and if so, how would you change the exception
   hierarchy to let `send_notification` tell the two apart?
