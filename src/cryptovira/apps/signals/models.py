"""`Signal` (a triggered, notification-worthy evaluation), where to deliver it
(`NotificationRecipient`), and the per-recipient delivery attempt (`NotificationDelivery`).

Design notes worth knowing cold for an interview — see
docs/interview/05-concurrency-and-correctness.md for the full walkthrough:

- `Signal.evaluation` is a `OneToOneField`, not a fresh `UniqueConstraint`. A `OneToOneField`
  already puts a `UNIQUE` index on the FK column, and since `StrategyEvaluation` is itself
  uniquely keyed on `(strategy, candle_open_time)` (see apps/strategy/models.py), this
  transitively guarantees "at most one Signal per (strategy, candle_open_time), ever" — the same
  redelivery-safety `Candle`/`StrategyEvaluation` get from their own constraints, inherited here
  rather than duplicated.
- `NotificationDelivery` is the first model in this codebase where `TimestampedModel`'s
  `updated_at` carries real information: every earlier user of it (`Currency`, `Strategy`) is
  occasionally-edited config, and every append-only fact so far (`Candle`, `StrategyEvaluation`,
  `Signal` here) never changes after creation. A delivery's `status`/`attempts`/`last_error`
  genuinely mutate across retries — `updated_at` means "when was the last delivery attempt,"
  distinct from `created_at`'s "when was this delivery first queued."
- Note for anyone grepping this codebase: this `Signal` is a domain model (a trading alert) and
  has nothing to do with Django's own `django.dispatch.Signal` (the `pre_save`/`post_save` event
  framework). The name collision is real but harmless — nothing here uses Django's signal
  dispatch, and "Signal" is the term the roadmap and ADR 0005 already use consistently.
"""

from __future__ import annotations

from django.db import models

from cryptovira.apps.accounts.models import User
from cryptovira.apps.common.models import TimestampedModel
from cryptovira.apps.strategy.models import StrategyEvaluation


class Signal(models.Model):
    """Append-only, like `Candle`/`StrategyEvaluation` — never edited after creation, so no
    `TimestampedModel` (an `updated_at` that always equals `created_at` would misrepresent it)."""

    evaluation = models.OneToOneField(
        StrategyEvaluation, on_delete=models.CASCADE, related_name="signal"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"Signal for {self.evaluation}"


class Channel(models.TextChoices):
    """Only channels with a real implementation behind them (see `channels/__init__.py`). No
    `SMS` value — no chosen provider, and an enum member with nothing behind it is dead code.
    Adding a channel later is an additive choices change, not a migration risk."""

    TELEGRAM = "telegram", "Telegram"
    WEBHOOK = "webhook", "Webhook"


class NotificationRecipient(TimestampedModel):
    """Where to actually deliver a signal for a given user — deferred here all the way back in
    ADR 0005 ("Telegram linkage → the notifications app (step 5)... its own model with a
    ForeignKey(User), not a column bolted onto identity"). Live-edited config (a user links or
    unlinks a destination), the same `TimestampedModel` shape as `Currency`/`Strategy`."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notification_recipients")
    channel = models.CharField(max_length=20, choices=Channel.choices)
    destination = models.CharField(
        max_length=255, help_text="Telegram chat id, or a webhook URL, depending on `channel`."
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("user", "channel")
        constraints = (
            models.UniqueConstraint(
                fields=("user", "channel"), name="unique_recipient_per_user_channel"
            ),
        )

    def __str__(self) -> str:
        return f"{self.user.email} via {self.channel}"


class DeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    SENT = "sent", "Sent"
    FAILED = "failed", "Failed"


class NotificationDelivery(TimestampedModel):
    """One row per (signal, recipient) delivery attempt. Mutated across retries by
    `tasks.py::send_notification` — see the module docstring above for why this is the first
    model here where that mutability, and therefore `TimestampedModel`, genuinely fits."""

    signal = models.ForeignKey(Signal, on_delete=models.CASCADE, related_name="deliveries")
    recipient = models.ForeignKey(
        NotificationRecipient, on_delete=models.CASCADE, related_name="deliveries"
    )
    status = models.CharField(
        max_length=10, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = (
            models.UniqueConstraint(
                fields=("signal", "recipient"), name="unique_delivery_per_signal_recipient"
            ),
        )

    def __str__(self) -> str:
        return f"{self.recipient} <- {self.signal} ({self.status})"
