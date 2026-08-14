"""Admin registration for market data.

Step 3 adds no API surface, so `/admin/` is the only way staff control which symbols get
ingested — hence `CurrencyAdmin.list_editable` on `is_active`. `Candle` rows are ingest-only
facts (see the idempotency note on `Candle` itself); `CandleAdmin` is read-only so admin can
never become a second write path that bypasses the unique-constraint/`bulk_create` model.
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from cryptovira.apps.market.models import Candle, Currency


@admin.register(Currency)
# django-stubs types ModelAdmin as generic for annotation purposes only; the real runtime class
# has no __class_getitem__, so `ModelAdmin[Currency]` would raise TypeError at import time
# (same situation as accounts/admin.py's UserAdmin).
class CurrencyAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("symbol", "name", "is_active", "created_at")
    list_editable = ("is_active",)
    list_filter = ("is_active",)
    search_fields = ("symbol", "name")


@admin.register(Candle)
class CandleAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("currency", "interval", "open_time", "close", "volume")
    list_filter = ("currency", "interval")
    date_hierarchy = "open_time"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any | None = None) -> bool:
        return False
