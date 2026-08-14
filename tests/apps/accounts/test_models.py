from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction

from cryptovira.apps.accounts.models import User

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def test_str_is_the_email() -> None:
    user = User.objects.create_user(email="rider@example.com", password="pw")

    assert str(user) == "rider@example.com"


def test_get_full_name_combines_first_and_last() -> None:
    user = User.objects.create_user(
        email="rider@example.com", password="pw", first_name="Ada", last_name="Lovelace"
    )

    assert user.get_full_name() == "Ada Lovelace"


def test_get_full_name_falls_back_to_email_when_no_name_set() -> None:
    user = User.objects.create_user(email="rider@example.com", password="pw")

    assert user.get_full_name() == "rider@example.com"
    assert user.get_short_name() == "rider@example.com"


def test_each_user_gets_a_distinct_uuid() -> None:
    first = User.objects.create_user(email="first@example.com", password="pw")
    second = User.objects.create_user(email="second@example.com", password="pw")

    assert first.uuid != second.uuid


def test_email_uniqueness_is_a_real_database_constraint() -> None:
    """The old system checked uniqueness with a SELECT before the INSERT — a race under
    concurrent requests (see docs/adr/0005-custom-user-model.md). Proving the constraint is at
    the database level, not just in a serializer, is what actually closes that gap: this test
    creates the duplicate directly through the manager, bypassing any API-layer validation."""
    User.objects.create_user(email="rider@example.com", password="pw")

    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create_user(email="rider@example.com", password="pw")


def test_email_uniqueness_is_case_sensitive_at_the_db_level() -> None:
    """Documents an actual gap, doesn't paper over it: Postgres's UNIQUE constraint on `email`
    is case-sensitive, so `Rider@example.com` and `rider@example.com` are two distinct rows at
    the database level even though most mail providers treat them as the same mailbox. The
    registration serializer's `email__iexact` check (api/serializers.py) is the layer that
    actually prevents this for the signup path — this test is here so that fact stays visible
    and isn't "discovered" again by a future duplicate-account bug report.
    """
    User.objects.create_user(email="rider@example.com", password="pw")

    # Does NOT raise — same address, different case, and the DB constraint alone doesn't care.
    User.objects.create_user(email="Rider@example.com", password="pw")

    assert User.objects.filter(email__iexact="rider@example.com").count() == 2
