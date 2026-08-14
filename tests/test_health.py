"""Liveness and readiness endpoints — the contract the orchestrator depends on.

These run without Postgres or RabbitMQ: the dependency probes are the unit under test only in
``test_readyz_integration``-style tests, which are marked ``integration``.
"""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest
from django.test import Client

OK: dict[str, Any] = {"ok": True}


def test_healthz_is_ok_without_touching_any_dependency(client: Client) -> None:
    with mock.patch("cryptovira.apps.common.views._check_database") as check_db:
        response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    check_db.assert_not_called()


def test_healthz_rejects_non_get(client: Client) -> None:
    assert client.post("/healthz").status_code == 405


def test_readyz_reports_ok_when_every_dependency_answers(client: Client) -> None:
    with (
        mock.patch("cryptovira.apps.common.views._check_database", return_value=OK),
        mock.patch("cryptovira.apps.common.views._check_cache", return_value=OK),
        mock.patch("cryptovira.apps.common.views._check_broker", return_value=OK),
    ):
        response = client.get("/readyz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"] == {"database": OK, "cache": OK, "broker": OK}


def test_readyz_returns_503_when_the_broker_is_unreachable(client: Client) -> None:
    with (
        mock.patch("cryptovira.apps.common.views._check_database", return_value=OK),
        mock.patch("cryptovira.apps.common.views._check_cache", return_value=OK),
        mock.patch(
            "cryptovira.apps.common.views._check_broker",
            return_value={"ok": False, "error": "OperationalError"},
        ),
    ):
        response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_probe_errors_never_leak_connection_details() -> None:
    from cryptovira.apps.common.views import _describe

    exc = ConnectionRefusedError("amqp://user:hunter2@rabbitmq:5672// refused")

    assert _describe(exc) == "ConnectionRefusedError"


@pytest.mark.integration
@pytest.mark.django_db
def test_database_probe_succeeds_against_a_real_database() -> None:
    from cryptovira.apps.common.views import _check_database

    assert _check_database() == {"ok": True}
