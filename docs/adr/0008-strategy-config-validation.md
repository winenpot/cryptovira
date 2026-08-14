# ADR 0008 — Strategy config: pydantic validation on every save, AND-only, explicit operators

**Status:** Accepted · 2026-08-14

## Context

Step 4 needs a `Strategy` model whose behaviour is driven entirely by a JSON config a user
authors. `old-version/core/apps/market/models/strategy.py`'s `data = JSONField(default=dict)` is
the same idea, and it shows exactly what happens when that JSON is trusted rather than validated:

- Nothing validates `Strategy.data`'s shape before it's used. A malformed `triggers` entry is
  discovered only when `Strategy.is_triggerd()` runs against it — at evaluation time, in
  production, against real market data — not when it was authored.
- `Strategy.is_triggerd()` loops the `triggers` list and `break`s on the first failed condition.
  This is AND-only chaining, but it's never stated as a rule anywhere — a config author, or a
  future maintainer reading the JSON schema alone, has no way to know OR isn't supported short of
  reading the evaluation loop itself.
- `constants.py`'s `OPERATOR_MAPPER` maps `"bigger"`/`"smaller"` to plain `operator.gt`/`lt`, but
  the actual check in `is_triggerd()` (`current_operator_condition and not
  previous_operator_condition`) also compares against the *previous* candle — so a config key
  that reads as a level check ("RSI bigger than 70") silently behaves as an edge check ("RSI just
  crossed above 70"). Nothing documents this; it's discoverable only by reading the method body.

## Decision

**Validation.** `Strategy.config` is validated by a `pydantic.BaseModel` schema
(`apps/strategy/schema.py`: `Condition` + `StrategyConfig`, both `extra="forbid"`) — the same
tool `cryptovira.config.Settings` already uses for "validate untrusted structured input at a
boundary," rather than a new `jsonschema` dependency or hand-rolled checks. `extra="forbid"`
specifically: unlike `Settings` (`extra="ignore"`, because `.env` legitimately carries platform
variables this app doesn't read), a hand-authored strategy config has no legitimate unknown
keys — a typo'd `"opreator"` must fail validation immediately, not silently parse as a no-op.

**Enforcement timing.** `Strategy.save()` is overridden to always call `self.full_clean()` — the
only model in this codebase that pays that cost on every save (`Currency`/`Candle` don't).
Justification: an invalid config isn't cosmetically wrong the way a blank optional field would
be — it would silently break every future `evaluate_strategy` run for that row, discovered one
`StrategyEvaluation.error` at a time instead of at the point of authorship. That asymmetry (config
validity gates a whole recurring task pipeline, not just this one row's correctness) is what
justifies the stronger, less-conventional guarantee. `Strategy.clean()` catches pydantic's
`ValidationError` and re-raises Django's — the same shape as
`RegisterSerializer.validate_password`'s `except DjangoValidationError as exc: raise
serializers.ValidationError(...) from exc` (`apps/accounts/api/serializers.py`), the two
frameworks swapped.

**AND-only chaining.** `StrategyConfig.conditions` is a flat list, every condition required —
matching the old system's *actual* semantics (loop-and-break-on-first-failure), not its
undocumented one. OR-groups or nested boolean trees are not modelled; if a real strategy needs
them, that's a schema extension driven by an actual use case, not a speculative one built now.

**Explicit level vs. edge operators**, replacing the old system's hidden crossing behaviour:
`apps/strategy/operators.py` splits `gt`/`lt`/`eq` (level — true every evaluation while the
condition holds) from `crosses_above`/`crosses_below` (edge — true only on the transition
candle). An author who wants "RSI above 70 right now" writes `gt`; an author who wants "RSI just
crossed above 70" writes `crosses_above`. The two produce genuinely different signal frequencies
(a level check re-fires every candle the condition holds; an edge check fires once), and picking
the wrong one for a real strategy is a meaningful, silent difference in behaviour — worth two
named operators, not one operator with a hidden mode nothing documents.

**One indicator registry, not two.** `apps/strategy/indicators.py`'s `INDICATORS: dict[str,
IndicatorFn]` is a plain, explicit, typed dispatch table (`SMA`, `EMA`, `RSI`, `MACD`/
`MACD_SIGNAL`/`MACD_HIST`) — replacing the old system's *two* indicator layers
(`core/algorithms/indicators.py`'s hand-written wrappers, which reimplemented MACD/TRIX instead
of calling TA-Lib's own, plus a second, separate dynamic `talib.abstract.Function(name)`
introspection dispatcher in `core/algorithms/__init__.py`). Adding an indicator later is one
registry entry, not a second code path to keep in sync with the first.

## Consequences

- A strategy author (today: admin-only, per step 4's scope — no API surface yet) gets a precise
  validation error naming the offending key at the moment they save, not a mysterious empty
  evaluation history discovered later.
- `evaluate_strategy` (`apps/strategy/tasks.py`) never has to defend against a malformed
  `config` — `full_clean()` has already guaranteed validity by the time a `Strategy` row exists,
  so `InsufficientDataError` (not enough candle history yet) is the only expected runtime failure
  left to handle.
- Divergence detection and candlestick-pattern matching — real features of the old system's
  operator layer — are out of scope. `IndicatorName`/`OperatorName` are closed `Literal` types
  today; adding either later is an additive extension, not a breaking schema change, when a real
  consumer needs them.
- `risk_ratio`/`leverage`/`quantity`-style fields stay off `Strategy` even though ADR 0005 names
  `Strategy` as their eventual home — those are order-sizing parameters for step 6, an additive
  migration when that step actually needs them, not a reason to widen this schema now.

## We would revisit if

A real strategy needs OR-groups or nested condition trees (at which point `StrategyConfig` grows
a recursive shape, likely `AnyOf`/`AllOf` wrapper nodes around `Condition`), or divergence/pattern
detection gets a real consumer in a later step.
