# ADR 0009 — Signal idempotency, transactional commit ordering, and at-least-once delivery

**Status:** Accepted · 2026-08-14

## Context

Step 5 needs to turn a triggered `StrategyEvaluation` into a `Signal`, and a `Signal` into a
delivered notification — redelivery-safely, with retry and a recorded failure when delivery
permanently fails. `old-version/`'s equivalent (`Signal.objects.create_signal_from_strategy`,
called synchronously inside the evaluation task) got the shape right but the guarantees wrong:

- **No transaction, no idempotency key around `Signal` creation.** A redelivered evaluation task
  would create a duplicate `Signal` — nothing prevented it.
- **No retry, no backoff, no dead-letter around notification sending.**
  `core/apps/account/tasks.py::send_message` caught a failed Telegram send, logged it, and moved
  on. The recipient simply never got their alert, with no record that it had failed.

This ADR covers both halves as one causal decision — the idempotency mechanism, the transaction
ordering that makes it safe to trigger from, and the retry/dead-letter design are one story
("how does an evaluation become a delivered notification, exactly once as far as we can
guarantee, with a recorded, actionable failure when it can't be"), not three independent choices.

## Decision

**`Signal.evaluation` is a `OneToOneField(StrategyEvaluation)`, not a fresh `UniqueConstraint`.**
A `OneToOneField` already puts a `UNIQUE` index on `evaluation_id`; since `StrategyEvaluation` is
itself uniquely keyed on `(strategy, candle_open_time)` (ADR 0008), this transitively guarantees
"at most one `Signal` per (strategy, candle_open_time), ever" without a second constraint to keep
in sync with the first — and it's semantically honest: a `Signal` *is* the notification-worthy
subset of evaluations, not an independent fact.

**`record_signal()` is a plain function, not a Celery task, called inline from
`evaluate_strategy`.** This matches the target-design pipeline (evaluate → create `Signal` in a
transaction → dispatch notification) as one continuous synchronous step, with the async boundary
appearing only *after* the `Signal` is durably committed:
```python
def record_signal(evaluation: StrategyEvaluation) -> Signal:
    try:
        with transaction.atomic():
            signal = Signal.objects.create(evaluation=evaluation)
    except IntegrityError:
        signal = Signal.objects.get(evaluation=evaluation)
    transaction.on_commit(lambda: dispatch_notifications.delay(signal.id))
    return signal
```
The `IntegrityError` catch is scoped to its own nested `atomic()` — the same shape
`test_email_uniqueness_is_a_real_database_constraint` (ADR 0005) already established — so the
expected, handled "already recorded" case only rolls back to a savepoint, not any ambient outer
transaction. `transaction.on_commit(...)` runs unconditionally after *both* branches, not just
the `try`: if it only ran on the create path, a crash between the `Signal` committing and its
`on_commit` callback firing — followed by `task_acks_late` redelivering the whole
`evaluate_strategy` task — would hit the `IntegrityError` branch on redelivery and silently never
dispatch notifications at all. The cost is `dispatch_notifications` can run more than once for
the same signal; its own idempotency (below) already has to absorb that.

**Retry uses Celery's own `self.retry(...)` with `bind=True`, explicitly — not `autoretry_for`.**
The explicit form keeps the catch, the max-retry check, and the retry call visible in one
function body rather than behind a decorator argument. **This surfaced a real bug during manual
verification against the running stack, not just a style preference**: `retry_backoff`/
`retry_backoff_max`/`retry_jitter` are only *automatically* applied by Celery's `autoretry_for`
wrapper, which computes the countdown itself and passes it to `task.retry()`. Called explicitly,
`Task.retry()`'s own source has no reference to those options at all — `if not eta and countdown
is None: countdown = self.default_retry_delay` — so the first version of this task silently fell
back to a flat 180-second delay on every retry, observed directly in worker logs
(`Retry in 180s`, unchanging across five retries) instead of the intended exponential curve. The
fix keeps the explicit `self.retry()` call but computes the countdown with the exact function
Celery's own `autoretry_for` wrapper uses (`celery.utils.time.get_exponential_backoff_interval`)
and passes it explicitly — reusing Celery's algorithm, not reinventing it, while keeping the
decision visible. Re-verified after the fix: real jittered delays (`Retry in 7s`, `14s`, ...),
`attempts` landing at exactly `max_retries + 1` before dead-lettering.

This is also the first task in this codebase distinguishing two *different* failure-recovery mechanisms
that were already both present but never both load-bearing at once: broker-level redelivery
(`task_acks_late` — the worker process itself died, RabbitMQ redelivers the same message
immediately, no delay) versus task-level retry (the task ran, caught an exception itself, and
asked Celery to schedule a *new* message with `retry_backoff`-computed delay). `send_notification`
needs both — (b) for "Telegram is briefly down," (a) still covering "the worker died mid-send."

**Dead-lettering is an application-level `NotificationDelivery.status = FAILED` row**, once
`self.request.retries >= self.max_retries`, not a RabbitMQ dead-letter exchange. Nothing in
`celery.py` declares `task_queues`/`kombu.Queue` topology today, and a DB row gives the same
practical guarantee (a Postgres-visible, admin-actionable record) at far lower cost for the
failure mode this step targets — the task ran, the external call failed repeatedly, retries
exhausted. **Named limit**: this only works if the task's own code reaches its `except` block. A
hard worker kill (OOM, `task_time_limit`'s `SIGKILL`) means no row is ever written and broker
redelivery just keeps retrying the original message forever, since the `>= max_retries` check
never gets a chance to run. A real DLX is broker-native and doesn't depend on task code executing
— deliberately out of scope for this step (maps to Step 8's "worker killed mid-task" testing).

**Channels: `TelegramChannel`/`WebhookChannel` as thin project-owned `httpx` clients** — directly
reusing ADR 0007's precedent over a heavy SDK (`python-telegram-bot`/`telethon`, both carried by
the old system for reasons lost to history; its actually-working path was always raw
`requests.post`). No `sms` value on `Channel` — no chosen provider, would be dead code; additive
later, not a migration.

## Consequences

- **This pipeline gives at-least-once delivery, not exactly-once**, and that's stated plainly
  rather than implied. `dispatch_notifications` re-queries `status=PENDING` (not just
  just-created rows) so it's redelivery-safe on its own; `send_notification`'s `status == SENT`
  guard prevents *recording* a duplicate send but not necessarily *sending* one twice if two
  invocations both pass that check before either writes `SENT`. Closing that fully needs a
  `SELECT ... FOR UPDATE` claim step — a preview of the exact lock Step 6 will use for balance
  changes, deliberately not built here for a genuinely rare crash-and-redeliver window.
- `apps/common/models.py`'s `TimestampedModel` docstring is corrected: `Signal` was forward-guessed
  there in Step 3 as a future user; its actual shape (append-only, `OneToOneField`-keyed) means it
  isn't one. `NotificationDelivery` is — the first model in this codebase where `updated_at`
  reflects the system mutating a row across retries, not a human occasionally editing config.
- A "Retry now" admin action on `NotificationDelivery` reuses `send_notification` itself as the
  one operational lever for a dead-lettered row, rather than a new code path or a status-editing
  field that would let admin become a second writer around the state machine `send_notification`
  owns.

## We would revisit if

A real RabbitMQ DLX becomes necessary (hard-kill resilience genuinely matters in practice, per
Step 8's load/failure testing), or the double-send race under concurrent redelivery turns out to
be more than theoretical (at which point `SELECT ... FOR UPDATE` around delivery claiming is the
fix, not a redesign) — or "fan-out per plan tier" becomes real once Step 7 ships `Plan`, at which
point `dispatch_notifications`'s recipient query grows from `strategy.user` to something
tier-driven, without needing to touch the delivery/retry/dead-letter machinery at all.
