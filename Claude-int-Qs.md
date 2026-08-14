# Backend Developer (Django/DRF) — 100 Interview Questions with Answers

---

## How to use this document

**For a recruiter or hiring manager without deep Django knowledge:**

- Each question has a **model answer** — you don't need to match it word for word. You are listening for whether the candidate covers the same *ideas*, especially the ones in **bold**.
- Each section ends with **Recruiter signals** — green flags and red flags that are easy to spot without being an engineer.
- Questions get harder within each section. If a candidate struggles on the first two of a section, move on; that area is not their strength.
- **Money-related sections (H) and blockchain (I) are the differentiators** for this role. A generic Django developer can answer A–D well and still be wrong for an exchange.

**Suggested 45–60 minute screen (12 questions):** 2, 15, 17, 21, 27, 31, 38, 56, 62, 63, 70, 96.
*(Covers: async, locking, migrations at scale, transactions, rate limiting, idempotency, isolation levels, Kafka, ledger design, race conditions on money, chain reorgs, incident ownership.)*

**Scoring rough guide per question:** 0 = no idea · 1 = knows the term · 2 = correct explanation · 3 = explanation + trade-offs + a real example from their own work.

---

## Section A — Python core & concurrency (Q1–Q8)

**Q1. What is the GIL, and how does it affect how you deploy a Django application?**

The Global Interpreter Lock means only one thread executes Python bytecode at a time in CPython. It does **not** block I/O: the lock is released during network/disk waits, so threads still help for I/O-bound work (which most web requests are). CPU-bound work needs **multiple processes**. Practically: run Gunicorn/uWSGI with several worker *processes* (roughly matched to available CPU), use threaded or async workers for I/O-heavy endpoints, and push CPU-heavy work (report generation, crypto signing, large serialization) to Celery workers instead of web workers.

**Q2. When would you use asyncio, threads, or processes in a Django backend? What's the state of async in Django?**

- **asyncio/ASGI** — many concurrent I/O waits: calling blockchain RPC nodes, webhooks, external exchanges, WebSockets. Django supports async views and middleware under ASGI; the ORM is only partly async (`aget`, `acreate`, async iteration) and sync ORM calls inside async code must go through `sync_to_async(thread_sensitive=True)`, otherwise you get `SynchronousOnlyOperation`.
- **Threads** — simple parallel I/O inside a task (`ThreadPoolExecutor` fanning out to 20 nodes).
- **Processes** — genuine CPU work (hashing, signature verification, big pandas jobs).

A strong candidate also says: **mixing async views with a sync ORM often gains nothing** — the win comes when the endpoint's time is dominated by external I/O.

**Q3. You must process 10 million rows in a management command without exhausting memory. How?**

Avoid loading the queryset into memory: `.iterator(chunk_size=...)` (server-side cursor on PostgreSQL) or keyset pagination on an indexed column (`WHERE id > last_id ORDER BY id LIMIT n`) — **never `LIMIT/OFFSET`** for deep pages. Use `.only()`/`.values()` to fetch fewer columns, `bulk_update` in batches, and generators throughout so nothing accumulates. Watch out: with `DEBUG=True` Django stores every SQL query in memory, which alone can OOM a long-running script.

**Q4. What's wrong with `def f(items=[])` or `class M(models.Model): tags = models.JSONField(default=[])`?**

Default arguments are evaluated **once**, so the same list is shared across all calls — mutations leak between invocations. Django raises a warning for mutable field defaults for the same reason: you must pass a **callable** (`default=list`, `default=dict`), otherwise all model instances can share one object. Same class of bug: mutable class attributes and module-level caches shared across requests in a long-lived worker process.

**Q5. Write a retry decorator with exponential backoff. What must be true about the function you wrap?**

```python
import functools, random, time


def retry(times=3, base=0.5, exceptions=(Exception,)):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            for attempt in range(times):
                try:
                    return fn(*args, **kwargs)
                except exceptions:
                    if attempt == times - 1:
                        raise
                    time.sleep(base * 2**attempt + random.uniform(0, 0.1))

        return wrapper

    return deco
```

Key points: `functools.wraps` preserves metadata; **jitter** prevents synchronized retry storms; only retry *transient* errors (timeouts, 5xx, deadlocks), never validation errors. Critically — **the wrapped operation must be idempotent**. Retrying "broadcast withdrawal" without an idempotency key can send money twice. In production, prefer Celery's `autoretry_for`/`retry_backoff` or `tenacity` over hand-rolled code.

**Q6. Explain context managers and give a backend example beyond file handling.**

An object implementing `__enter__`/`__exit__` (or a generator with `@contextlib.contextmanager`) that guarantees cleanup even on exception. Backend examples: `transaction.atomic()`, acquiring and releasing a **PostgreSQL advisory lock** or Redis lock, temporarily switching database using `using()`, timing/tracing blocks that emit metrics, and `override_settings` in tests. A good answer mentions that `__exit__` receives the exception and can suppress it by returning `True` — and that silently swallowing exceptions there is a common bug.

**Q7. How does Django turn a class with class attributes into a database model? What are descriptors and `__slots__`?**

`ModelBase` is a **metaclass**: it intercepts class creation, collects `Field` instances, builds `_meta`, and replaces attributes with **descriptors** (objects defining `__get__`/`__set__`) — which is why `obj.related_fk` triggers a query on access and why deferred fields load lazily. `__slots__` removes per-instance `__dict__` to cut memory for objects created in the millions. Depth here is a good proxy for "will this person debug an ORM problem or just guess."

**Q8. A Celery worker's memory keeps growing until it's OOM-killed. How do you investigate?**

Confirm growth is real (container RSS, `OOMKilled` exit 137). Reproduce and profile with **`tracemalloc`**, `objgraph`, or `py-spy dump`/`memray` on a live process. Common causes: `DEBUG=True` query accumulation, module-level caches/dicts that never evict, unbounded prefetch of large querysets, reference cycles with `__del__`, C-extension leaks, and Celery prefetching too many large messages. Mitigations: fix the leak, plus `worker_max_tasks_per_child`/`--max-memory-per-child` as a safety net (a net — **not** a fix).

> **Recruiter signals — Section A**
> 🟢 Talks about processes vs threads in terms of *their* deployment; mentions profiling tools by name; brings up idempotency unprompted in Q5.
> 🔴 Says "asyncio makes Django faster" with no nuance; can't explain why retries can be dangerous; treats `max_tasks_per_child` as a solution rather than a bandage.

---

## Section B — Django ORM & query performance (Q9–Q19)

**Q9. `select_related` vs `prefetch_related`? When does neither work and you need `Prefetch`?**

`select_related` does a **SQL JOIN** in one query — for forward `ForeignKey`/`OneToOne` (many-to-one). `prefetch_related` runs a **second query** and joins in Python — for reverse FKs and `ManyToMany`. `Prefetch(...)` lets you customize the inner queryset: filter it, order it, add its own `select_related`, or store it under `to_attr`:

```python
Order.objects.prefetch_related(
    Prefetch(
        "trades",
        queryset=Trade.objects.filter(status="filled").select_related("market"),
        to_attr="filled_trades",
    )
)
```
Note that filtering a prefetched relation in Python (`[t for t in o.trades.all() if ...]`) is fine, but calling `o.trades.filter(...)` **discards the prefetch cache** and re-queries — a classic silent N+1.

**Q10. What is the N+1 query problem, how do you detect it in production, and how do you prevent regressions?**

One query to fetch N parents, then one query per parent for a relation → N+1 round trips. Detection: `django-debug-toolbar` locally, `nplusone`, query-count logging, and **APM (Elastic APM/Sentry) showing dozens of near-identical spans in one transaction**. Prevention: `select_related`/`prefetch_related`, serializer-level `get_queryset` optimization, and — the answer that separates seniors — **assert query counts in tests** with `assertNumQueries`, so a future change that reintroduces N+1 fails CI.

**Q11. When is a QuerySet evaluated? Explain `.count()` vs `len()` vs `.exists()`.**

QuerySets are lazy — they hit the DB on iteration, slicing with a step, `len()`, `list()`, `bool()`, pickling. Results are then cached on the QuerySet instance, but **re-filtering returns a new QuerySet with an empty cache**. `.count()` → `SELECT COUNT(*)`, cheap if you only need the number; `len()` fetches all rows (right choice if you'll iterate them anyway — otherwise you've done both); `.exists()` → `SELECT 1 ... LIMIT 1`, always the right way to ask "is there any?". Bonus: `COUNT(*)` on a huge table in PostgreSQL is not free — mention approximate counts from `pg_class.reltuples` for dashboards.

**Q12. `annotate` vs `aggregate`, and why did my `Count` return double the real number?**

`aggregate` collapses the whole queryset to one dict; `annotate` adds a per-row computed column. The doubling is **JOIN fan-out**: two `annotate` calls across two different multi-valued relations multiply rows. Fixes: `Count('x', distinct=True)` (correct but can be slow), or — better — compute each aggregate with an independent **`Subquery`**, or split into separate queries. A candidate who has actually been burned by this will recognize it instantly.

**Q13. Show how you'd fetch each user's most recent order in one query.**

```python
latest = Order.objects.filter(user=OuterRef("pk")).order_by("-created_at")
User.objects.annotate(
    last_order_id=Subquery(latest.values("id")[:1]),
    has_open=Exists(Order.objects.filter(user=OuterRef("pk"), status="open")),
)
```
`OuterRef` references the outer row; slicing `[:1]` is required for `Subquery`. Prefer `Exists()` over `Count(...) > 0` for existence checks — the database can stop at the first match. On PostgreSQL, `DISTINCT ON` via `.distinct("user")` with matching `order_by` is often faster still.

**Q14. Explain `F()` expressions. Does `F` alone make a balance update safe?**

`F()` refers to a column value **in the database**, so `.update(balance=F("balance") - amount)` becomes `UPDATE ... SET balance = balance - x` — one atomic statement, no read-modify-write race, no lost update. But `F` alone is **not** sufficient business-level safety: it will happily drive a balance negative. The safe pattern combines a conditional filter with a check on affected rows, plus a DB constraint as backstop:

```python
updated = Wallet.objects.filter(pk=w.pk, balance__gte=amount).update(balance=F("balance") - amount)
if updated != 1:
    raise InsufficientFunds
```
Also: after `.update()`, in-memory instances are stale (`refresh_from_db()`), and `F` expressions can't be used with `save()` and then re-read without refreshing.

