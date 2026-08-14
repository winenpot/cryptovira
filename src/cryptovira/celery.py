"""Celery application.

Broker is RabbitMQ (AMQP), result backend is Postgres via ``django-celery-results``.

Why RabbitMQ rather than Redis: this system's tasks place real orders. RabbitMQ gives
per-message acknowledgement with broker-side redelivery, publisher confirms, and dead-letter
queues — so a worker that dies mid-order does not silently lose the message. Redis as a broker
loses in-flight messages on failover and has no native DLQ.

The beat schedule is declared here, in code. The old system upserted ``PeriodicTask`` rows from
a ``beat_init`` signal, which meant the live schedule could silently drift from the repository.
"""

from __future__ import annotations

import os
from typing import Any

from celery import Celery
from celery.schedules import crontab  # noqa: F401  (used by schedules added later)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cryptovira.settings")

app = Celery("cryptovira")

# All Celery settings come from Django settings, prefixed with CELERY_.
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.update(
    # --- correctness over throughput ------------------------------------------------
    task_acks_late=True,  # ack after the task returns, so a crash redelivers it
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # no hoarding: a slow task must not park others
    task_time_limit=300,
    task_soft_time_limit=270,
    # --- serialization ---------------------------------------------------------------
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_extended=True,
    # --- routing ---------------------------------------------------------------------
    # Separate queues let order execution scale (and fail) independently of price polling.
    task_default_queue="default",
    task_routes={
        "cryptovira.apps.market.tasks.*": {"queue": "market"},
        "cryptovira.apps.brokers.tasks.*": {"queue": "orders"},
    },
    beat_schedule={},
)


@app.task(bind=True, ignore_result=True)  # type: ignore[untyped-decorator]  # celery is untyped
def debug_task(self: Any) -> str:
    """Smoke test: ``uv run celery -A cryptovira call cryptovira.celery.debug_task``."""
    return f"ok from {self.request.id}"
