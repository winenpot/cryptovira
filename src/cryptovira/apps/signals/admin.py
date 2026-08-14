"""Admin registration. Step 5 adds no API surface either (matching steps 3 and 4's precedent), so
`/admin/` is where `NotificationRecipient` rows get managed. `Signal` is read-only, like
`CandleAdmin`/`StrategyEvaluationAdmin` — an audit fact, never hand-edited.
`NotificationDelivery` is read-only too, but with one custom action ("Retry now"): the one
operational lever a dead-lettered row needs, reusing `send_notification` itself rather than a
new code path — deliberately not a bulk "resend all failed" and not a status-editing field,
which would let admin become a second write path around the state machine `send_notification`
owns.
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from cryptovira.apps.signals.models import NotificationDelivery, NotificationRecipient, Signal
from cryptovira.apps.signals.tasks import send_notification


@admin.register(Signal)
class SignalAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("evaluation", "created_at")
    date_hierarchy = "created_at"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any | None = None) -> bool:
        return False


@admin.register(NotificationRecipient)
class NotificationRecipientAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("user", "channel", "destination", "is_active", "updated_at")
    list_editable = ("is_active",)
    list_filter = ("channel", "is_active")
    search_fields = ("user__email", "destination")


@admin.register(NotificationDelivery)
class NotificationDeliveryAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("recipient", "signal", "status", "attempts", "updated_at")
    list_filter = ("status", "recipient__channel")
    actions = ("retry_now",)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any | None = None) -> bool:
        return False

    @admin.action(description="Retry now (dispatches send_notification again)")
    def retry_now(self, request: HttpRequest, queryset: Any) -> None:
        for delivery_id in queryset.values_list("id", flat=True):
            send_notification.delay(delivery_id)
