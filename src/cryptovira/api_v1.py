"""Aggregated ``/api/v1/`` URLconf.

Each app owns an ``api/urls.py``; this module is the only place that knows the mount points,
so adding an app is a one-line change here rather than an edit to the root URLconf.
"""

from __future__ import annotations

from django.urls import URLPattern, URLResolver, include, path

urlpatterns: list[URLPattern | URLResolver] = [
    path("accounts/", include("cryptovira.apps.accounts.api.urls")),
    # path("market/", include("cryptovira.apps.market.api.urls")),
]
