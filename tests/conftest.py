"""Shared pytest fixtures.

Tests that need a database ask for it explicitly (``@pytest.mark.django_db`` or the
``db`` fixture). Everything else runs without one, which keeps the fast suite fast.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from django.core.cache import cache
from django.test import Client
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    """Reset the cache before every test.

    CACHES["default"] is real Redis (settings.py) — deliberately the same backend production
    uses, not a per-test-isolated in-memory stand-in. That realism has a cost: throttle counters
    (api/throttles.py) and anything else cache-backed persist for the *whole* pytest session
    unless something clears them. Without this fixture, enough accumulated `/token/` calls across
    unrelated test files can legitimately trip the login throttle mid-suite — a real bug this
    caught, order-dependent on pytest-randomly's seed, not a flaky test to retry away.
    """
    cache.clear()
    yield


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
