"""Login, refresh, and logout — the JWT lifecycle end to end.

Worth studying alongside docs/adr/0005-custom-user-model.md and the LogoutSerializer/LogoutView
docstrings: this is the concrete demonstration of "JWT revocation is the hard part" from
docs/interview/01-foundations.md — an access token blacklisting a *refresh* token does not stop
the access token itself from working until it naturally expires.
"""

from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from cryptovira.apps.accounts.models import User

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

TOKEN_URL = "/api/v1/accounts/token/"
REFRESH_URL = "/api/v1/accounts/token/refresh/"
VERIFY_URL = "/api/v1/accounts/token/verify/"
LOGOUT_URL = "/api/v1/accounts/logout/"
ME_URL = "/api/v1/accounts/me/"

PASSWORD = "correct horse battery staple 1"


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="rider@example.com", password=PASSWORD)


def test_login_with_correct_credentials_returns_a_token_pair(
    api_client: APIClient, user: User
) -> None:
    response = api_client.post(TOKEN_URL, {"email": user.email, "password": PASSWORD})

    assert response.status_code == status.HTTP_200_OK
    assert "access" in response.data
    assert "refresh" in response.data


def test_login_with_wrong_password_is_rejected(api_client: APIClient, user: User) -> None:
    response = api_client.post(TOKEN_URL, {"email": user.email, "password": "wrong password"})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_login_uses_email_not_username_as_the_identifier(api_client: APIClient, user: User) -> None:
    """Confirms USERNAME_FIELD = "email" actually took effect end to end — simplejwt's token
    view builds its serializer from the user model's USERNAME_FIELD automatically, so a
    regression here (e.g. someone re-adding a `username` field) would show up as this field
    silently being ignored rather than as an import error."""
    response = api_client.post(TOKEN_URL, {"email": user.email, "password": PASSWORD})

    assert response.status_code == status.HTTP_200_OK


def test_access_token_authorizes_requests(api_client: APIClient, user: User) -> None:
    login = api_client.post(TOKEN_URL, {"email": user.email, "password": PASSWORD})
    access = login.data["access"]

    response = api_client.get(ME_URL, HTTP_AUTHORIZATION=f"Bearer {access}")

    assert response.status_code == status.HTTP_200_OK
    assert response.data["email"] == user.email


def test_refresh_token_issues_a_new_access_token(api_client: APIClient, user: User) -> None:
    login = api_client.post(TOKEN_URL, {"email": user.email, "password": PASSWORD})

    response = api_client.post(REFRESH_URL, {"refresh": login.data["refresh"]})

    assert response.status_code == status.HTTP_200_OK
    assert "access" in response.data
    # ROTATE_REFRESH_TOKENS=True (settings.py): every refresh call also issues a *new* refresh
    # token, and BLACKLIST_AFTER_ROTATION=True means the one just spent stops working below.
    assert "refresh" in response.data
    assert response.data["refresh"] != login.data["refresh"]


def test_a_rotated_refresh_token_cannot_be_reused(api_client: APIClient, user: User) -> None:
    login = api_client.post(TOKEN_URL, {"email": user.email, "password": PASSWORD})
    old_refresh = login.data["refresh"]
    api_client.post(REFRESH_URL, {"refresh": old_refresh})  # rotates + blacklists old_refresh

    replay = api_client.post(REFRESH_URL, {"refresh": old_refresh})

    assert replay.status_code == status.HTTP_401_UNAUTHORIZED


def test_logout_blacklists_the_refresh_token(api_client: APIClient, user: User) -> None:
    login = api_client.post(TOKEN_URL, {"email": user.email, "password": PASSWORD})
    access, refresh = login.data["access"], login.data["refresh"]

    logout = api_client.post(
        LOGOUT_URL, {"refresh": refresh}, HTTP_AUTHORIZATION=f"Bearer {access}"
    )
    assert logout.status_code == status.HTTP_205_RESET_CONTENT

    replay = api_client.post(REFRESH_URL, {"refresh": refresh})
    assert replay.status_code == status.HTTP_401_UNAUTHORIZED


def test_logout_does_not_revoke_the_access_token_itself(api_client: APIClient, user: User) -> None:
    """The gap logout cannot close: the access token used to authenticate *this same request*
    keeps working after logout, because access tokens are verified by signature alone (no
    database lookup) — see LogoutSerializer's docstring. This is exactly why
    ACCESS_TOKEN_LIFETIME is short (15 minutes): it bounds this window, it doesn't close it."""
    login = api_client.post(TOKEN_URL, {"email": user.email, "password": PASSWORD})
    access, refresh = login.data["access"], login.data["refresh"]
    api_client.post(LOGOUT_URL, {"refresh": refresh}, HTTP_AUTHORIZATION=f"Bearer {access}")

    still_works = api_client.get(ME_URL, HTTP_AUTHORIZATION=f"Bearer {access}")

    assert still_works.status_code == status.HTTP_200_OK


def test_logout_requires_authentication(api_client: APIClient, user: User) -> None:
    login = api_client.post(TOKEN_URL, {"email": user.email, "password": PASSWORD})

    response = api_client.post(LOGOUT_URL, {"refresh": login.data["refresh"]})

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_logout_with_an_already_blacklisted_token_is_a_clean_400_not_a_500(
    api_client: APIClient, user: User
) -> None:
    """Calling logout twice with the same refresh token — a plausible double-click or retried
    request — must not surface as an unhandled 500. LogoutView.post() catches TokenError
    specifically so this stays a normal 400 response."""
    login = api_client.post(TOKEN_URL, {"email": user.email, "password": PASSWORD})
    access, refresh = login.data["access"], login.data["refresh"]
    api_client.post(LOGOUT_URL, {"refresh": refresh}, HTTP_AUTHORIZATION=f"Bearer {access}")

    second_logout = api_client.post(
        LOGOUT_URL, {"refresh": refresh}, HTTP_AUTHORIZATION=f"Bearer {access}"
    )

    assert second_logout.status_code == status.HTTP_400_BAD_REQUEST
    assert "detail" in second_logout.data
