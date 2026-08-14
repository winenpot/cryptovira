"""No `integration` marker: pure computation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cryptovira.apps.strategy.schema import Condition, StrategyConfig


def test_a_valid_config_parses() -> None:
    config = StrategyConfig.model_validate(
        {
            "conditions": [
                {"indicator": "RSI", "variables": {"timeperiod": 14}, "operator": "lt", "value": 30}
            ]
        }
    )

    assert config.conditions[0].indicator == "RSI"


def test_conditions_may_not_be_empty() -> None:
    with pytest.raises(ValidationError):
        StrategyConfig.model_validate({"conditions": []})


def test_unknown_indicator_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Condition.model_validate(
            {"indicator": "NOT_A_REAL_INDICATOR", "operator": "gt", "value": 1}
        )


def test_unknown_operator_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Condition.model_validate(
            {"indicator": "RSI", "operator": "not_a_real_operator", "value": 1}
        )


def test_unknown_top_level_key_is_rejected() -> None:
    """`extra="forbid"` — a typo'd key (`"opreator"`) must fail loudly, not silently parse as an
    unrelated no-op condition."""
    with pytest.raises(ValidationError):
        Condition.model_validate({"indicator": "RSI", "opreator": "gt", "value": 1})


def test_variables_default_to_an_empty_dict() -> None:
    condition = Condition.model_validate({"indicator": "SMA", "operator": "gt", "value": 1})

    assert condition.variables == {}
