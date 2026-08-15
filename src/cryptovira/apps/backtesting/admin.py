"""Admin registration. Step 5.5 adds no API surface either (matching steps 3-5's precedent), so
`/admin/` is where `Backtest` rows get authored and run. Unlike `StrategyEvaluation`/`Signal`
(fully read-only audit facts), `Backtest`'s config fields (`strategy`, `start_time`, `end_time`,
`horizon_candles`) are meant to be hand-authored, the same as `Strategy` itself — only the
result/status fields that `apps/backtesting/tasks.py::run_backtest` owns are read-only, the same
split `NotificationDelivery` draws between config and system-mutated fields.

One custom action, "Run backtest", reusing `run_backtest` itself as the one operational lever —
the same shape as `NotificationDeliveryAdmin`'s "Retry now" (ADR 0009), not a parallel code path.
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from cryptovira.apps.backtesting.models import Backtest
from cryptovira.apps.backtesting.tasks import run_backtest


@admin.register(Backtest)
class BacktestAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "strategy",
        "start_time",
        "end_time",
        "status",
        "progress",
        "trigger_count",
        "win_rate",
        "updated_at",
    )
    list_filter = ("status", "strategy")
    date_hierarchy = "start_time"
    actions = ("run_backtest_action",)
    readonly_fields = (
        "status",
        "progress",
        "error",
        "trigger_count",
        "scored_trigger_count",
        "win_count",
        "win_rate",
        "total_forward_return",
        "created_at",
        "updated_at",
    )

    @admin.action(description="Run backtest")
    def run_backtest_action(self, request: HttpRequest, queryset: Any) -> None:
        for backtest_id in queryset.values_list("id", flat=True):
            run_backtest.delay(backtest_id)
