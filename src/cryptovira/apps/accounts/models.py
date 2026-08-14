"""The identity model. See docs/adr/0005-custom-user-model.md for why this stays this thin.

Design notes worth knowing cold for an interview:

- ``AbstractBaseUser`` + ``PermissionsMixin`` is the *unopinionated* base — it gives you password
  hashing (``set_password``/``check_password``) and nothing else about *how* a user is identified.
  ``AbstractUser`` is that same base *plus* a concrete ``username`` field, ``first_name``,
  ``last_name``, ``email`` (non-unique!), and the `is_staff`/`is_active`/`is_superuser` flags
  already wired up. Subclassing ``AbstractUser`` is the fast path when you're keeping
  username/password login; the moment the login field changes (here: email, uniquely
  constrained), fighting AbstractUser's existing `username` field is more work than starting from
  ``AbstractBaseUser`` and declaring exactly the fields you want.
- ``PermissionsMixin`` is what adds `is_superuser`, `groups`, `user_permissions`, and `has_perm()`
  — the plumbing Django's admin and permission system expect on *any* user model, custom or not.
- Django itself never assumes a `username` field exists; it looks up `USERNAME_FIELD` at runtime
  wherever it needs the "how does this user log in" field (ModelBackend, admin, shell prompts).
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.db import models

from cryptovira.apps.accounts.managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    # The *public* identifier — put this in URLs, JWT claims, API responses. Never expose `id`:
    # a sequential integer PK leaks how many users exist and in what order they signed up, and
    # invites enumeration (`/users/1/`, `/users/2/`, ...). `id` stays as the internal PK because
    # it's the fastest thing to index/join on; `uuid` is the only externally-visible handle.
    uuid = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True,
        db_index=True,
        help_text="Public identifier — use this in URLs and tokens, never the numeric id.",
    )

    # The actual DB-level constraint the old system's save()-time check-then-save was missing.
    # A UNIQUE index means the *database* rejects a second row with the same email even under
    # concurrent inserts — the check-then-save pattern in old-version's User.save() cannot do
    # that, because two transactions can both pass the SELECT before either COMMITs.
    email = models.EmailField(unique=True)

    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)

    # is_active gates login (Django's ModelBackend refuses inactive users); is_staff gates
    # /admin/ access. Neither implies the other, and neither implies is_superuser
    # (PermissionsMixin) — three independent switches, a common interview trip-up.
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    # Tells Django (admin, auth backends, `createsuperuser`) which field is the login identifier.
    USERNAME_FIELD = "email"
    # Fields `createsuperuser` prompts for *in addition to* USERNAME_FIELD and password — email
    # and password are already mandatory via the manager, so nothing else needs to be forced.
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        ordering = ("-date_joined",)

    def __str__(self) -> str:
        return self.email

    def get_full_name(self) -> str:
        """Conventional Django method name — the admin site calls this if it exists."""
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name or self.email

    def get_short_name(self) -> str:
        return self.first_name or self.email

    def clean(self) -> None:
        # BaseUserManager.normalize_email lowercases only the domain part; do the same at the
        # model level so a save() that bypasses the manager (e.g. an admin form) stays consistent.
        super().clean()
        self.email = self.__class__.objects.normalize_email(self.email)

    def natural_key(self) -> tuple[Any, ...]:
        return (self.email,)
