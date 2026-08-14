"""Operational endpoints.

Two endpoints, two different questions — conflating them is how a transient database blip
turns into a rolling restart of every healthy pod:

``/healthz`` (liveness)  — "is this process alive?"  Never touches a dependency.
``/readyz``  (readiness) — "can this process serve traffic?"  Checks the dependencies it
                            cannot work without, and returns 503 when one is down.
"""

from __future__ import annotations

from typing import Any

from django.db import connections
from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

CHECK_TIMEOUT_SECONDS = 2.0


@require_GET
def healthz(request: HttpRequest) -> JsonResponse:  # noqa: ARG001
    """Liveness probe: process is up and the WSGI/ASGI stack can produce a response."""
    return JsonResponse({"status": "ok"})


@require_GET
def readyz(request: HttpRequest) -> JsonResponse:  # noqa: ARG001
    """Readiness probe: report per-dependency status, 200 only if all are usable."""
    checks: dict[str, Any] = {
        "database": _check_database(),
        "cache": _check_cache(),
        "broker": _check_broker(),
    }
    healthy = all(check["ok"] for check in checks.values())
    return JsonResponse(
        {"status": "ok" if healthy else "degraded", "checks": checks},
        status=200 if healthy else 503,
    )


def _check_database() -> dict[str, Any]:
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as exc:  # noqa: BLE001 - probe must never raise
        return {"ok": False, "error": _describe(exc)}
    return {"ok": True}


def _check_cache() -> dict[str, Any]:
    from django.core.cache import cache

    try:
        cache.set("readyz", "1", timeout=5)
        cache.get("readyz")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": _describe(exc)}
    return {"ok": True}


def _check_broker() -> dict[str, Any]:
    from kombu import Connection

    from cryptovira.config import get_settings

    try:
        with Connection(
            get_settings().celery_broker_url,
            connect_timeout=CHECK_TIMEOUT_SECONDS,
        ) as conn:
            conn.ensure_connection(max_retries=0, timeout=CHECK_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": _describe(exc)}
    return {"ok": True}


def _describe(exc: BaseException) -> str:
    """Exception type only — probe output is world-readable, so never leak a DSN."""
    return type(exc).__name__
