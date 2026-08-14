"""Structured logging setup.

Logs are JSON in every deployed environment so they can be queried by field
(``request_id``, ``strategy_id``, ``currency``) instead of grepped. Locally they render
as coloured key/value lines, which is the only reason ``log_json`` is a knob at all.
"""

from __future__ import annotations

from typing import Any

import structlog


def _shared_processors() -> list[Any]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]


def configure_structlog() -> None:
    """Point structlog at the stdlib logging pipeline configured by ``LOGGING``."""
    structlog.configure(
        processors=[
            *_shared_processors(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def build_logging_config(*, level: str, json_output: bool) -> dict[str, Any]:
    """Return a ``dict``-config that routes stdlib *and* structlog records to one formatter."""
    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=True)
    )
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "structured": {
                "()": structlog.stdlib.ProcessorFormatter,
                "processor": renderer,
                "foreign_pre_chain": _shared_processors(),
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "structured",
            },
        },
        "root": {"handlers": ["console"], "level": level},
        "loggers": {
            # Django's own request logger is noisy at INFO under load; keep it at WARNING
            # and rely on django-structlog's request_started/request_finished events.
            "django.request": {"level": "WARNING", "propagate": True},
            "django.db.backends": {"level": "WARNING", "propagate": True},
        },
    }
