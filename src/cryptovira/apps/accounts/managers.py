"""The manager Django needs to create users when there is no ``username`` field.

``AbstractUser`` (Django's default base) ships a working manager for free, because it already
knows the login field is called ``username``. The moment you switch away from that — as this
project does, using ``email`` instead — Django has no idea how to construct a user anymore:
``manage.py createsuperuser`` and ``User.objects.create_user(...)`` both go through *this* class.
Skipping it is the single most common mistake when rolling a custom user model; Django's own docs
call it out explicitly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib.auth.base_user import BaseUserManager

if TYPE_CHECKING:
    from cryptovira.apps.accounts.models import User


class UserManager(BaseUserManager["User"]):
    """``use_in_migrations = True`` so migrations that create rows (data migrations, fixtures
    loaded via ``migrate``) use *this* manager rather than Django's bare default — otherwise a
    migration calling ``User.objects.create(...)`` would silently skip password hashing."""

    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields: Any) -> User:
        if not email:
            raise ValueError("An email address is required.")
        # normalize_email lowercases the domain only (not the local part — `Bob@x.com` and
        # `bob@x.com` are technically different mailboxes per RFC 5321, even though almost no
        # real provider treats them that way). The `unique=True` on the field is what actually
        # prevents duplicate signups; this just avoids `Example.com`/`example.com` splitting
        # into two rows over a typo.
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        # set_password hashes with Django's configured PASSWORD_HASHERS (Argon2/PBKDF2/etc.) —
        # never assign to `user.password` directly, that stores it in plaintext.
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra_fields: Any) -> User:
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(
        self, email: str, password: str | None = None, **extra_fields: Any
    ) -> User:
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        # `createsuperuser` calls this with is_staff/is_superuser already True; the checks below
        # exist for the *programmatic* caller who passes is_staff=False by mistake and would
        # otherwise get a superuser that can't log into /admin/, or a "superuser" that Django's
        # permission checks (`has_perm`) silently don't treat as one.
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)
