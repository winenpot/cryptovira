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
from celery.schedules import crontab

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
        "cryptovira.apps.strategy.tasks.*": {"queue": "strategy"},
        "cryptovira.apps.brokers.tasks.*": {"queue": "orders"},
    },
    # One entry per interval *cadence*, not per (currency, interval) pair — each tick fans out
    # to every active Currency itself (see apps/market/tasks.py), so adding or deactivating a
    # symbol in admin never requires touching this schedule. Minute offsets sit a few minutes
    # past each boundary so the exchange has actually closed the candle before polling for it.
    beat_schedule={
        "market-ingest-1m": {
            "task": "cryptovira.apps.market.tasks.fan_out_ingest_candles",
            "schedule": crontab(minute="*"),
            "kwargs": {"interval": "1m"},
        },
        "market-ingest-5m": {
            "task": "cryptovira.apps.market.tasks.fan_out_ingest_candles",
            "schedule": crontab(minute="*/5"),
            "kwargs": {"interval": "5m"},
        },
        "market-ingest-15m": {
            "task": "cryptovira.apps.market.tasks.fan_out_ingest_candles",
            "schedule": crontab(minute="*/15"),
            "kwargs": {"interval": "15m"},
        },
        "market-ingest-30m": {
            "task": "cryptovira.apps.market.tasks.fan_out_ingest_candles",
            "schedule": crontab(minute="5,35"),
            "kwargs": {"interval": "30m"},
        },
        "market-ingest-1h": {
            "task": "cryptovira.apps.market.tasks.fan_out_ingest_candles",
            "schedule": crontab(minute=5),
            "kwargs": {"interval": "1h"},
        },
        "market-ingest-4h": {
            "task": "cryptovira.apps.market.tasks.fan_out_ingest_candles",
            "schedule": crontab(minute=5, hour="*/4"),
            "kwargs": {"interval": "4h"},
        },
        "market-ingest-1d": {
            "task": "cryptovira.apps.market.tasks.fan_out_ingest_candles",
            "schedule": crontab(minute=5, hour=0),
            "kwargs": {"interval": "1d"},
        },
        "market-ingest-1w": {
            "task": "cryptovira.apps.market.tasks.fan_out_ingest_candles",
            "schedule": crontab(minute=5, hour=0, day_of_week=1),
            "kwargs": {"interval": "1w"},
        },
        # Strategy evaluation needs that interval's candle to have already landed. Sub-15-minute
        # tiers reuse ingest's own cadence unchanged (no headroom at that granularity, and
        # evaluate_strategy tolerates evaluating a slightly-stale "latest candle" rather than
        # erroring); 30m and up get ingest's offset +3 minutes.
        "strategy-evaluate-1m": {
            "task": "cryptovira.apps.strategy.tasks.fan_out_evaluate_strategies",
            "schedule": crontab(minute="*"),
            "kwargs": {"interval": "1m"},
        },
        "strategy-evaluate-5m": {
            "task": "cryptovira.apps.strategy.tasks.fan_out_evaluate_strategies",
            "schedule": crontab(minute="*/5"),
            "kwargs": {"interval": "5m"},
        },
        "strategy-evaluate-15m": {
            "task": "cryptovira.apps.strategy.tasks.fan_out_evaluate_strategies",
            "schedule": crontab(minute="*/15"),
            "kwargs": {"interval": "15m"},
        },
        "strategy-evaluate-30m": {
            "task": "cryptovira.apps.strategy.tasks.fan_out_evaluate_strategies",
            "schedule": crontab(minute="8,38"),
            "kwargs": {"interval": "30m"},
        },
        "strategy-evaluate-1h": {
            "task": "cryptovira.apps.strategy.tasks.fan_out_evaluate_strategies",
            "schedule": crontab(minute=8),
            "kwargs": {"interval": "1h"},
        },
        "strategy-evaluate-4h": {
            "task": "cryptovira.apps.strategy.tasks.fan_out_evaluate_strategies",
            "schedule": crontab(minute=8, hour="*/4"),
            "kwargs": {"interval": "4h"},
        },
        "strategy-evaluate-1d": {
            "task": "cryptovira.apps.strategy.tasks.fan_out_evaluate_strategies",
            "schedule": crontab(minute=8, hour=0),
            "kwargs": {"interval": "1d"},
        },
        "strategy-evaluate-1w": {
            "task": "cryptovira.apps.strategy.tasks.fan_out_evaluate_strategies",
            "schedule": crontab(minute=8, hour=0, day_of_week=1),
            "kwargs": {"interval": "1w"},
        },
    },
)


@app.task(bind=True, ignore_result=True)  # type: ignore[untyped-decorator]  # celery is untyped
def debug_task(self: Any) -> str:
    """Smoke test: ``uv run celery -A cryptovira call cryptovira.celery.debug_task``."""
    return f"ok from {self.request.id}"
