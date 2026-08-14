"""Shared pytest fixtures.

Tests that need a database ask for it explicitly (``@pytest.mark.django_db`` or the
``db`` fixture). Everything else runs without one, which keeps the fast suite fast.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from django.test import Client
from rest_framework.test import APIClient


@pytest.fixture
def client() -> Client:
    """Unauthenticated Django test client."""
    return Client()


@pytest.fixture
def api_client() -> APIClient:
    """Unauthenticated DRF test client — use this (not `client`) for /api/v1/ endpoints so
    responses are parsed as DRF `Response` objects with `.data` available."""
    return APIClient()


@pytest.fixture
def eager_celery() -> Iterator[None]:
    """Run Celery tasks inline, so a test can assert on their effects without a worker."""
    from celery import current_app

    previous = current_app.conf.task_always_eager
    current_app.conf.task_always_eager = True
    try:
        yield
    finally:
        current_app.conf.task_always_eager = previous