**Q15. `select_for_update()` — how does it work, and what do `nowait`, `skip_locked`, and `of` do?**

It issues `SELECT ... FOR UPDATE`, taking row-level write locks held until the end of the transaction — so it **must** be inside `transaction.atomic()` (Django raises otherwise). Concurrent transactions touching the same rows block, serializing the critical section.
- `nowait=True` → error immediately instead of waiting (good for user-facing endpoints that should fail fast).
- `skip_locked=True` → ignore locked rows; the standard way to build a **queue/worker claim** pattern.
- `of=("self",)` → lock only the base table, not everything joined by `select_related`.

Caveats: not supported on all backends, doesn't lock rows that don't exist yet (use unique constraints or advisory locks for "insert if absent"), and holding locks across external API calls is a production killer — **never call a blockchain node while holding a row lock**.

**Q16. How do you avoid deadlocks when multiple transactions lock several rows?**

Acquire locks in a **globally consistent order** (e.g., always `ORDER BY id` when locking multiple wallets — a transfer between A and B must not lock A→B in one path and B→A in another). Keep transactions short, lock the minimum set of rows, avoid user-interactive or network waits inside transactions, and **expect** deadlocks anyway: catch the database error and retry the whole transaction with backoff. Monitoring `deadlock` entries in PostgreSQL logs is part of the answer.

**Q17. How do you deploy a schema migration on a 500-million-row table with zero downtime?**

Core principle: **application and schema must be compatible in both directions during the rollout**, because old and new code run simultaneously.
- Adding a nullable column, or a column with a non-volatile default, is cheap on modern PostgreSQL; adding `NOT NULL` with a backfill is not.
- Build indexes with `CREATE INDEX CONCURRENTLY` — in Django, `AddIndexConcurrently` from `django.contrib.postgres.operations` with `atomic = False` on the migration.
- Backfill in **batches** in a separate data migration or management command, not in one `UPDATE`.
- Renaming/dropping a column = multi-deploy expand/contract: add new → write to both → backfill → read from new → stop writing old → drop old.
- Set a short `lock_timeout` so a migration that can't get its lock fails fast instead of queuing behind and blocking every query.

**Q18. `bulk_create` / `bulk_update` — what do you gain and what do you lose?**

You gain far fewer round trips (`batch_size` controls statement size). You lose: `save()` is not called, `pre_save`/`post_save` **signals do not fire**, `auto_now` and custom `save()` logic are skipped, and file/related handling isn't done. On PostgreSQL `bulk_create` can return PKs; `ignore_conflicts=True` silently skips duplicates (and then you don't get PKs), while `update_conflicts` gives upsert behaviour. For ingesting blockchain transactions, upsert-on-conflict keyed by `(chain, tx_hash, log_index)` is exactly the tool you want.

**Q19. When do you drop to raw SQL, and how do you keep it safe?**

When the ORM can't express it or generates a bad plan: window functions in complex reporting, recursive CTEs, `INSERT ... ON CONFLICT` with intricate conditions, bulk set-based updates. Use `Model.objects.raw()` or `connection.cursor()` — always with **parameterized queries** (`cursor.execute(sql, [params])`), never f-strings or `%` formatting, which is straight SQL injection. Also mention: raw SQL bypasses the ORM's protections and is invisible to migrations, so it needs tests and a comment explaining why the ORM wasn't enough. `RawSQL`/`.extra()` should be a last resort.

> **Recruiter signals — Section B**
> 🟢 Reaches for `EXPLAIN`, query counts in tests, and batching without prompting; distinguishes "correct" from "fast".
> 🔴 Optimizes by adding indexes to everything; has never run a migration on a large table; thinks `select_related` and `prefetch_related` are interchangeable.

---

## Section C — Django internals & Django REST Framework (Q20–Q30)

**Q20. Walk through the request/response lifecycle. Why does middleware order matter?**

WSGI/ASGI server → `WSGIHandler` builds `HttpRequest` → middleware **request phase runs top-down** in `MIDDLEWARE` → URL resolution → view middleware → view (DRF: dispatch → authentication → permissions → throttling → handler → renderer) → **response phase runs bottom-up**. Order matters concretely: session must come before authentication (auth reads the session); `GZipMiddleware` placement affects what's compressed; CORS must be above middlewares that may short-circuit; a middleware that returns a response early prevents everything below it from running. In this role, that includes making sure the request-ID/correlation middleware is early enough to tag all downstream logs.

**Q21. When are Django signals appropriate, and when are they a mistake? What is `transaction.on_commit`?**

Signals decouple cross-cutting side effects (audit logging, cache invalidation, search index updates), especially from third-party apps you can't modify. They're a mistake when they hide **core business logic**: implicit control flow, hard to test, easy to trigger twice, they don't fire for `bulk_create`/`update()`/raw SQL, and they run **inside** the transaction — so a `post_save` handler that enqueues a Celery task can have the worker pick up a row that hasn't committed yet (or that gets rolled back).

The fix is `transaction.on_commit(lambda: task.delay(obj.pk))`, which defers until the outermost transaction commits. This is a **must-have answer** for a financial backend. (In tests, use `captureOnCommitCallbacks`.)

**Q22. Explain `transaction.atomic` — nesting, `ATOMIC_REQUESTS`, and error handling.**

`atomic()` opens a transaction; **nested `atomic()` blocks become savepoints**, so an inner block can roll back without killing the outer one. Once a database error occurs inside an atomic block, the transaction is broken — you cannot keep issuing queries; you must exit to the enclosing block (this is why catching `IntegrityError` *outside* the atomic block, or wrapping the risky part in its own inner atomic, matters). `ATOMIC_REQUESTS=True` wraps each request in one transaction — safe, but it holds locks and connections for the whole request including slow external calls, so most high-throughput services prefer explicit, narrow transactions. Never wrap external HTTP/RPC calls in a transaction.

**Q23. `Serializer` vs `ModelSerializer`. Where does validation belong, and what are the performance traps?**

`ModelSerializer` auto-generates fields from the model — fast to write, but **`fields = "__all__"` is a security smell** (leaks columns, allows mass assignment of fields like `is_staff` or `balance`); use explicit `fields` and `read_only_fields`. Validation layers: `validate_<field>` for single-field rules, `validate()` for cross-field rules, `validators` for reusable/DB-level rules. Model `clean()` is *not* called by DRF automatically. Performance traps: `SerializerMethodField` that queries per object (N+1), deeply nested serializers on list endpoints, and serializing large decimal sets — for hot read endpoints, `values()` + plain dicts or a cached payload often beats DRF serialization.

**Q24. When would you *not* use `ModelViewSet`?**

`ModelViewSet` + router is excellent for true CRUD resources. It's the wrong shape when the operation is a **business action, not a resource mutation** — placing an order, requesting a withdrawal, cancelling, confirming 2FA. Those deserve explicit endpoints (`APIView` or a `@action`) with their own serializers, permissions, throttles, and idempotency handling. A senior answer: "I don't want `PATCH /orders/{id}` to be a generic field-setter on a financial object; state changes should go through named transitions I can audit."

**Q25. Compare session auth, JWT, and HMAC-signed API keys. Which for an exchange?**

- **Session/cookie** — server-side state, easy revocation, needs CSRF protection; fine for a first-party web app.
- **JWT** — stateless and scalable, but **revocation is the hard part**: a stolen token is valid until expiry. Mitigate with short-lived access tokens + rotating refresh tokens, a denylist keyed by `jti`, `token_version` on the user, and forced invalidation on password change/logout-all.
- **HMAC API keys** (à la Binance/Kraken) — for programmatic/trading clients: key + secret, request signed with timestamp and nonce, server verifies signature and rejects stale/replayed requests. Per-key permissions (read / trade / **withdraw disabled by default**) and IP allowlisting.

Best answer: **all three coexist** — sessions or JWT for the web/mobile app, HMAC keys for the trading API, with different rate limits and scopes.

**Q26. How do you prevent one user from reading another user's orders (IDOR)?**

Never trust the URL's ID alone. Scope in `get_queryset()` (`Order.objects.filter(user=self.request.user)`) so an unauthorized ID returns 404, and add object-level permissions (`has_object_permission`, enforced via `get_object()` calling `check_object_permissions`). Extra layers: non-enumerable identifiers (UUID/ULID) so IDs aren't guessable, deny-by-default permission classes in `DEFAULT_PERMISSION_CLASSES`, and **automated tests that assert user A gets 404 on user B's objects** — this is the kind of bug that only tests catch reliably.

**Q27. Design rate limiting for a trading API. What's wrong with DRF's built-in throttling at scale?**

DRF's `AnonRateThrottle`/`UserRateThrottle` use a simple counter in the cache — good enough for basic protection, but it's a crude fixed window (burst at the boundary), per-cache-backend, and applied per-process if you use LocMem. At scale you want:
- **Redis-backed token bucket or sliding window**, atomic via a Lua script, shared across all pods.
- **Different limits per endpoint class** — order placement vs public ticker vs withdrawal — and per API key, per user, and per IP simultaneously.
- **Weight-based limits** (heavy endpoints cost more) as real exchanges do.
- Enforcement at the **edge** (Nginx/Ingress/Cloudflare) for cheap rejection of floods, so Python never sees them.
- Return `429` with `Retry-After` and expose remaining quota in headers so good clients self-regulate.

**Q28. Offset pagination vs cursor pagination — which for a trade history endpoint, and why?**

`LIMIT/OFFSET` forces the DB to scan and discard N rows, so page 10,000 is slow, and rows inserted while a user paginates cause **duplicates or skipped items**. **Cursor (keyset) pagination** — `WHERE (created_at, id) < (last_ts, last_id) ORDER BY created_at DESC, id DESC LIMIT n` — is O(page size) with the right composite index and is stable under concurrent inserts. DRF ships `CursorPagination`. For an append-heavy table like trades, cursor pagination is the correct answer; offset is acceptable only for small, bounded admin lists.

**Q29. How do you version a public API and evolve it without breaking clients?**

