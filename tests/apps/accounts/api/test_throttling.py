"""Confirms the login/registration throttle scopes (settings.py DEFAULT_THROTTLE_RATES) are
actually wired to their views, not just declared. See api/throttles.py for why these exist as
separate scopes from the global anon rate.
"""

from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from cryptovira.apps.accounts.api.throttles import LoginRateThrottle

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

TOKEN_URL = "/api/v1/accounts/token/"


def test_login_endpoint_is_throttled_after_the_scoped_rate_is_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A genuine DRF gotcha, not just test plumbing: `SimpleRateThrottle.THROTTLE_RATES =
    # api_settings.DEFAULT_THROTTLE_RATES` (rest_framework/throttling.py) runs ONCE, at module
    # import time, binding a plain dict — it is not re-read per request. So mutating
    # `settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]` at runtime (via override_settings, the
    # `settings` fixture, whatever) never reaches an already-imported throttle class; only
    # `api_settings`'s OWN cached attribute gets refreshed by Django's `setting_changed` signal.
    # The only way to actually change a rate at test time is to patch the throttle class's dict
    # directly, which is what this does.
    monkeypatch.setitem(LoginRateThrottle.THROTTLE_RATES, "login", "2/min")
    # No explicit cache.clear() needed here — the autouse `_clear_cache` fixture
    # (tests/conftest.py) resets the real Redis cache before every test, which is exactly the
    # isolation this test depends on: without it, an earlier test's login-scope counter could
    # eat into this one's deliberately tiny 2/min budget.
    client = APIClient()
    bad_credentials = {"email": "nobody@example.com", "password": "wrong"}

    first = client.post(TOKEN_URL, bad_credentials)
    second = client.post(TOKEN_URL, bad_credentials)
    third = client.post(TOKEN_URL, bad_credentials)

    # First two consume the 2/min budget (each is a normal 401 — wrong password, not throttled
    # yet); the third exceeds it and gets 429 regardless of whether the credentials were right.
    assert first.status_code == status.HTTP_401_UNAUTHORIZED
    assert second.status_code == status.HTTP_401_UNAUTHORIZED
    assert third.status_code == status.HTTP_429_TOO_MANY_REQUESTS
