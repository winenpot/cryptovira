from __future__ import annotations

from typing import Any

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from cryptovira.apps.accounts.models import User


class RegisterSerializer(serializers.ModelSerializer[User]):
    """Registration payload → a new ``User`` row.

    Password validation reuses ``AUTH_PASSWORD_VALIDATORS`` (settings.py) — the same rules
    Django's admin and ``createsuperuser`` enforce — via ``validate_password()``, rather than
    hand-rolling a "must be 8 characters" check here. One policy, one place it's defined.
    """

    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    class Meta:
        model = User
        fields = ["email", "password", "first_name", "last_name"]

    def validate_password(self, value: str) -> str:
        # validate_password raises Django's ValidationError (not DRF's) and needs a *user*
        # instance to check similarity-to-attributes rules (e.g. "password too close to your
        # name") — we don't have a saved user yet at this point, so build a throwaway unsaved
        # one from the other fields already present on the request. Deliberately reading from
        # `self.initial_data` (the raw request payload) rather than splatting it wholesale:
        # initial_data is unvalidated and may carry unexpected keys that `User(**kwargs)`
        # would reject with a TypeError, so only the fields the similarity check needs are used.
        dummy_user = User(
            email=self.initial_data.get("email", ""),
            first_name=self.initial_data.get("first_name", ""),
            last_name=self.initial_data.get("last_name", ""),
        )
        try:
            validate_password(value, dummy_user)
        except DjangoValidationError as exc:
            # validate_password raises Django's ValidationError, whose .messages DRF's exception
            # handler doesn't understand — re-raised as DRF's own to get a proper 400 response
            # instead of an unhandled 500.
            raise serializers.ValidationError(exc.messages) from exc
        return value

    def validate_email(self, value: str) -> str:
        # Belt-and-suspenders with the DB's unique=True constraint: this gives a clean 400 with
        # a field-specific error instead of the IntegrityError the DB constraint alone would
        # raise on a race. The DB constraint is still what actually prevents duplicates under
        # concurrent requests — this check alone has the same TOCTOU gap the old system had.
        normalized = User.objects.normalize_email(value)
        if User.objects.filter(email__iexact=normalized).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return normalized

    def create(self, validated_data: dict[str, Any]) -> User:
        # Never call User.objects.create(**validated_data) here — that bypasses set_password()
        # and stores the raw password string in the `password` column.
        return User.objects.create_user(**validated_data)


class UserSerializer(serializers.ModelSerializer[User]):
    """The authenticated user's own profile. ``email`` and ``uuid`` are read-only here: changing
    an email is an identity operation (it should require re-verification) that doesn't exist yet
    — see docs/adr/0005-custom-user-model.md's deferred-features list."""

    class Meta:
        model = User
        fields = ["uuid", "email", "first_name", "last_name", "date_joined"]
        read_only_fields = ["uuid", "email", "date_joined"]


class LogoutSerializer(serializers.Serializer[dict[str, Any]]):
    """Blacklisting takes a *refresh* token, not the access token in the Authorization header.

    This is the concrete answer to "how do you revoke a JWT": you can't invalidate an
    already-issued access token early — the server accepts any signature-valid, unexpired token,
    which is what makes JWTs statelessly verifiable in the first place. What *can* be revoked is
    the refresh token, which is checked against the blacklist table on every use. That's why
    ACCESS_TOKEN_LIFETIME is short (15 min, see settings.py): it bounds how long a "logged out"
    access token keeps working, since revocation can't stop it directly.
    """

    refresh = serializers.CharField()
