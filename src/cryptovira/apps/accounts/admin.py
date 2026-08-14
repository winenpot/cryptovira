"""Admin registration for the custom User model.

``django.contrib.auth.admin.UserAdmin`` is built assuming ``username`` exists (its default
``fieldsets``/``add_fieldsets``/``ordering`` all reference it), so subclassing it here means
overriding almost every class attribute rather than inheriting them — at which point it's more
honest to just write a plain ``ModelAdmin`` with the pieces this model actually has. We keep
``UserAdmin`` as the base anyway for one thing worth reusing: it wires the password field to a
readonly *hash display* plus a "change password" link in the admin form, instead of a plaintext
input that would defeat hashing entirely.
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.http import HttpRequest

from cryptovira.apps.accounts.models import User


@admin.register(User)
# django-stubs types UserAdmin as generic for annotation purposes only; the real runtime class
# has no __class_getitem__, so `DjangoUserAdmin[User]` would raise TypeError at import time.
class UserAdmin(DjangoUserAdmin):  # type: ignore[type-arg]
    model = User
    ordering = ("-date_joined",)
    list_display = ("email", "first_name", "last_name", "is_staff", "is_active", "date_joined")
    list_filter = ("is_staff", "is_superuser", "is_active")
    search_fields = ("email", "first_name", "last_name", "uuid")
    readonly_fields = ("uuid", "date_joined", "last_login")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Identity", {"fields": ("uuid", "first_name", "last_name")}),
        (
            "Permissions",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    # The form shown on the "Add user" page — deliberately narrower than `fieldsets` above
    # (which is for *editing*): DjangoUserAdmin's add flow uses a dedicated form that asks for
    # the two password fields once, hashes on submit, and re-displays the full `fieldsets` form
    # afterward for everything else.
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("email", "password1", "password2")}),)

    def get_readonly_fields(self, request: HttpRequest, obj: Any | None = None) -> tuple[str, ...]:
        # uuid must never be editable (it's the stable public identifier); everything else in
        # `readonly_fields` is Django-managed metadata (dates) that a human editing this form
        # should see but never hand-edit.
        return self.readonly_fields
