from __future__ import annotations

from django.apps import AppConfig


class StrategyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cryptovira.apps.strategy"
    label = "strategy"
