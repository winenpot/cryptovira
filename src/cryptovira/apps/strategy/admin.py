"""Admin registration. Step 4 adds no API surface (matching step 3's `Currency`/`Candle`
precedent), so `/admin/` is the only management surface for `Strategy`; `StrategyEvaluation` is
read-only for the same reason `CandleAdmin` is — audit rows are ingest-only facts, never
hand-edited.
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from cryptovira.apps.strategy.models import Strategy, StrategyEvaluation


@admin.register(Strategy)
class StrategyAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("name", "user", "currency", "interval", "is_active", "updated_at")
    list_editable = ("is_active",)
    list_filter = ("is_active", "interval", "currency")
    search_fields = ("name", "user__email")


@admin.register(StrategyEvaluation)
class StrategyEvaluationAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("strategy", "candle_open_time", "triggered", "evaluated_at", "error")
    list_filter = ("triggered", "strategy")
    date_hierarchy = "evaluated_at"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any | None = None) -> bool:
        return False
