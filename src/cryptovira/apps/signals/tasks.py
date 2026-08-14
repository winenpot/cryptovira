"""Notification dispatch. Two tasks:

- `dispatch_notifications` fans out one `NotificationDelivery` per active recipient of the
  signal's strategy owner, then dispatches `send_notification` for every currently-`PENDING`
  delivery — re-querying `PENDING` rather than iterating just-created rows, so this stays
  redelivery-safe on its own (see docs/interview/05-concurrency-and-correctness.md, section B/D).
- `send_notification` is the first task in this codebase that needs Celery's *task-level* retry
  (`self.retry(...)`) on top of the *broker-level* redelivery (`task_acks_late`) every task since
  Step 3 already relies on — see the module docstring reference above for the full distinction.
  `bind=True` + an explicit `self.retry(exc=exc)` call, not the `autoretry_for` decorator
  shortcut: the retry mechanism stays visible in the function body. Once `max_retries` is
  exhausted, this writes `NotificationDelivery.status = FAILED` — a Postgres-visible dead letter
  — rather than a RabbitMQ dead-letter exchange (a deliberate scope cut; see the ADR).

  A real gotcha manual verification against the actual running stack caught (`self.retry()`
  falling back to a flat 180s delay every time, not the exponential curve the task decorator
  looked like it configured): `retry_backoff`/`retry_backoff_max`/`retry_jitter` are only
  *automatically* applied by Celery's `autoretry_for` decorator wrapper — it computes the
  countdown and passes it to `task.retry()` for you. Called explicitly, `self.retry()` doesn't
  read those options at all (see `celery.app.task.Task.retry`'s source: `if not eta and
  countdown is None: countdown = self.default_retry_delay` — no mention of backoff anywhere).
  Keeping the explicit `self.retry()` call (for the max-retries-then-dead-letter branching this
  needs) means computing the countdown ourselves, with the *same* function Celery's own
  `autoretry_for` wrapper uses (`celery.utils.time.get_exponential_backoff_interval`) — reusing
  Celery's algorithm, not reinventing it, while keeping the decision visible in this function.
"""

from __future__ import annotations

from typing import Any

from celery.utils.time import get_exponential_backoff_interval

from cryptovira.apps.signals.channels import get_channel
from cryptovira.apps.signals.channels.base import ChannelDeliveryError
from cryptovira.apps.signals.messages import render_signal_message
from cryptovira.apps.signals.models import (
    Channel,
    DeliveryStatus,
    NotificationDelivery,
    NotificationRecipient,
    Signal,
)
from cryptovira.apps.signals.services import build_message_context
from cryptovira.celery import app


@app.task(ignore_result=True)  # type: ignore[untyped-decorator]  # celery is untyped
def dispatch_notifications(signal_id: int) -> None:
    signal = Signal.objects.select_related("evaluation__strategy__user").get(id=signal_id)
    recipients = NotificationRecipient.objects.filter(
        user=signal.evaluation.strategy.user, is_active=True
    )
    NotificationDelivery.objects.bulk_create(
        [NotificationDelivery(signal=signal, recipient=recipient) for recipient in recipients],
        ignore_conflicts=True,
    )
    pending_ids = NotificationDelivery.objects.filter(
        signal=signal, status=DeliveryStatus.PENDING
    ).values_list("id", flat=True)
    for delivery_id in pending_ids:
        send_notification.delay(delivery_id)


@app.task(  # type: ignore[untyped-decorator]  # celery is untyped
    bind=True,
    ignore_result=True,
    max_retries=5,
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def send_notification(self: Any, delivery_id: int) -> None:
    delivery = NotificationDelivery.objects.select_related("recipient", "signal").get(
        id=delivery_id
    )
    if delivery.status == DeliveryStatus.SENT:
        # Redelivered send_notification, already done — the guard that makes recording a send
        # idempotent. It does NOT guarantee the external send itself only happened once; see
        # dispatch_notifications' docstring and the interview module for the honest limit.
        return

    message = render_signal_message(build_message_context(delivery.signal))
    channel = get_channel(Channel(delivery.recipient.channel))

    try:
        channel.send(destination=delivery.recipient.destination, message=message)
    except ChannelDeliveryError as exc:
        delivery.attempts += 1
        delivery.last_error = str(exc)
        if self.request.retries >= self.max_retries:
            delivery.status = DeliveryStatus.FAILED
            delivery.save(update_fields=["attempts", "last_error", "status", "updated_at"])
            return
        delivery.save(update_fields=["attempts", "last_error", "updated_at"])
        countdown = get_exponential_backoff_interval(
            factor=1,
            retries=self.request.retries,
            maximum=self.retry_backoff_max,
            full_jitter=self.retry_jitter,
        )
        raise self.retry(exc=exc, countdown=countdown) from exc

    delivery.attempts += 1
    delivery.status = DeliveryStatus.SENT
    delivery.save(update_fields=["attempts", "status", "updated_at"])
