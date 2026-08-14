# Module 04 — Strategy engine

Covers roadmap step 4: pure indicator/operator functions, a `pydantic`-validated JSON config on a
Django model, and a level-vs-edge operator distinction that fixes a real, undocumented bug in the
old system. The theme running through this module is architectural: keeping computation that
doesn't need a database honest about not needing one, and making a config schema say what it
means instead of hiding behaviour in the code that reads it.

---

## A. Why "no Django imports" is a design constraint, not a style preference

### A1. `apps/strategy/indicators.py`, `operators.py`, `schema.py`, and `engine.py` import nothing from `django`. What does that buy you that a Django-aware version wouldn't?

Testability without infrastructure, first: `tests/apps/strategy/test_indicators.py` and friends
run with no `@pytest.mark.django_db`, no `integration` marker, no Postgres — they're plain
functions over `numpy` arrays and `pydantic` models, so the fast suite (`pytest -m "not
integration"`) covers the entire decision-making core of this app. Second, and just as real:
reusability outside a Celery task. A backtest script, a notebook, a future CLI — anything that
wants to ask "would this strategy have triggered on this data" can call `engine.evaluate()`
directly with a plain array, with no Django app registry, no settings module, no database
connection to set up first.

> **In this repo:** `apps/strategy/tasks.py::evaluate_strategy` is the *only* place the pure layer
> meets the ORM — it converts a `QuerySet[Candle]` into a `numpy.ndarray` on the way in, and a
> `bool` result into a `StrategyEvaluation` row on the way out. Everything in between is Django-free.

### A2. `apps/market/sources/base.py` (step 3) is the only prior "logic without ORM" precedent in this codebase. What's actually different about how strict that boundary needs to be here versus there?

`MarketDataSource` is one `Protocol` and one value type (`Kline`) — a thin seam around network
I/O. `apps/strategy`'s pure layer is a small *system*: an indicator registry, an operator
registry, a validated schema, and an evaluation function that ties them together — four modules
that only talk to each other, never to Django, even though the thing that calls them
(`tasks.py`) very much does. The old system never drew this line at all: `core/algorithms/`'s
indicator and operator functions are pure-ish, but nothing stopped `check_rsi`/`check_macd`
(same package) from taking a Django `binance_profile` argument and mutating a DataFrame in place
— once one function in a "pure" module accepts a Django object, nothing else in that module can
be trusted to be pure either without reading it line by line.

**Drill:** grep `apps/strategy/` for the string `django` (case-insensitive, excluding
`models.py`, `admin.py`, `tasks.py`, and their tests). Confirm zero results. Then explain what
concretely would need to change in `engine.py`'s signature if `evaluate()` needed to look up a
`Currency`'s display name for an error message — and why that's a sign the lookup belongs in
`tasks.py`, not a reason to relax the boundary.

---

## B. Validating a JSON blob nobody else's code enforces the shape of

### B1. `Strategy.config` is a `JSONField`. What stops a completely malformed dict from ending up in the database?

By itself, nothing — `JSONField` accepts any JSON-serializable value. The enforcement is
`Strategy.save()` explicitly calling `self.full_clean()` before `super().save()`, which runs
`Strategy.clean()`, which parses `self.config` through `StrategyConfig.model_validate(...)`
(`apps/strategy/schema.py`) and converts a `pydantic.ValidationError` into Django's
`ValidationError` if it fails. Without that override, Django's own well-known gotcha applies:
`full_clean()` is **not** called automatically by `.save()` — only `ModelForm` (admin, DRF
`ModelSerializer` if it delegates validation) calls it for you. A bare `Strategy.objects.create(...)`
from a shell or a script would otherwise skip validation entirely.

> **In this repo:** this is the *only* model in the codebase that pays `full_clean()`'s cost on
> every save — `Currency`/`Candle` (step 3) don't. See B2 for why this one earns the exception.

