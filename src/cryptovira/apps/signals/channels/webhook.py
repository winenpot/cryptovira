"""A generic webhook channel — POSTs a JSON payload to whatever URL a recipient registered.
Not tied to a vendor (the old system's equivalent, `Adamignal`, was one specific relay service);
any consumer that can accept a JSON POST works, no new dependency needed beyond `httpx`.
"""

from __future__ import annotations

import httpx

from cryptovira.apps.signals.channels.base import ChannelDeliveryError
from cryptovira.config import get_settings


class WebhookChannel:
    """Implements `NotificationChannel` (structurally — `Protocol`, no inheritance needed)."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        settings = get_settings()
        self._client = client or httpx.Client(timeout=settings.webhook_request_timeout_seconds)

    def send(self, *, destination: str, message: str) -> None:
        try:
            response = self._client.post(destination, json={"message": message})
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ChannelDeliveryError(str(exc)) from exc
