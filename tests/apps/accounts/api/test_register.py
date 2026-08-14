from __future__ import annotations

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from cryptovira.apps.accounts.models import User

pytestmark = [pytest.mark.integration, pytest.mark.django_db]

REGISTER_URL = "/api/v1/accounts/register/"

VALID_PAYLOAD = {
    "email": "rider@example.com",
    "password": "correct horse battery staple 1",
    "first_name": "Ada",
}


def test_register_creates_a_user_and_returns_tokens_in_one_call(api_client: APIClient) -> None:
    response = api_client.post(REGISTER_URL, VALID_PAYLOAD)

    assert response.status_code == status.HTTP_201_CREATED, response.data
    assert User.objects.filter(email="rider@example.com").exists()
    # See RegisterView's docstring for why registration returns tokens directly rather than
    # requiring a follow-up call to /token/.
    assert "access" in response.data
    assert "refresh" in response.data
    assert response.data["user"]["email"] == "rider@example.com"
    # The password must never come back in the response, under any key.
    assert "password" not in response.data["user"]


def test_register_does_not_store_the_raw_password(api_client: APIClient) -> None:
    api_client.post(REGISTER_URL, VALID_PAYLOAD)

    user = User.objects.get(email="rider@example.com")
    assert user.password != VALID_PAYLOAD["password"]
    assert user.check_password(VALID_PAYLOAD["password"])


def test_register_rejects_a_duplicate_email(api_client: APIClient) -> None:
    api_client.post(REGISTER_URL, VALID_PAYLOAD)

    response = api_client.post(REGISTER_URL, {**VALID_PAYLOAD, "first_name": "Someone Else"})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "email" in response.data
    assert User.objects.filter(email="rider@example.com").count() == 1


def test_register_rejects_a_duplicate_email_regardless_of_case(api_client: APIClient) -> None:
    """The serializer's `email__iexact` check (not the DB constraint — see
    test_models.py::test_email_uniqueness_is_case_sensitive_at_the_db_level) is what's under
    test here: this is the layer that actually stops a case-variant duplicate signup."""
    api_client.post(REGISTER_URL, VALID_PAYLOAD)

    response = api_client.post(REGISTER_URL, {**VALID_PAYLOAD, "email": "Rider@Example.com"})

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.parametrize(
    "weak_password",
    [
        "short1",  # below Django's MinimumLengthValidator (default 8)
        "12345678",  # NumericPasswordValidator
        "password",  # CommonPasswordValidator
    ],
)
def test_register_rejects_passwords_that_fail_django_validators(
    api_client: APIClient, weak_password: str
) -> None:
    response = api_client.post(REGISTER_URL, {**VALID_PAYLOAD, "password": weak_password})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "password" in response.data
    assert not User.objects.filter(email=VALID_PAYLOAD["email"]).exists()


def test_register_rejects_missing_email() -> None:
    client = APIClient()
    response = client.post(REGISTER_URL, {"password": "correct horse battery staple 1"})

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "email" in response.data
