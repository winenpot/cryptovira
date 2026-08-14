from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from cryptovira.apps.accounts.models import User

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

ME_URL = "/api/v1/accounts/me/"
PASSWORD = "correct horse battery staple 1"


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="rider@example.com", password=PASSWORD, first_name="Ada")


@pytest.fixture
def auth_client(user: User) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def test_me_requires_authentication(api_client: APIClient) -> None:
    response = api_client.get(ME_URL)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_me_returns_only_the_caller_own_profile(auth_client: APIClient, user: User) -> None:
    response = auth_client.get(ME_URL)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["email"] == user.email
    assert response.data["uuid"] == str(user.uuid)
    # There is no numeric id in the payload at all — see the comment on User.uuid.
    assert "id" not in response.data


def test_me_patch_updates_the_editable_fields(auth_client: APIClient, user: User) -> None:
    response = auth_client.patch(ME_URL, {"first_name": "Grace", "last_name": "Hopper"})

    assert response.status_code == status.HTTP_200_OK
    user.refresh_from_db()
    assert user.first_name == "Grace"
    assert user.last_name == "Hopper"


def test_me_patch_silently_ignores_attempts_to_change_email(
    auth_client: APIClient, user: User
) -> None:
    """`email` is in `read_only_fields` (UserSerializer) — DRF drops read-only keys from the
    input rather than erroring, which is the expected, if slightly surprising, behaviour: this
    test exists so that surprise is documented instead of rediscovered."""
    response = auth_client.patch(ME_URL, {"email": "someone-else@example.com"})

    assert response.status_code == status.HTTP_200_OK
    user.refresh_from_db()
    assert user.email == "rider@example.com"


def test_me_cannot_see_another_users_profile(auth_client: APIClient) -> None:
    """There is no `/accounts/users/<id>/` endpoint and no id in the URL at all — `me/` can only
    ever resolve to `request.user` (see MeView.get_object). Nothing to parametrize here; the
    absence of an id-based route *is* the access control.
    """
    other = User.objects.create_user(email="someone-else@example.com", password=PASSWORD)

    response = auth_client.get(ME_URL)

    assert response.data["email"] != other.email
