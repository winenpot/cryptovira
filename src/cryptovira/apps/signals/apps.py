from __future__ import annotations

from django.apps import AppConfig


class SignalsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cryptovira.apps.signals"
    label = "signals"
