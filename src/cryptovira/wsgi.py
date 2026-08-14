"""WSGI entrypoint — kept for tooling that still expects it; ASGI is the deployed path."""

from __future__ import annotations

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cryptovira.settings")

application = get_wsgi_application()
