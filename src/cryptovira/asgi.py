"""ASGI entrypoint — the one used in every environment (uvicorn worker under gunicorn)."""

from __future__ import annotations

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cryptovira.settings")

application = get_asgi_application()
