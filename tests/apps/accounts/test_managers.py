"""UserManager: the thing `createsuperuser` and `User.objects.create_user(...)` actually call.

Marked `integration` (needs real Postgres) rather than the default fast suite — see
tests/conftest.py and README's troubleshooting table for why the fast suite stays DB-free.
"""

from __future__ import annotations

import pytest

from cryptovira.apps.accounts.models import User

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def test_create_user_requires_an_email() -> None:
    with pytest.raises(ValueError, match="email"):
        User.objects.create_user(email="", password="correct horse battery staple 1")


def test_create_user_hashes_the_password() -> None:
    user = User.objects.create_user(
        email="rider@example.com", password="correct horse battery staple 1"
    )

    # The whole point of set_password(): the column never holds the raw string.
    assert user.password != "correct horse battery staple 1"
    assert user.check_password("correct horse battery staple 1") is True
    assert user.check_password("wrong password") is False


def test_create_user_defaults_to_non_privileged() -> None:
    user = User.objects.create_user(
        email="rider@example.com", password="correct horse battery staple 1"
    )

    assert user.is_staff is False
    assert user.is_superuser is False
    assert user.is_active is True


def test_create_superuser_sets_both_privilege_flags() -> None:
    admin_user = User.objects.create_superuser(
        email="admin@example.com", password="correct horse battery staple 1"
    )

    assert admin_user.is_staff is True
    assert admin_user.is_superuser is True


@pytest.mark.parametrize("bad_field", ["is_staff", "is_superuser"])
def test_create_superuser_rejects_explicitly_downgraded_privilege_flags(bad_field: str) -> None:
    # Guards against a caller passing is_staff=False / is_superuser=False by mistake and
    # silently getting a "superuser" that admin/permission checks don't actually treat as one.
    with pytest.raises(ValueError, match=bad_field):
        User.objects.create_superuser(
            email="admin@example.com",
            password="correct horse battery staple 1",
            **{bad_field: False},
        )