Pick one scheme and be consistent — URL path (`/api/v1/`) is the most operationally obvious; header/accept-based versioning is cleaner in theory, harder to debug and cache. Then: treat **additive changes as safe** (new optional fields, new endpoints) and everything else as breaking; never repurpose a field's meaning or change a numeric type/precision silently. Practices: publish an OpenAPI schema (`drf-spectacular`), a deprecation policy with sunset dates and `Deprecation`/`Sunset` headers, usage metrics per version so you know who's still on v1, and run both versions in parallel via serializer subclasses rather than `if version ==` branches sprinkled through views.

**Q30. A DRF list endpoint takes 3 seconds. Walk me through your optimization.**

Measure first — APM trace or `django-silk` to split time between SQL, Python, and external calls.
1. **Query count**: kill N+1 with `select_related`/`prefetch_related`; confirm with `assertNumQueries`.
2. **Query cost**: `EXPLAIN ANALYZE` the slow one, add/fix the composite index, replace `COUNT(*)` on huge tables (or drop pagination counts entirely via cursor pagination).
3. **Payload**: are we serializing 500 objects with nested relations? Reduce fields, flatten nesting, paginate smaller.
4. **Serialization cost**: for hot endpoints, bypass DRF serializers with `.values()`, or use `orjson`.
5. **Caching**: cache the computed response or fragments in Redis with a sane invalidation trigger (`on_commit`), and add ETag/`Cache-Control` for public data.
6. **Move work out of the request**: precompute aggregates in a materialized view or a periodic task.

Then re-measure and set an SLO/alert so the regression is caught next time.

> **Recruiter signals — Section C**
> 🟢 Mentions `on_commit`, explicit serializer fields, and object-level scoping without prompting; distinguishes first-party app auth from trading-API auth.
> 🔴 Puts business logic in signals; uses `fields = "__all__"`; can't explain why offset pagination hurts; optimizes by guessing rather than measuring.

---

## Section D — API design, idempotency & resilience (Q31–Q37)

**Q31. A user's withdrawal request times out and their client retries. How do you guarantee the money leaves once?**