### B2. Why does an invalid `Strategy.config` deserve a stronger guarantee than, say, `Currency.name` being blank?

A blank `Currency.name` is cosmetically wrong — nothing downstream breaks because of it. An
invalid `Strategy.config` is load-bearing: `evaluate_strategy` (`apps/strategy/tasks.py`) reads
it on every scheduled run for as long as the strategy is active, and a malformed condition would
fail *every single time*, discovered one `StrategyEvaluation.error` row at a time rather than at
the moment someone actually typed the bad JSON. Paying a `full_clean()` call on every `save()` is
unusual in this codebase specifically because it's unusual to have a field whose validity gates
an entire recurring pipeline rather than just describing this one row correctly.

> **In this repo:** [ADR 0008](../adr/0008-strategy-config-validation.md)'s "Enforcement timing"
> section states this trade-off explicitly, the same way ADR 0005 states why `User.email`'s
> uniqueness needed a real DB constraint rather than a serializer-only check.

### B3. `Strategy.clean()` catches `pydantic.ValidationError` and re-raises `django.core.exceptions.ValidationError`. Where else in this codebase does the exact same "catch the framework-specific exception, re-raise the framework-native one" shape appear, and why is it needed both places?

`RegisterSerializer.validate_password` (`apps/accounts/api/serializers.py`, module 02, section B2):
`django.contrib.auth.password_validation.validate_password()` raises Django's `ValidationError`,
which DRF's exception handler doesn't understand — caught and re-raised as
`rest_framework.serializers.ValidationError`. Same underlying reason both places: two different
libraries each have their own validation-error type, and whichever layer is about to hand a
response (or, here, a save) back to its caller needs the error in *that* layer's vocabulary, not
the one it was validated in. `Strategy.clean()` is doing the pydantic-to-Django version of exactly
that translation.

