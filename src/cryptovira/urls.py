"""Root URLconf.

Versioned API lives under ``/api/v1/`` (DRF ``NamespaceVersioning``); operational endpoints
sit at the root so a load balancer never has to know about API versions.
"""

from __future__ import annotations

from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from cryptovira.apps.common import views as common_views

urlpatterns = [
    path("healthz", common_views.healthz, name="healthz"),
    path("readyz", common_views.readyz, name="readyz"),
    path("admin/", admin.site.urls),
    path("api/v1/", include(("cryptovira.api_v1", "v1"), namespace="v1")),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
]