**Idempotency keys.** The client sends a unique key (UUID) in a header, e.g. `Idempotency-Key`. Server side:
1. Insert `(user_id, key)` into an `idempotency_records` table with a **UNIQUE constraint** — the database, not application logic, is what makes this safe.
2. On unique-violation, the request is a replay: return the **stored original response** (same status, same body), don't re-execute.
3. Store the response and a hash of the request body once processing completes; if the same key arrives with a *different* body, return `422`/`409` — that's a client bug, not a retry.
4. Give records a TTL (24–48h) and make the whole thing work with concurrent retries (row lock or `INSERT ... ON CONFLICT DO NOTHING` + poll for the in-flight result, returning `409 Conflict` while it's still processing).

Second layer, deeper down: the on-chain broadcast itself must be idempotent — a withdrawal row with a unique reference and a state machine, so a retried Celery task never signs and broadcasts twice.

**Q32. Optimistic vs pessimistic concurrency control — pick one for a wallet, one for a user profile.**

**Pessimistic** (`SELECT ... FOR UPDATE`) locks upfront: correct and simple under high contention on the same row — use it for **wallet balance mutations**, where conflicts are expected and retrying is expensive.
**Optimistic** (a `version` column or `updated_at` check; update only if version matches, else retry) has no locks and scales better when conflicts are **rare** — use it for profile edits, settings, admin-managed configuration. State the trade-off explicitly: pessimistic risks lock waits and deadlocks; optimistic risks retry storms and lost user work if you don't handle the conflict gracefully.

**Q33. Design `POST /api/v1/withdrawals`. What does the contract look like?**

- **Request**: asset, network, address (+ memo/tag where applicable), amount as a **string** (never a JSON float), `Idempotency-Key` header, 2FA/OTP token.
- **Validation**: address checksum/format per network, amount ≥ min and ≤ per-request/daily limits, sufficient *available* balance, address allowlist and account-risk checks.
- **Behaviour**: it is **asynchronous** — the API creates a `PENDING` withdrawal, reserves (locks) the balance in the same transaction, and returns `202 Accepted` with an id and status URL. Broadcasting happens in a worker.
- **Status codes**: 202 accepted · 400 malformed · 401/403 auth or missing 2FA · 409 idempotency conflict · 422 business rule violation (insufficient funds, limit exceeded) · 429 rate limited · 503 network temporarily disabled.
- **Error body**: stable machine-readable `code`, human `message`, optional `details` — never leak internals.
- **Everything auditable**: who, when, from which IP/API key, and an immutable state history.

A candidate who answers "it returns 200 with the transaction hash" has not built a real exchange.

**Q34. You must deliver webhooks to merchant customers. What do you need to get right?**

At-least-once delivery with **exponential backoff retries** and a dead-letter state after N attempts; **signing** each payload (HMAC-SHA256 over body + timestamp, secret per customer) so receivers can verify authenticity; a **timestamp + tolerance window** to stop replay; a monotonically increasing `event_id` and delivery attempt log so consumers can **deduplicate** and detect gaps. Tell consumers explicitly that ordering is not guaranteed and that handlers must be idempotent. Operationally: per-customer queues so one slow endpoint can't stall everyone, short timeouts, circuit-breaking dead endpoints, and a manual replay tool.

**Q35. Your service calls an external node/API that becomes slow. How do you stop it taking down your API?**

- **Timeouts everywhere** (connect + read), always shorter than the caller's timeout — an unbounded `requests.get()` is how outages start.
- **Retries with backoff + jitter**, capped, and only for idempotent operations.
- **Circuit breaker**: after a failure threshold, fail fast for a cooldown, then probe with a half-open state.
- **Bulkheads**: separate connection pools/queues per dependency so one can't consume all workers.
- **Degrade gracefully**: serve cached/stale data, disable the affected feature (e.g. mark one network's deposits "delayed") rather than 500-ing the whole API.
- Never call external services **inside a DB transaction**, and never hold a row lock across the call.
- Set `statement_timeout` on the DB side too, so slow queries can't pile up.

**Q36. Two services must stay consistent (order service and wallet service) but you can't use one transaction. What do you do?**

Acknowledge that distributed two-phase commit is usually the wrong tool. Options: keep the invariant-critical operations (balance + ledger) inside **one database and one transaction** — this is a legitimate and often correct answer for an exchange; or use the **saga pattern**: a sequence of local transactions with compensating actions (reserve funds → place order → on failure, release reservation), driven by events. Combine with the **transactional outbox** so the local state change and the emitted event commit atomically, and require every consumer to be idempotent. Mention that "eventually consistent" needs a **reconciliation job** that detects and reports drift.

**Q37. Traffic grows 10×. What breaks first in a Django stack, and what's your scaling plan?**

Usually, in order: the **database** (connections, then locks, then IO), then Celery queue depth, then the app servers. Plan:
1. App tier is **stateless** — no local session/file state — so it scales horizontally behind a load balancer with an HPA.
2. Put **PgBouncer** in front of PostgreSQL; app pods × workers × threads can otherwise exceed `max_connections` instantly.
3. Move reads to **replicas** where staleness is acceptable; cache hot public data (tickers, market lists) in Redis with short TTLs.
4. Split queues by workload so slow blockchain jobs don't starve fast ones; scale workers per queue.
5. Vertical scale + partition + archive the biggest tables; add missing indexes based on `pg_stat_statements`.
6. Only then consider splitting services — and always **load test to find the next bottleneck** rather than guessing.

> **Recruiter signals — Section D**
> 🟢 Uses a unique DB constraint (not application checks) for idempotency; says "202 + async"; names timeouts and circuit breakers.
> 🔴 Assumes retries are harmless; designs synchronous money movement; answers "we'd add more servers".

---

## Section E — PostgreSQL, transactions & indexing (Q38–Q46)

**Q38. Explain transaction isolation levels and which anomalies each prevents. What does Django/PostgreSQL use by default?**

- **Read Committed** (PostgreSQL and Django default): no dirty reads; non-repeatable reads and phantoms are possible. Each *statement* sees a fresh snapshot — this is exactly why read-modify-write in Python is unsafe without a lock.
- **Repeatable Read** (in PostgreSQL, a true snapshot for the whole transaction): prevents non-repeatable reads and, in PG, phantoms too — but concurrent conflicting writes raise a **serialization failure** you must catch and retry.
- **Serializable** (SSI in PostgreSQL): behaves as if transactions ran one at a time; safest, with more aborts and retry logic required.

A strong candidate concludes: for balance operations, either take explicit row locks under Read Committed, or use Serializable **with a retry loop** — but you must pick one deliberately.

**Q39. Walk me through `EXPLAIN ANALYZE` output. When is a sequential scan fine?**

`EXPLAIN` shows the planner's plan and estimates; `ANALYZE` actually runs it and shows real times and row counts. What you look at: the node types (Seq Scan / Index Scan / Bitmap Heap Scan / Nested Loop / Hash Join), **estimated vs actual rows** — a large mismatch means bad statistics (`ANALYZE` the table, raise statistics targets, or the query is unsargable), plus loops count, and whether sorts spill to disk. `BUFFERS` shows real IO. A **sequential scan is correct** when the query touches a large fraction of a small-to-medium table — forcing an index there is slower. Red flag: a Nested Loop with a huge `loops` count, or an index existing but unused because the predicate wraps the column in a function (`WHERE lower(email) = ...` needs an expression index).

**Q40. Which index types do you use, and how do you order columns in a composite index?**

- **B-tree** — the default; equality and range, and it can serve `ORDER BY`.
- **Composite**: put **equality columns first, range/sort column last** (`(user_id, created_at DESC)` serves "this user's recent trades" perfectly). Leftmost-prefix rule: that index also serves `user_id` alone, but not `created_at` alone.
- **Partial** — `WHERE status = 'pending'`: tiny index over a hot subset, ideal for queue tables.
- **Unique / composite unique** — the real enforcement of business invariants (e.g. one deposit per `(chain, tx_hash, log_index)`).
- **GIN** — JSONB and full-text; **BRIN** — huge append-only time-ordered tables (blocks, trades) at a fraction of the size; **`INCLUDE`** columns for index-only scans.

Also mention the cost: every index slows writes and consumes cache; drop unused ones (`pg_stat_user_indexes`).

**Q41. What is MVCC, and why do long-running transactions hurt?**

PostgreSQL keeps multiple row versions so readers never block writers. Dead tuples are cleaned by **autovacuum** — but vacuum can only remove versions older than the **oldest running transaction**. So one forgotten `idle in transaction` session (or a long analytics query, or an `ATOMIC_REQUESTS` request stuck on an external call) blocks cleanup globally: tables and indexes **bloat**, plans degrade, disk grows, and in the extreme you approach transaction-ID wraparound. Mitigations: short transactions, `idle_in_transaction_session_timeout`, `statement_timeout`, monitoring `pg_stat_activity` and bloat, tuning autovacuum on hot tables, `pg_repack` when needed.

**Q42. How do you manage database connections for a Django app running 40 pods?**

Each Gunicorn worker process holds its own connection; 40 pods × 4 workers = 160 connections before Celery, and PostgreSQL's `max_connections` plus per-connection memory make that expensive. Use **PgBouncer** in **transaction pooling** mode to multiplex — but then you must know the caveats: no session-level state, so **session advisory locks, `LISTEN/NOTIFY`, and `SET` variables break**, and Django needs `DISABLE_SERVER_SIDE_CURSORS = True` (which affects `.iterator()`). `CONN_MAX_AGE` gives persistent connections (avoid `0` churn, but beware it multiplies idle connections; with PgBouncer, keep it modest). Also separate pools for web vs Celery vs analytics so a batch job can't starve the API.

**Q43. The `trades` table is 800 GB. What do you do?**

**Partition** it — declarative range partitioning by time (monthly) or hash by market — so queries prune to a few partitions, and old partitions can be detached/archived instantly instead of a `DELETE` that bloats the table. Pair with a retention policy: hot data in PostgreSQL, cold data in object storage / a data warehouse / Elasticsearch for search, with the source of truth clearly defined. Practical notes: every unique index on a partitioned table must include the partition key; migrating an existing huge table to partitioned usually means creating the partitioned table and backfilling in batches, then a short swap. Also consider BRIN indexes and summary/rollup tables (OHLCV candles) rather than aggregating raw trades on demand.

**Q44. You add a read replica and route reads to it. What breaks?**

**Replication lag** → read-after-write inconsistency: a user places an order, the UI immediately reads from the replica and it isn't there yet. Handle it by routing reads that must be fresh to the primary (Django database routers with an explicit `using("default")` or a per-request "recently wrote" flag), keeping all writes and read-modify-write flows on the primary, and never using replicas inside a transaction that also writes. Also: `select_for_update` on a replica is meaningless, migrations run only on the primary, and you need **lag monitoring with automatic fallback** when lag exceeds a threshold. Good use cases for replicas: reporting, admin panels, analytics, exports.

**Q45. Design the schema for user balances. What constraints do you rely on?**

Two related concepts: a **balances** row per `(user, asset)` with `available` and `locked` amounts, and an append-only **ledger_entries** table recording every change with a reason and reference. Constraints doing real work:
- `NUMERIC(38, 18)` (Django `DecimalField`) — **never** `float`/`double`.
- `CHECK (available >= 0 AND locked >= 0)` — the last line of defence against a code bug creating money.
- `UNIQUE (user_id, asset_id)` on balances; `UNIQUE (reference_type, reference_id)` on ledger entries for idempotency.
- Foreign keys with deliberate `ON DELETE` behaviour — financial rows are **never** hard-deleted.
- Immutability of ledger rows (no updates/deletes; enforce with permissions or a trigger).

Bonus: an invariant job asserting `balance == SUM(ledger entries)` per account, alerting on any mismatch.

**Q46. Row locks vs PostgreSQL advisory locks vs Redis locks — when do you use each?**

- **Row locks** (`SELECT ... FOR UPDATE`) — protecting rows that exist; transactional, released automatically on commit/rollback. Default choice for balance mutations.
- **Advisory locks** (`pg_advisory_xact_lock(key)`) — protecting a *logical* resource that may have no row yet: "only one sweeper per wallet", "one scanner per chain", serializing address generation. Transaction-scoped variants release automatically; **session-scoped ones break under PgBouncer transaction pooling**.
- **Redis locks** (`SET key val NX PX ttl`, released via a Lua compare-and-delete) — cross-service coordination where the DB isn't shared, or lightweight "run once" guards. Must have a TTL, must be released by the owner only, and are **not safe for money-critical mutual exclusion** — a GC pause or network partition can let two holders exist (hence fencing tokens; and why Redlock is contested). Rule of thumb: **if correctness of funds depends on it, enforce it in the database.**

> **Recruiter signals — Section E**
> 🟢 Knows the default isolation level and its consequence; talks about constraints as safety nets; mentions PgBouncer caveats.
> 🔴 "We'd just use Serializable" with no retry logic; believes an index is always faster; has never seen replication lag cause a bug.

---

## Section F — Caching, Redis & NoSQL (Q47–Q52)

**Q47. Describe your caching strategy and how you keep the cache consistent with the database.**

Default pattern is **cache-aside**: read cache → miss → read DB → populate with a TTL. Invalidate on write — and crucially **from `transaction.on_commit`**, not inside the transaction, or a rollback leaves a poisoned cache and a concurrent reader can repopulate stale data. Prefer short TTLs plus **versioned/namespaced keys** (`user:{id}:v{version}`) so invalidation is a version bump rather than hunting every key. Never cache authorization decisions or balances that must be exact — for money, the database is the only source of truth; cache the *presentation* (market lists, tickers, fee schedules, static metadata), not the ledger.

**Q48. What is a cache stampede, and how do you prevent it?**

When a hot key expires, thousands of concurrent requests miss simultaneously and hammer the database — often taking it down right after a deploy or cache flush. Mitigations: a **mutex/lock so only one request recomputes** while others serve stale or wait; **probabilistic early expiration** (recompute slightly before TTL, randomly); **TTL jitter** so keys created together don't expire together; and background refresh for critical keys (compute on a schedule, never expire, only replace). Related failure: cache-penetration on missing keys — cache negative results briefly.

**Q49. Which Redis data structures would you use in an exchange, and what are the operational gotchas?**

- **Sorted sets (ZSET)** — order books/price levels, leaderboards, ranked feeds, and sliding-window rate limiters.
- **Hashes** — compact objects (per-user session or ticker snapshot).
- **Streams** — an append-only log with consumer groups for real-time fan-out.
- **Pub/Sub** — WebSocket price broadcasts (fire-and-forget, no persistence — say this explicitly).
- **Strings + `INCR`/Lua** — counters and atomic rate limiting.

Gotchas: choose an **eviction policy** deliberately (`allkeys-lru` for a cache, **`noeviction` for a broker/queue** — evicting Celery tasks silently loses jobs); persistence trade-offs (RDB snapshots vs AOF); single-threaded, so avoid `KEYS *`, big `O(N)` commands, and huge values; separate Redis instances (or at least databases) for cache vs broker vs locks; and remember Redis is not durable enough to be the system of record.

**Q50. How would you implement "only one worker sweeps this deposit address at a time" across many pods?**

Preferably a **PostgreSQL transaction-scoped advisory lock** keyed by the address id, or a `SELECT ... FOR UPDATE SKIP LOCKED` claim pattern on the job row — both are transactional and release automatically on crash. If it must be Redis: `SET lock:{addr} {token} NX PX 30000`, release with a Lua script that deletes **only if the token matches**, and extend the TTL with a watchdog for long jobs. Explain the residual risk: if the job exceeds the TTL (or the process stalls), a second worker can acquire the lock — so the protected operation still needs to be **idempotent at the database level** (unique constraints, state machine transitions guarded by `WHERE status = 'pending'`). Locks reduce contention; constraints guarantee correctness.

**Q51. When would you choose MongoDB or another NoSQL store over PostgreSQL here?**

Justify by access pattern, not fashion. Reasonable: high-volume, schema-variable, non-transactional data — raw blockchain payloads and node responses, audit/event logs, KYC document metadata, notification history, per-user feature flags or UI state. Also time-series stores (ClickHouse/Timescale) for market data and analytics at volume. **Not** reasonable: balances, orders, ledger — anything needing multi-row ACID transactions, foreign keys and hard constraints belongs in PostgreSQL, which also handles JSONB well enough that "we need flexible schema" is rarely sufficient reason on its own. A senior answer names the cost: no joins, denormalization, and consistency guarantees you now have to implement yourself.

**Q52. How do you use Elasticsearch alongside PostgreSQL without them drifting apart?**

Elasticsearch is a **secondary index, never the source of truth** — it's near-real-time (refresh interval), has no transactions, and can lose or reorder updates. Sync options: index from `on_commit` hooks (simple, but lossy if the indexer fails), publish to Kafka via the **transactional outbox / CDC (Debezium)** and consume into ES (robust, ordered per key), or bulk reindex on a schedule. Always include: a **version/sequence number** on documents so out-of-order updates can't overwrite newer ones, idempotent document IDs, **alias-based reindexing** for mapping changes with zero downtime, and a periodic **reconciliation job** comparing counts/checksums with PostgreSQL. Use it for what it's good at — search, log/APM analytics, aggregations over huge histories.

> **Recruiter signals — Section F**
> 🟢 Says "cache the presentation, not the ledger"; knows `noeviction` for brokers; treats ES as derived data.
> 🔴 Wants to cache balances; proposes Redlock for money; picks MongoDB "because it's faster" with no access-pattern reasoning.

---

## Section G — Celery, Kafka & event-driven processing (Q53–Q60)

**Q53. Explain Celery's architecture and its delivery guarantees.**

Producer (Django) → **broker** (Redis/RabbitMQ) → worker pool → optional **result backend**. Default behaviour is `acks_early`: the worker acknowledges the message when it *starts*, so a crash mid-task loses the task. With **`acks_late=True`** (plus `task_reject_on_worker_lost`), the ack happens after completion — you get **at-least-once** delivery, meaning the same task can run twice (worker killed after the side effect but before the ack, or a Redis **visibility timeout** shorter than the task's runtime causing redelivery). There is no exactly-once. The correct conclusion: **design tasks to be idempotent**, and set the visibility timeout above your longest task.

**Q54. How do you make a task like "credit this deposit" safe to run twice?**

Idempotency at the data layer, not with flags in Python:
- A **unique constraint** on the natural key — `(chain, tx_hash, log_index)` — so a duplicate insert fails harmlessly.
- **Guarded state transitions**: `UPDATE deposits SET status='credited' WHERE id=%s AND status='confirmed'` and act only if one row was affected.
- Do the credit and the ledger entry in **one transaction** with the state change.
- Pass **IDs, not objects**, so the task re-reads current state.
- Retries with `autoretry_for`, `retry_backoff`, `retry_jitter`, `max_retries`, and a **dead-letter queue / failed state** with alerting for poison messages so a permanently failing task doesn't loop forever.

**Q55. What are the most common Celery mistakes you've seen in production?**

- Passing model instances (or whole payloads) instead of primary keys — stale or unpicklable data, huge messages.
- Enqueuing from `post_save` without `transaction.on_commit` → worker reads a row that isn't committed.
- One giant queue: slow blockchain scans starve latency-sensitive tasks. **Route by queue** and scale workers independently.
- `worker_prefetch_multiplier` left at 4 with long tasks, so messages sit in a worker's buffer while others idle — set it to 1 for long jobs.
- No time limits (`soft_time_limit`/`time_limit`), so a hung RPC call pins a worker forever.
- Unbounded retries on non-transient errors, and no monitoring of **queue depth** (the single most useful Celery metric) or task latency.
- Storing results nobody reads (`ignore_result=True` saves a lot of Redis).

**Q56. Explain Kafka topics, partitions, consumer groups, and what ordering you actually get.**

A topic is split into **partitions**; each partition is an append-only ordered log. **Ordering is guaranteed only within a partition** — so if you need per-user or per-market ordering, use that as the **message key** so it hashes to a consistent partition. A **consumer group** distributes partitions across consumers: parallelism is capped by partition count, and each partition is consumed by exactly one member. Consumers track **offsets** (commit after processing, not automatically, for at-least-once). **Rebalancing** on join/leave/crash pauses consumption and can cause duplicate processing — long-processing consumers must respect `max.poll.interval.ms` or they'll be kicked out and re-consume. Retention is time/size-based and independent of consumption, which is why you can replay history — a huge advantage over a classic task queue.

**Q57. Kafka delivery semantics — can you get exactly-once?**

Practically you design for **at-least-once + idempotent consumers**. Kafka does offer an **idempotent producer** (dedupes retries within a partition) and **transactions** for atomic write-plus-offset-commit ("exactly-once semantics") — but that guarantee ends at Kafka's boundary: the moment your consumer writes to PostgreSQL or calls a blockchain node, you're back to needing idempotency. So: unique keys on the consumer side, guarded state transitions, and dedupe on `(topic, partition, offset)` or a business key. A candidate who claims "Kafka gives exactly-once end-to-end" doesn't understand the boundary.

**Q58. You must update the database and publish an event. Why is doing both in the same function broken, and what's the fix?**

That's the **dual-write problem**: the DB commit and the broker publish are two systems with no shared transaction. If the publish fails after the commit, the event is lost; if it succeeds and the transaction rolls back, you've announced something that never happened; and `on_commit` still leaves a window if the process dies right after commit.

Fix: the **transactional outbox** — write the event into an `outbox` table **in the same transaction** as the state change, then a relay process (a poller, or **CDC with Debezium** reading the WAL) publishes rows to Kafka and marks them sent. Delivery becomes at-least-once with guaranteed durability, and consumers dedupe. Mention the alternative reading direction: **CDC straight off the DB log** when you don't want application-level events at all.

**Q59. Kafka vs RabbitMQ vs Celery — when do you reach for which?**

- **Celery (on Redis/RabbitMQ)** — background *jobs*: send email, generate a report, sweep a wallet. Per-task retries, scheduling, simple ops. Messages are consumed and gone.
- **RabbitMQ** — flexible routing, per-message acks, priorities, RPC-style messaging; a broker, not a log.
- **Kafka** — a durable, replayable **event log** with high throughput, ordered per key, multiple independent consumer groups reading the same stream, and retention that lets you rebuild a consumer from scratch. Right for trade/order event streams, audit trails, feeding Elasticsearch/analytics/risk engines, and inter-service events.

A mature answer: they coexist — Kafka as the event backbone, Celery for operational jobs — and you shouldn't force one to do the other's work.

**Q60. How do you run scheduled jobs reliably across a Kubernetes cluster?**

Exactly one scheduler must exist — Celery **beat** must run as a single replica (`replicas: 1`, `Recreate` strategy) or with a locking scheduler (`redbeat`/DB-backed with leader election); two beats = double-fired jobs. Kubernetes `CronJob` is a good alternative for isolated management commands (with `concurrencyPolicy: Forbid` and a history limit). Regardless: make each job **idempotent and re-runnable**, guard it with an advisory lock, give it a time limit, alert on *missed* runs (not just failed ones — silence is the dangerous failure), and design for clock drift/DST by using UTC and windows rather than exact timestamps. For financial jobs, log a run record with parameters so you can prove what ran when.

> **Recruiter signals — Section G**
> 🟢 Says "at-least-once, so tasks must be idempotent" unprompted; knows message keys drive ordering; mentions queue depth monitoring.
> 🔴 Believes queues deliver exactly once; puts everything on one queue; passes model objects into tasks; runs multiple beat replicas.

---

## Section H — Money, ledgers & exchange domain (Q61–Q68)

**Q61. Why can't you store balances as floats? What does correct rounding look like?**

Binary floating point can't represent decimal fractions exactly (`0.1 + 0.2 != 0.3`), and errors accumulate over millions of operations — in an exchange that means money created or destroyed. Use PostgreSQL `NUMERIC` / Django `DecimalField` and Python `Decimal` **end to end**, including JSON (serialize amounts as **strings**, because JavaScript clients will silently mangle a large float). Configure precision for the worst case (BTC 8 decimals, ETH 18 → `NUMERIC(38,18)`). Rounding must be **explicit and directional**: `quantize()` with the asset's step size, rounding in the house's favour or per exchange rules (`ROUND_DOWN` on payouts) — never "whatever the default is" — and rounding remainders must be recorded, not discarded. Watch for silent float leaks at the boundaries: JSON parsing, `float()` casts, NumPy/pandas, and some third-party APIs.

**Q62. Design a double-entry ledger. Why not just a `balance` column?**

Every movement produces **balanced entries**: debits equal credits, and money is transferred between accounts (user wallet, exchange fee account, hot wallet, liability accounts) rather than created or destroyed. An `entries` table is **append-only and immutable**: `id, transaction_id, account_id, asset, amount (signed), created_at, reference_type, reference_id`, with a unique constraint on the business reference for idempotency and a group id tying both legs together. A balance column can still exist as a **denormalized cache** for performance — but it's derived, and a periodic job must assert `balance == SUM(entries)` and alert on any drift.

Why not the column alone: no history, no auditability, no way to answer "why is this balance what it is", no way to detect or repair a bug after the fact. In a regulated financial system, **you must be able to reconstruct every balance from immutable history**.

**Q63. Two requests try to spend the same balance at the same time. Show me exactly how you prevent a negative balance.**

Layered defence — a strong candidate names more than one layer:
```python
with transaction.atomic():
    wallet = Wallet.objects.select_for_update().get(user=user, asset=asset)  # 1. row lock
    if wallet.available < amount:
        raise InsufficientFunds  # 2. business check
    wallet.available = F("available") - amount
    wallet.locked = F("locked") + amount
    wallet.save(update_fields=["available", "locked"])
    LedgerEntry.objects.create(..., reference_id=order.id)  # 3. audit trail (unique ref)
```
1. **Row lock** serializes concurrent access to that wallet.
2. A **`CHECK (available >= 0)` constraint** as the backstop — if a code path ever bypasses the lock, the database refuses.
3. **Ledger entry with a unique reference** so a retry can't double-apply.
4. Everything in **one transaction**, with no external calls inside it.

Also acceptable: conditional `UPDATE ... WHERE available >= amount` checking the affected row count (lock-free, works well under contention). The unacceptable answer is a plain `if balance >= amount` read followed by a separate save — a textbook lost update.

**Q64. What are "available" and "locked" balances, and how do they change across an order's lifecycle?**

`available` is spendable; `locked` (reserved) is committed to open orders or pending withdrawals; the user's total is the sum. Lifecycle for a limit buy: **place** → move `price × qty` (+ estimated fee) from available to locked, atomically with creating the order. **Partial fill** → decrease locked by the filled portion, credit the bought asset to available, debit fees, write ledger entries. **Cancel / expire** → return remaining locked to available. **Reject** → nothing moves. Every one of these transitions must be idempotent and produce ledger entries. Key insight to listen for: **reserve on placement, not on fill** — otherwise a user can place ten orders against the same balance.

**Q65. How does an order matching engine work, and how does a Django backend interact with it?**

Conceptually: two price-ordered books (bids descending, asks ascending), FIFO queue at each price level, matched by **price-time priority**. Real engines are typically a **single-threaded in-memory process per market** — determinism matters more than parallelism — fed by a sequenced input stream and emitting an event stream (order accepted / trade executed / order cancelled), often with an append-only journal so state can be rebuilt by replay.

Django's role is **not** to match orders in a request cycle. It: authenticates, validates, checks risk and limits, reserves balance, publishes the order to the engine (via Kafka or a gateway), and returns `202`. It then **consumes the engine's event stream** to persist trades, settle balances via the ledger, and push WebSocket updates. A candidate proposing to run matching inside a DRF view with database locks does not understand the latency or ordering requirements.

**Q66. Walk me through settling a single trade: two users, partial fill, maker/taker fees.**

In one database transaction, driven by the engine's trade event and keyed by a **unique trade id** so it's replay-safe:
1. Look up both orders, verify they're in a valid state and the fill quantity doesn't exceed remaining amounts.
2. Buyer: reduce locked quote currency by `price × qty`, credit base asset; Seller: reduce locked base by `qty`, credit quote.
3. Deduct **maker and taker fees** (different rates, possibly discounted by fee tier or paid in a native token) and credit them to the exchange fee account — as ledger entries, so fee revenue is auditable.
4. Update both orders' filled quantity and status (`partially_filled` → `filled`), releasing any leftover reservation on completion.
5. Insert the trade row and all ledger entries; assert the ledger nets to zero.
6. **After commit** (`on_commit`), publish WebSocket/webhook notifications and analytics events.

Every amount is `Decimal`, rounded per asset precision, with rounding dust accounted for rather than dropped.

**Q67. How do you prove, today, that the exchange's books are correct?**

Continuous **reconciliation and invariants**, alerting loudly on any breach:
- Per account: `balance == SUM(ledger entries)`.
- Per asset, system-wide: total user liabilities + fee accounts == sum of internal accounts (the ledger nets to zero).
- **On-chain vs internal**: sum of confirmed deposits − confirmed withdrawals ≈ actual hot + warm + cold wallet balances, with known-in-flight items explained.
- Locked balances == sum of open order reservations + pending withdrawals.
- Daily snapshot/close so any drift is bounded to one day and traceable to a transaction id.

Additional practices: immutable append-only ledger, admin actions requiring dual approval and leaving audit rows, and a "money created/destroyed" alert that pages a human. This question separates people who've worked on financial systems from those who haven't.

**Q68. Prices come from external feeds. What can go wrong and how do you protect users?**

Failure modes: a stale feed (last price frozen while the market moves), a single-source outlier or manipulated print, a provider outage, and unit/precision mismatches. Protections: **timestamp every quote and treat anything past a freshness threshold as unusable**; aggregate multiple independent sources with median/outlier rejection; circuit-break on implausible moves (price bands, deviation limits); halt the affected market rather than executing at a bad price; and make any dependent action (liquidations, conversions, portfolio valuation) refuse to run on stale data instead of guessing. Log the exact quote (source, value, timestamp) used for each decision so it can be audited afterwards.

> **Recruiter signals — Section H**
> 🟢 Reaches for Decimal, double-entry, locked-vs-available, and reconciliation naturally; says "the ledger is the source of truth".
> 🔴 Talks only about a `balance` column; ignores fees and partial fills; wants to match orders inside a web request; no answer for "how would you detect a bug that lost money last week?"

---

## Section I — Blockchain network interfaces (Q69–Q76)

**Q69. Design deposit detection for a new chain. Push or pull?**

**Pull (block scanning) is the reliable core**; webhooks/subscriptions are an optimization on top. A scanner keeps a cursor (last processed height + block hash), fetches blocks sequentially, extracts relevant transfers (matching your deposit addresses, or `Transfer` logs for tokens), and writes them idempotently keyed by `(chain, tx_hash, log_index)`. Deposits progress through a **state machine**: `seen (0 conf) → confirmed (N confs) → credited`, where **N is per-chain and per-amount** (higher value → more confirmations). Credit the user only on `confirmed`, in the same transaction as the ledger entry. Operational must-haves: the scanner is restartable and re-scannable (idempotency makes replay free), it lags a few blocks behind head, and you alert when the cursor falls behind the chain tip or when no block has been processed in X minutes — **silent scanner death is the classic exchange incident**.

**Q70. What is a chain reorganization and how does your system survive one?**

The chain switches to a different, heavier branch, so blocks you already processed are orphaned and their transactions may vanish or be re-mined in a different block. Detection: store each processed block's **hash and parent hash**; on each new block, verify its parent matches your stored tip — if not, walk back to the last common ancestor. Handling: mark deposits from orphaned blocks as reverted/unconfirmed, remove any *uncredited* provisional state, and re-scan from the fork point (idempotent inserts make this safe). The primary defence is **confirmation depth** — never credit at 0 confirmations, and pick N so that a reorg deeper than N is a serious-incident event, not a routine loss. If a credit ever must be reversed, do it as a **compensating ledger entry**, never by editing history, and escalate to humans if the funds were already withdrawn.

**Q71. How do you manage deposit addresses at scale, across UTXO, account, and memo-based chains?**

Derive addresses from an **HD wallet (BIP32/BIP39/BIP44)** — a per-user, per-chain address derived from an xpub, so the **private keys never need to be online**: the deposit service holds only the extended *public* key. Persist the derivation path with the address and enforce uniqueness. Chain-model differences matter:
- **UTXO chains (BTC)** — many addresses per user is natural; you must handle **sweeping** to hot/cold storage, UTXO selection, dust, change addresses, and fee estimation.
- **Account chains (ETH)** — per-user deposit contracts/addresses require gas to sweep (you must fund each address with native token first), and tokens vs native transfers are detected differently.
- **Memo/tag chains (XRP, XLM, TON, some exchanges' BNB)** — one shared address plus a **unique memo/destination tag per user**; a deposit with a missing or wrong memo is the #1 support ticket, so plan the manual recovery flow.

Also mention address reuse policy, address validation/checksums on withdrawal, and never trusting an address the client "computed".

**Q72. Describe a hot/warm/cold wallet architecture and the withdrawal approval flow.**

- **Hot wallet** — online, automated, holds a small percentage sufficient for normal withdrawal volume; keys in an HSM or MPC/threshold-signing service, never in application config or the database.
- **Warm** — semi-automated, requires approvals, replenishes hot.
- **Cold** — offline/air-gapped or multisig, holds the majority; withdrawals require multiple humans in different locations.

Flow: user request → validation, 2FA, allowlist and risk scoring → **auto-approve under a threshold**, manual/dual approval above it → signing service (separate service, separate credentials, its own policy engine and rate limits) → broadcast → confirm → finalize ledger. Controls to name: per-user and global velocity limits, an automatic kill switch, alerts on hot-wallet drain rate, segregation of duties (the person who can approve cannot deploy code), and full audit logs. The signing service should enforce policy **independently** of the application — so a compromised Django server cannot drain funds.

**Q73. Withdrawal broadcasting on an EVM chain: what are the hard parts?**

- **Nonce management**: nonces are strictly sequential per address. Concurrent signers cause gaps (transactions stuck pending forever) or collisions. Solution: a **single serialized signer per hot wallet** (advisory lock or a dedicated single-consumer queue), with nonces allocated from the database and reconciled against the node's pending count.
- **Stuck transactions**: gas price too low. Re-broadcast the **same nonce** with higher fees (replacement/speed-up), never a new nonce — and make sure your bookkeeping treats it as the same withdrawal.
- **Idempotency**: a retried task must never sign twice. Persist the signed transaction/hash before broadcasting, and guard the state transition (`WHERE status='pending'`).
- **Fee estimation**: EIP-1559 base fee + priority fee with caps and a maximum you're willing to pay; refuse rather than overpay in a spike.
- **Failed transactions still cost gas** — check the receipt's status field, don't assume inclusion means success.
- **Batching** (multi-send) to cut fees, plus confirmation tracking and reorg-aware finalization.

**Q74. Your RPC node provider degrades. How is the system built to cope?**

Multiple providers plus your own nodes behind an **abstraction layer** with health checks, timeouts, retries with backoff, and automatic failover; per-provider rate limiting and quota tracking. Crucially, **validate consistency**: different providers can be at different heights or briefly serve inconsistent state, so pin a scan to one provider per block range, compare heights, and refuse to advance the cursor on a node lagging behind the others. Cache immutable data (finalized blocks, receipts) so you don't re-fetch. Monitor per-provider latency, error rate, and head-block lag, and page when the scanner cursor falls behind. Running your own node gives control and no rate limits but adds real ops burden — a good candidate weighs both.

**Q75. What surprises people about ERC-20 tokens?**

Native transfers and token transfers are detected completely differently — tokens are **`Transfer` event logs from a contract**, not a value in the transaction. Beyond that: `decimals()` varies (USDT is 6, not 18) so amounts must be scaled per token; some tokens don't return a bool from `transfer` (non-standard, breaks naive integrations); **fee-on-transfer and rebasing tokens** mean the amount received ≠ the amount sent — always credit based on the actual event/balance delta; native transfers made *by a contract* (internal transactions) don't show in the normal transaction list and need trace APIs; and **anyone can create a token with the same name and symbol**, so identify assets by **contract address**, never by symbol. Also: a token transfer to an address you can't sweep (or a contract you don't control) is effectively lost — and users will send unsupported tokens to your addresses regardless.

**Q76. You'll add many chains over time. How do you structure the code, and how do you test it?**

Define a **chain-agnostic interface** — `get_block`, `get_transactions_for_addresses`, `derive_address`, `validate_address`, `estimate_fee`, `build_and_sign`, `broadcast`, `get_confirmations` — with one adapter per chain/family (EVM, UTXO, memo-based), registered via configuration so adding a chain is a plugin, not a rewrite of the core. Keep shared concerns (confirmation policy, reorg handling, ledger crediting, idempotency, state machine) in the **core**, chain quirks in adapters. Persist raw node responses for forensics. Testing: unit tests against **recorded real payloads/fixtures** (including a reorg, a failed transaction, a fee-on-transfer token, a 0-decimal token), a local node/devnet (Anvil/Hardhat/regtest) for integration, testnet for end-to-end, plus **staged rollout** for a new chain — deposits enabled before withdrawals, low limits first, and reconciliation running from day one.

> **Recruiter signals — Section I**
> 🟢 Talks about confirmations, reorgs, idempotent crediting, and nonce serialization without being led; separates the signing service from the app.
> 🔴 "We just listen for webhooks from the node provider"; credits on 0 confirmations; keeps private keys in the Django settings/database; hasn't thought about what happens when the scanner stops.

---

## Section J — Testing & CI/CD (Q77–Q81)

**Q77. What does your test suite look like for a Django financial backend, and how do you keep it fast?**

A pyramid: many fast **unit tests** for domain logic (fee calculation, order state machine, amount rounding) that don't touch the DB; a solid layer of **integration tests** for ORM behaviour, constraints, permissions and API contracts via DRF's `APIClient`; a thin layer of **end-to-end** flows (deposit → trade → withdrawal). Tooling: `pytest-django`, **factories** (`factory_boy`) over static fixtures because they're composable and explicit, `freezegun` for time, `responses`/`vcr` for HTTP. Speed: `--reuse-db`, `pytest-xdist` for parallelism, fast password hashing in test settings, avoid `TransactionTestCase` unless needed (it truncates tables), and keep the DB in tmpfs in CI. Also: **query-count assertions** and **coverage on the money paths specifically** — 90% overall coverage means nothing if the settlement code is the untested 10%.

**Q78. How do you actually test a race condition?**

You can't reproduce it with normal `TestCase`, because it wraps each test in a transaction that's never committed and rolls back — concurrent connections won't see each other's data. Use **`TransactionTestCase`** (or `pytest.mark.django_db(transaction=True)`) and drive real concurrency with threads or processes, each with its own connection, using barriers/events to force overlap at the dangerous moment, then assert the invariant (final balance, exactly one row created, no negative). Complementary approaches: a deterministic test that asserts the SQL includes `FOR UPDATE`; a test that violates the constraint directly and expects `IntegrityError`; and a **load/soak test** (Locust/k6) hammering the same wallet, checking the ledger reconciles at the end. Any candidate who has genuinely fixed a race will describe something like this.

**Q79. How do you test code that talks to a blockchain node or an external exchange?**

Isolate behind your own interface, then test at three levels: **unit** with the adapter mocked; **contract/fixture tests** replaying recorded real responses (including malformed ones, reorgs, timeouts, rate-limit errors); and **integration** against a local devnet/regtest node or a testnet in a nightly job. Rules: no network calls in the default test suite (they make CI flaky and slow), never test against mainnet with real funds, keep fixtures updated by re-recording, and make time and randomness injectable so tests are deterministic. Also test the **failure paths** explicitly — node returns a stale height, RPC times out mid-broadcast, receipt says reverted — because those are the paths that lose money.

**Q80. Design the CI pipeline for this project.**

On every pull request, in roughly this order (fail fast first): lint/format (`ruff`/`black`), type checks (`mypy`), **`makemigrations --check --dry-run`** so nobody merges a model change without a migration plus a check for conflicting migration branches, unit tests, integration tests against real PostgreSQL/Redis service containers, coverage thresholds (with a stricter gate on critical modules), and security scanning (`pip-audit`/Safety, `bandit`, secret detection, image scanning with Trivy). Then build a **single immutable image tagged with the commit SHA** that is promoted unchanged through staging → production. Speed matters: cache dependencies and Docker layers, shard tests, and keep PR feedback under ~10 minutes or people route around it. Protected branches, required reviews, and no direct pushes to main.

**Q81. How do you deploy a change safely, and what does rollback look like when migrations are involved?**

Rolling or **canary** deploys behind readiness probes, with the ability to shift a small percentage of traffic first and automatic rollback on error-rate/latency SLO breach. The hard constraint is that **code rollback is easy, schema rollback is not** — so migrations must be **backwards compatible**: expand → deploy → migrate → deploy code that uses the new shape → contract in a later release. Practically: run migrations as a separate, single-run step before the new pods take traffic; never combine a destructive migration with the deploy that stops using the column; use **feature flags** to decouple release from deploy (and to disable a chain, market, or feature instantly without a deploy); drain workers gracefully so in-flight tasks finish. Add a post-deploy verification step: error rates, queue depth, reconciliation checks green.

> **Recruiter signals — Section J**
> 🟢 Distinguishes `TestCase` from `TransactionTestCase` and knows why; mentions `makemigrations --check` in CI; separates deploy from release with flags.
> 🔴 "We test manually on staging"; mocks everything including the database; treats migrations as an afterthought in rollback.

---

## Section K — Linux, shell & production debugging (Q82–Q85)

**Q82. Production is slow, you have SSH (or a shell in a pod). Walk me through the first five minutes.**

Start broad, then narrow: `uptime`/load average vs core count, `top`/`htop` for CPU vs memory vs a single hot process, `vmstat 1` and `iostat -x 1` for IO wait, `free -m` for memory pressure and swap, `df -h`/`df -i` (a full disk or exhausted inodes is a classic silent outage), `ss -s`/`ss -tnp` for connection counts and `TIME_WAIT` buildup, and `dmesg -T | tail` for OOM kills. Then application-level: is it the database (`pg_stat_activity`, waiting locks, `pg_stat_statements`), the queue (Celery/Kafka lag), or an external dependency? Python-specific: **`py-spy top`/`py-spy dump`** on a live process to see where it's actually spending time — no restart, no code change. Above all: check the APM dashboard and recent deploys first; "what changed?" answers most incidents faster than any command.

**Q83. Write a shell one-liner to find the top 10 IPs in an access log, and tell me how you write safe scripts.**

```bash
awk '{print $1}' access.log | sort | uniq -c | sort -rn | head -10
```
For safety: start scripts with `set -euo pipefail` (exit on error, unset variables, and — importantly — failures inside pipelines), always **quote variables** (`"$var"`), use `mktemp` for temp files and `trap ... EXIT` for cleanup, prefer `find -print0 | xargs -0` for filenames with spaces, check that required commands and env vars exist up front, make scripts **idempotent and re-runnable**, and log what they do. Bonus points for knowing when to stop: once a shell script grows conditionals and parsing, rewrite it in Python.

**Q84. What happens when Kubernetes sends SIGTERM to a Gunicorn pod and a Celery worker?**

Kubernetes sends **SIGTERM**, waits `terminationGracePeriodSeconds`, then **SIGKILL** (which cannot be caught — in-flight work dies). Gunicorn should stop accepting new connections and finish in-flight requests within the grace period; the readiness probe must fail first (or a `preStop` sleep must run) so the load balancer stops sending traffic *before* shutdown, otherwise users see connection resets. Celery treats **warm shutdown** as "finish current tasks, stop consuming"; a second SIGTERM/SIGQUIT forces cold shutdown and kills running tasks — with `acks_late` those messages are redelivered, which is precisely why tasks must be idempotent. Also: your process must actually **receive** the signal — running the app under a shell wrapper as **PID 1** swallows signals and reaps no children; use `exec` in the entrypoint or an init like `tini`. Set the grace period longer than your longest task, or route long jobs to workers with their own policy.

**Q85. Your app suddenly throws "too many open files" / can't make outbound connections. What's going on?**

Each socket and file is a **file descriptor**, capped by `ulimit -n` (and container limits). Causes: not closing HTTP sessions/connections (create one `requests.Session` and reuse it, don't leak one per call), unbounded connection pools, leaked DB connections, or simply high concurrency against a low limit. Diagnose with `lsof -p PID | wc -l`, `ls /proc/PID/fd | wc -l`, and `ss -tan state time-wait | wc -l`. Related exhaustion: **ephemeral port** and `TIME_WAIT` accumulation when you open huge numbers of short-lived outbound connections — fix with keep-alive/connection pooling rather than aggressive kernel tuning. The generalizable answer: raise limits as a stopgap, but the real fix is bounded, reused pools with timeouts.

> **Recruiter signals — Section K**
> 🟢 Asks "what changed?" first; knows `py-spy`; understands graceful shutdown as a *load balancer* problem, not just a process one.
> 🔴 Only knows `top`; has never looked at a log with `awk`/`grep` beyond `tail -f`; thinks SIGKILL can be handled.

---

## Section L — Docker, Kubernetes & observability (Q86–Q91)

**Q86. What makes a good production Dockerfile for a Django app?**

**Multi-stage build** (compile wheels/build assets in a builder stage, copy only artifacts into a slim runtime) for a small image and no compilers in production. Order layers so dependencies are cached before source code. Pin base image versions (digest if you're strict), install with a lock file for reproducibility, run as a **non-root user**, use `.dockerignore` (excluding `.git`, tests, local env files), and **never bake secrets into layers** — they persist in image history even if deleted later. Entrypoint should `exec` the process so it receives signals as PID 1. Collect static at build time; run migrations **outside** the container start command (otherwise every replica races to migrate). Tag by commit SHA, not `latest`, and scan images in CI.

**Q87. Which Kubernetes objects make up this stack, and explain liveness vs readiness vs startup probes.**

Deployments for web/Celery workers/beat (beat with a single replica), Service + Ingress for routing and TLS, ConfigMap for config and Secret (ideally backed by a real secret manager) for credentials, HPA for autoscaling, PodDisruptionBudget so voluntary disruptions don't take everything down, Jobs/CronJobs for migrations and scheduled tasks, and StatefulSets only for stateful components (usually managed services instead).

Probes: **readiness** decides whether the pod receives traffic (fail it while starting up, during shutdown, or when a critical dependency is unavailable); **liveness** restarts the container if it's wedged (make it *cheap and local* — a liveness probe that checks the database will restart every pod in the fleet during a DB blip and turn a small incident into an outage); **startup** protects slow-booting apps from liveness killing them prematurely.

**Q88. Where and how do you run migrations in Kubernetes?**

As a **separate, single-execution step** — a Job (or a Helm/Argo pre-upgrade hook) that runs once before the new version rolls out — never in each pod's entrypoint, where N replicas would migrate concurrently. Even then, guard with a lock (Django's migration framework locks in some backends, but an explicit advisory lock is safer), set a `lock_timeout` so a blocked migration fails fast rather than blocking the site, and make the pipeline fail the deploy if the Job fails. Because rolling deploys mean **old and new code run at the same time**, the migration must be compatible with both — which is the expand/contract discipline. Long backfills belong in a separate, batched, resumable job, not in the deploy path.

**Q89. Your pods are OOMKilled and CPU-throttled. Explain requests, limits, and worker sizing.**

**Requests** drive scheduling and guaranteed share; **limits** are hard caps — exceeding the memory limit means the kernel kills the container (exit 137), and exceeding the CPU limit means **CFS throttling**, which shows up as mysterious latency spikes rather than errors. Common causes here: too many Gunicorn workers × per-worker memory (each worker is a full copy of the app), unbounded querysets, or memory-hungry libraries. Sizing: workers should reflect the container's **CPU limit**, not the node's core count (Python doesn't see the cgroup limit by default) — a common starting point is `2 × cpu_limit + 1` for sync workers, fewer with threads/async, then tune with real measurements. Set memory limits from observed RSS + headroom, use `--max-requests` with jitter to recycle leaky workers, and set requests close to real usage so the scheduler and HPA behave sensibly.

**Q90. How would you instrument this system so you can answer "why was checkout slow at 14:05 yesterday?"**

Three pillars, correlated: **metrics** (RED for services — rate, errors, duration; USE for resources), **structured JSON logs** to stdout, and **distributed traces**. Use **Elastic APM** (the Django agent instruments requests, ORM queries, Celery tasks, and external HTTP automatically), propagate a `trace_id`/correlation ID via middleware and into Celery task headers and Kafka message headers, and include it in every log line so a trace links to its logs. Add **business metrics**, not just technical ones: deposits credited per minute, withdrawal queue age, scanner block lag, order latency percentiles, reconciliation drift. Alert on **symptoms and SLOs** (p99 latency, error budget burn, queue depth growing) rather than raw CPU, and keep dashboards per user journey. Mention sampling and PII scrubbing — never log keys, tokens, addresses tied to identity, or full request bodies.

**Q91. A pod is in `CrashLoopBackOff`. Walk me through debugging it.**

`kubectl describe pod` (events: image pull failure, failed mount, OOMKilled, probe failures, scheduling issues), then `kubectl logs --previous` for the crashed container's output. Distinguish the classes: config/secret missing or malformed → app exits on startup; failing **liveness probe** → the app is alive but the probe is wrong or too aggressive; **OOMKilled** (exit 137) → raise limits or fix memory; dependency unreachable → check Service DNS, NetworkPolicy, and the dependency's own health; migration or entrypoint failure → check the command. Useful tools: `kubectl exec` into a running pod (or `kubectl debug`/ephemeral container when it can't stay up), `kubectl get events --sort-by=.lastTimestamp`, and comparing against the last known-good revision (`kubectl rollout history` / `undo`). The instinct to look for is **roll back first, diagnose second** when production is down.

> **Recruiter signals — Section L**
> 🟢 Knows a database check in a liveness probe is dangerous; runs migrations as a Job; sizes workers from the CPU limit; instruments business metrics.
> 🔴 Runs `migrate` in the container command; sets no limits (or identical requests/limits everywhere with no reasoning); only monitors CPU and memory.

---

## Section M — Security (Q92–Q95)

**Q92. Which vulnerability classes do you actively defend against in a Django/DRF codebase?**

- **SQL injection** — the ORM parameterizes, but raw SQL and `.extra()` don't unless you pass parameters properly.
- **Mass assignment** — `fields = "__all__"` letting a user set `is_staff`, `balance`, or `status`; always explicit fields + `read_only_fields`.
- **IDOR / broken object-level authorization** — scope every queryset to the requesting user.
- **CSRF** for cookie-authenticated endpoints; correct `SameSite`, `Secure`, `HttpOnly` cookie flags.
- **XSS** — Django autoescapes; the danger is `|safe`, `mark_safe`, and rendering user content in a JS context.
- **SSRF** — any feature that fetches a user-supplied URL (webhooks, avatars) must validate against internal ranges and metadata endpoints.
- **Insecure defaults in production** — `DEBUG=True` (leaks settings and SQL), permissive `ALLOWED_HOSTS`/CORS, missing HSTS/`SECURE_SSL_REDIRECT`.
- **Sensitive data in logs and error reports** — scrub tokens, keys, OTPs.
- **Deserialization/file upload** — never `pickle` untrusted data; validate uploaded file types and store outside the web root.

**Q93. How do you handle secrets, keys, and sensitive user data?**

Config from environment/secret manager (Vault, cloud KMS/Secrets Manager, sealed secrets) — **never in the repo, image layers, or the database**; rotate regularly and on any suspected exposure; separate credentials per environment with least privilege. Signing keys are a special category: **hardware-backed (HSM) or MPC/threshold signing in a separate service** with its own policy engine, so no application server can produce a valid transaction on its own. User data: TLS everywhere including internally, encryption at rest, application-level encryption for KYC documents and identifiers, strong password hashing (Argon2), TOTP-based 2FA with rate-limited verification and one-time recovery codes, and short-lived scoped tokens. Add access logging on sensitive reads and a data retention/deletion policy.

**Q94. An attacker has a user's password. What should stop them from withdrawing funds?**

Defence in depth beyond authentication: mandatory **2FA on withdrawal** (not just login), **address allowlists with a cooldown** before a newly added address can be used, a **withdrawal lock window** after password/2FA/email changes, per-user and global **velocity limits**, and email/push notification with a cancel link for every request. Then risk signals: new device/IP/geo, impossible travel, changed behaviour patterns — escalate to manual review or step-up verification instead of blocking blindly. Plus: rate limiting and CAPTCHA on auth endpoints, credential-stuffing detection, session invalidation on password change, separate confirmation for API-key creation, and API keys that **cannot withdraw unless explicitly enabled and IP-allowlisted**. Finally, human controls: large withdrawals require approval, and there's a kill switch.

**Q95. How do you keep dependencies and the supply chain safe?**

Pin exact versions with a **lock file** (`pip-tools`/Poetry/uv) so builds are reproducible; automated dependency updates (Dependabot/Renovate) with tests gating the merge; **vulnerability scanning** of dependencies (`pip-audit`) and images (Trivy/Grype) in CI, with a policy for critical findings; verify what you install (hashes) and be wary of typosquats and freshly published packages. Minimize the dependency surface — a small library that does one thing is easier to audit than a framework you use 5% of. Build a single signed image per commit and promote it unchanged. Keep base images patched and rebuild regularly, generate an SBOM if you're in a regulated context, and restrict who can publish to your registry and who can approve deploys.

> **Recruiter signals — Section M**
> 🟢 Treats withdrawal as a separately protected action; assumes application servers can be compromised and designs so that's survivable.
> 🔴 Security = "we use HTTPS and hash passwords"; stores keys in environment variables on the app server and sees no issue.

---

## Section N — Collaboration, ownership & judgement (Q96–Q100)

**Q96. Tell me about a production incident you owned. What happened, what did you do, what changed afterwards?**

*(Open question — you're assessing structure and honesty, not the specific outage.)* A strong answer has a clear shape: what the user impact was and how it was detected (ideally by monitoring, not by a customer), how they **stopped the bleeding first** (rollback, feature flag, disabling a chain/market) before root-causing, how they diagnosed it with evidence, and — most importantly — the **follow-through**: a blameless post-mortem, a concrete prevention item that shipped (a test, an alert, a constraint), and something they'd do differently. Listen for ownership without blame-shifting, and for whether they can say "I caused it" out loud. In a financial context, ask specifically: *did any money end up wrong, and how did you prove it afterwards?*

**Q97. What do you look for in a code review, and how do you give feedback people accept?**

Priority order that seniors converge on: **correctness and safety first** (race conditions, transaction boundaries, money paths, error handling, security), then design/maintainability, then tests, then style — style should be automated away by linters so review time isn't spent there. Good practice: review the *diff in context*, ask questions instead of issuing verdicts, distinguish **blocking issues from suggestions** explicitly (nit / consider / must-fix), explain the *why* with a reference so it's a teaching moment, approve when it's good enough rather than gatekeeping perfection, and take repeated disagreements to a synchronous conversation instead of a comment thread. Also: small PRs are the reviewer's biggest lever — a senior pushes for them.

**Q98. How do you mentor a junior developer and raise the whole team's standards?**

Concretely, not abstractly: pairing on real tasks, giving scoped-but-real ownership with a safety net, reviewing to teach rather than to correct, and letting them make reversible mistakes. Team-level leverage: writing down conventions (a contributing guide, ADRs for architecture decisions), automating standards into tooling (linters, type checks, CI gates, templates) so quality doesn't depend on who reviews, running internal walkthroughs after incidents, and improving onboarding so the next person ramps faster. The best answers include a measure of success — the junior ships independently, or review cycles shorten — and acknowledge adapting to the person rather than one fixed method.

**Q99. You disagree with a senior colleague's architecture proposal. Walk me through what you do.**

Structure to listen for: understand their reasoning and constraints first (they may know something you don't), make the disagreement about **trade-offs against explicit criteria** — latency, failure modes, operational burden, migration cost, reversibility — rather than preference, and bring evidence (a benchmark, a prototype, a failure scenario, a cost estimate). Distinguish **one-way doors from two-way doors**: fight hard about the irreversible ones, and for reversible ones, propose a small experiment. Then **disagree and commit** — once the team decides, support it properly and revisit with data if reality disagrees. Red flag: someone who either never pushes back, or who describes escalating and re-litigating every decision.

**Q100. There's pressure to ship features, and the codebase is accumulating debt. How do you decide what to fix?**

Frame debt by **impact and risk**, not aesthetics: debt that causes incidents, blocks delivery, or threatens correctness of funds gets fixed now; debt that is merely ugly but stable can wait. Make it visible — a tracked list with evidence (incident frequency, time lost, error rates), so it competes on business terms rather than "engineers want to refactor". Tactics: fix in the path of feature work (boy-scout rule), reserve a steady share of each cycle, and prefer incremental strangler-style replacement over rewrites, which usually cost more than promised. Also worth hearing: the discipline to *knowingly* take on debt with a written follow-up when speed genuinely matters — and the honesty to say some debt should just be accepted forever.

> **Recruiter signals — Section N**
> 🟢 Concrete stories with named consequences and follow-through; separates blocking from non-blocking feedback; "disagree and commit".
> 🔴 Blames others or "the previous team" for everything; describes mentoring purely as answering questions; wants to rewrite everything.

---

## Quick scorecard

| Area | Questions | Weight for this role | Must-pass |
|---|---|---|---|
| Python & concurrency | 1–8 | Medium | Q1, Q2 |
| Django ORM & performance | 9–19 | **High** | Q14, Q15, Q17 |
| Django internals & DRF | 20–30 | **High** | Q21, Q23, Q26 |
| API design & resilience | 31–37 | **High** | Q31, Q33, Q35 |
| PostgreSQL & transactions | 38–46 | **High** | Q38, Q45 |
| Caching, Redis, NoSQL | 47–52 | Medium | Q47, Q50 |
| Celery & Kafka | 53–60 | **High** | Q53, Q54, Q56 |
| Money & ledger domain | 61–68 | **Critical** | Q61, Q62, Q63 |
| Blockchain interfaces | 69–76 | **Critical** | Q69, Q70, Q72 |
| Testing & CI/CD | 77–81 | High | Q77, Q80 |
| Linux & shell | 82–85 | Medium | Q82 |
| Docker & Kubernetes | 86–91 | Medium-High | Q87, Q88 |
| Security | 92–95 | High | Q92, Q94 |
| Collaboration & judgement | 96–100 | High | Q96, Q99 |

**Three themes that run through the whole interview.** If a candidate demonstrates these repeatedly, they will do well here even where specific knowledge is thin:

1. **Idempotency and retries** — they assume everything can happen twice and design so it's safe.
2. **The database enforces truth** — constraints, transactions and locks over hopeful application logic.
3. **Failure is normal** — timeouts, reorgs, lag, crashes and partial failures are designed for, not treated as edge cases.

**A note on fairness:** nobody scores well on all fourteen areas. Someone strong in A–G, J and N with no blockchain background is a very reasonable hire — Section I is learnable in weeks by a good engineer. Someone who is weak on Sections E, G and H is a much riskier hire for an exchange regardless of how polished their Django is.
