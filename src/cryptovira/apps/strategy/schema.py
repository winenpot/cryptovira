"""The shape of `Strategy.config`. No Django imports — validated with `pydantic`, the same tool
`cryptovira.config.Settings` already uses to validate untrusted structured input at a boundary;
there's no `jsonschema` dependency in this project and no reason to add a second validation
library for the same job.

Named `schema.py`, not `config.py`: `cryptovira/config.py` already owns "typed env settings read
once at boot," and reusing that name here — for "validate a JSON blob on every model save" — would
make `grep config` ambiguous between two unrelated things.

`conditions` is a flat, AND-chained list — every condition must hold for the strategy to trigger.
This matches the old system's *actual* behaviour (`Strategy.is_triggerd()` looped a `triggers`
list and broke on the first failure), not its documented intent, since it was never documented as
AND-only anywhere. OR-groups or nested boolean trees are explicit future work, not modelled here.

`extra="forbid"` on both models: unlike `Settings` (which uses `extra="ignore"` because a `.env`
file legitimately carries platform variables unrelated to this app), a hand-authored strategy JSON
has no legitimate unknown keys — a typo'd `"opreator"` should fail validation immediately, not be
silently ignored as a no-op condition.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

IndicatorName = Literal["SMA", "EMA", "RSI", "MACD", "MACD_SIGNAL", "MACD_HIST"]
OperatorName = Literal["gt", "lt", "eq", "crosses_above", "crosses_below"]


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator: IndicatorName
    variables: dict[str, int] = Field(default_factory=dict)
    operator: OperatorName
    value: float


class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conditions: list[Condition] = Field(min_length=1)