**Drill:** `StrategyConfig`'s `extra="forbid"` means a typo'd key (`"opreator"` instead of
`"operator"`) fails validation. Trace what `str(exc)` actually contains when that
`pydantic.ValidationError` is stringified into `Strategy.clean()`'s `ValidationError({"config":
str(exc)})` — is the resulting admin-form error message specific enough to tell an author *which*
key was wrong without them reading pydantic's source, or does something get lost in translation?
If it's not specific enough, where would you fix that — `clean()`, or a `field_validator` in
`schema.py` itself?

---

## C. AND-only, on purpose — and the bug this design deliberately doesn't repeat

### C1. `StrategyConfig.conditions` is a flat list; `engine.evaluate()` uses `all(...)` over it. Where does "every condition must hold" actually come from — is it a rewrite decision, or does it match the old system?

It matches the old system's *actual* behaviour: `old-version/core/apps/market/models/strategy.py`'s
`Strategy.is_triggerd()` loops a `triggers` list and `break`s the moment one condition fails —
functionally AND-only. The rewrite's difference isn't the semantics, it's that they're now
*true by construction* (`all(...)` over a schema-validated list) rather than an emergent property
of a loop nobody documented as AND-only. A future maintainer reading `schema.py` learns the rule
from the type, not from tracing a `for`/`break`.

> **In this repo:** [ADR 0008](../adr/0008-strategy-config-validation.md)'s Decision section
> states this explicitly: "matching the old system's *actual* semantics, not its undocumented one."

### C2. `operators.py` splits `gt`/`lt`/`eq` from `crosses_above`/`crosses_below`. What bug in the old system does this split exist specifically to avoid repeating?

`old-version/core/apps/market/constants.py`'s `OPERATOR_MAPPER` maps `"bigger"`/`"smaller"` to
plain `operator.gt`/`operator.lt` — but the actual check inside `Strategy.is_triggerd()` also
compares against the **previous** candle's value, so a condition that reads like a level check
("RSI bigger than 70") silently behaves as an edge check ("RSI just crossed above 70"). Nothing
in the config schema, the constant's name, or a comment says so. Here, `gt` is an honest level
check — `series[-1] > value`, true on every candle the condition holds — and `crosses_above` is
the edge check, spelled out as its own name.

> **In this repo:** `tests/apps/strategy/test_operators.py::test_crosses_above_fires_only_on_the_transition_candle`
> is the direct regression test — it asserts `gt`-style continued-truth is a *different* thing
> from `crosses_above`'s fire-once behaviour, by checking the same series against both.

### C3. Concretely, what goes wrong for a real strategy if an author picks `gt` when they meant `crosses_above` (or the reverse)?

`gt` (or `lt`/`eq`) re-fires on **every** evaluation tick the condition continues to hold — for a
strategy meant to catch "RSI just dropped below 30," using `lt` instead of `crosses_below` means
a `StrategyEvaluation.triggered=True` row every single tick RSI stays under 30, not once. Once
step 5 wires `Signal` creation to a triggered evaluation, that's the difference between one alert
and a flood of duplicate ones for the same underlying event. The reverse mistake
(`crosses_below` when a sustained-condition check was actually wanted) means the strategy fires
once and then goes silent even though the condition is still true — a real signal quietly missed
on every subsequent candle.

**Drill:** `_crosses_above`/`_crosses_below` read `series[-2]` and `series[-1]` — the current and
previous points of the *indicator's* output, not the raw close price. For `RSI`, is "RSI crosses
above 70" the same question as "the close price crosses above the price level RSI=70 would
imply"? Explain why indicator-space and price-space crossings are different questions, and which
one every operator in this codebase actually answers.

---

## D. TA-Lib's NaN convention as the insufficient-data signal

### D1. `INDICATORS["SMA"](close, {"timeperiod": 50})` called with 5 closes doesn't raise. What does it return, and how does `engine.py` turn that into `InsufficientDataError`?

A same-length `numpy.ndarray` of all `NaN` — TA-Lib pads the warm-up window with `NaN` rather
than raising or returning a shorter array (confirmed directly: `docs/adr/0006-ta-lib-packaging.md`'s
verification and `tests/test_talib.py`'s `test_sma_matches_a_hand_computed_value`). `engine.py`'s
`_evaluate_condition` checks `len(series) < 2 or math.isnan(series[-1])` after calling the
indicator and raises `InsufficientDataError` itself — the check is centralized once, in the one
place that knows what "not enough data yet" means for *any* indicator, rather than duplicated
inside every wrapper in `indicators.py`.

### D2. Why does the length check require at least 2 elements, not just "the last one isn't NaN"?

Because `crosses_above`/`crosses_below` read `series[-2]` as well as `series[-1]` — if the check
only guarded `series[-1]`, a series of length 1 would pass the guard and then `IndexError` inside
the edge operator. Requiring `len(series) >= 2` up front is a single, operator-agnostic guarantee
that every operator in `OPERATORS` can safely read the last two elements, whether or not it
actually needs the second one.

> **In this repo:** `operators.py`'s module docstring notes the complementary half of this: once
> the length guarantee holds, a `NaN` at `series[-2]` specifically (rather than an out-of-bounds
> read) is handled for free — `nan <= value` and `nan >= value` are both `False` in numpy, so an
> edge operator just correctly reports "no crossing," it doesn't need a special case.

**Drill:** `evaluate_strategy` fetches `HISTORY_CANDLE_COUNT = 200` candles regardless of what any
individual condition's `timeperiod` actually needs. For a strategy whose only condition is
`RSI(timeperiod=14)`, what's the practical cost of over-fetching 200 candles instead of, say, 20?
Is it worth making `HISTORY_CANDLE_COUNT` a per-strategy or per-condition value — what would that
change about `tasks.py`'s current fixed-constant design, and is the complexity worth it given
nothing has asked for it yet?

---

## E. A typing gotcha this module's tests hit: variance

### E1. `tests/apps/strategy/test_tasks.py`'s `_strategy()` helper takes `config: Mapping[str, object]`, not `config: dict[str, object]`. Passing a `dict[str, list[dict[str, object]]]` (an actual `ALWAYS_TRUE_CONFIG`-shaped value) satisfies the `Mapping` parameter but mypy rejects it against the `dict` one. Why does the *same* argument pass one and fail the other?

`dict[K, V]` is **invariant** in `V`: `dict` has `__setitem__`, so if `dict[str, list[dict]]` were
accepted anywhere a `dict[str, object]` is expected, code inside that function could legally do
`param["new_key"] = 42` (an `int` is a valid `object`) — and now the *caller's* dict, which they
still believe only holds `list[dict]` values, silently has an `int` in it too. mypy forbids the
substitution in either direction specifically to prevent that. `Mapping[K, V]` (from
`collections.abc`) has no `__setitem__` — nothing can be written through it — so there's no way to
exploit the substitution, and mypy allows `Mapping[str, object]` to accept a more specifically-typed
value like `dict[str, list[dict[str, object]]]`. This is **covariance**: safe precisely because
the interface is read-only.

### E2. What's the general rule this generalizes to, independent of `dict`/`Mapping` specifically?

Can a container be both read from *and* written to? If yes, it must be invariant in its value
type — accepting a substitution in either direction (either "more specific" or "more general") can
be exploited to store the wrong thing where a reader doesn't expect it. Can it only be read from
(no mutation possible through this particular reference)? Then it's safe to be covariant — a
`Container[Cat]` can stand in for `Container[Animal]` because every value handed back really is
an `Animal` (it's *also* a `Cat`, which is fine). The question to ask about any generic type
before assuming variance either way: "can code holding this reference write a *less specific*
value back into it?" If yes → invariant. If the interface makes that impossible → covariant is
sound.

> **In this repo:** `_strategy()`'s signature is the whole lesson in one line — it only ever
> *reads* `config` (forwards it unchanged to `Strategy.objects.create(config=config)`), so
> declaring the narrower, read-only interface it actually needs (`Mapping`) rather than the
> concrete mutable type it happens to receive (`dict`) is both more correct *and* more permissive
> to callers — the general "accept the most general type your function actually needs" principle,
> applied specifically to Python's variance rules.

**Drill:** would `list[Cat]` safely substitute for `list[Animal]` if `list` had no `append`/
`__setitem__` — i.e., if the only thing you could do with it was iterate and index-read? Compare
against `Sequence[Cat]` (from `collections.abc`, which *is* read-only and *is* covariant) to
confirm your answer, then explain concretely what `list.append` being available is what forces
`list` itself to stay invariant even though most *usage* of a given `list` in any one function
might only ever read from it.

---

## F. Questions you should be able to ask back

1. `evaluate_strategy` catches only `InsufficientDataError` and lets any other exception propagate
   to Celery's redelivery machinery. What happens on a *second* redelivery of a task that fails
   for a reason that will never resolve itself (e.g. a `Strategy.config` that was valid at save
   time but references an indicator this version of the code no longer supports)? Is there a
   dead-letter path, or does it retry forever under `task_acks_late`?
2. `StrategyEvaluation.error` is a free-text field. If a future dashboard needs to alert on
   evaluation failure *rates* per strategy, what's missing from the current schema to make that a
   cheap query rather than a full-text scan?
3. `fan_out_evaluate_strategies` queries `Strategy.objects.filter(is_active=True, interval=interval)`
   with no `.select_related("currency")`. For a deployment with thousands of active strategies on
   one interval, what would the fan-out's query pattern actually cost, and where would you fix it?
4. Step 5 will read `StrategyEvaluation.triggered=True` rows to decide when to create a `Signal`.
   Does that consumer need anything from today's `StrategyEvaluation` schema that isn't there yet
   — the actual indicator values at trigger time, for instance, so a notification can say *why* a
   strategy fired, not just that it did?
