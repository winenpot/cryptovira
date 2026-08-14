"""A thin client for Telegram's Bot API `sendMessage` endpoint.

Not `python-telegram-bot`, not `telethon` (the old system carried *both*, for reasons lost to
history — see `old-version/core/apps/account/tasks.py`, where the actually-working delivery path
was always the raw `requests.post` branch, not the `telethon` fallback). Directly reuses the
ADR-0007 precedent: a project-owned thin `httpx` client over a heavy SDK, for one endpoint that
needs none of a full bot framework's surface (updates, inline keyboards, webhooks-in).
"""

from __future__ import annotations

import httpx
from pydantic import SecretStr

from cryptovira.apps.signals.channels.base import ChannelDeliveryError
from cryptovira.config import get_settings


class _Unset:
    """Distinguishes "caller didn't pass bot_token, read it from settings" from "caller
    explicitly passed bot_token=None" — a plain `bot_token: SecretStr | None = None` default
    couldn't tell those apart, which would make a test for "no token configured" depend on
    whatever happens to be in the ambient environment's .env rather than being deterministic."""


_UNSET = _Unset()


class TelegramChannel:
    """Implements `NotificationChannel` (structurally — `Protocol`, no inheritance needed)."""

    def __init__(
        self,
        client: httpx.Client | None = None,
        bot_token: SecretStr | _Unset | None = _UNSET,
    ) -> None:
        settings = get_settings()
        self._bot_token = (
            settings.telegram_bot_token if isinstance(bot_token, _Unset) else bot_token
        )
        self._client = client or httpx.Client(
            base_url=settings.telegram_api_base_url,
            timeout=settings.telegram_request_timeout_seconds,
        )

    def send(self, *, destination: str, message: str) -> None:
        if self._bot_token is None:
            # A clear, named error at the point of use — config.py's own stated goal ("fail
            # with a precise error instead of at 3am") — rather than Telegram's API rejecting
            # an "None"-shaped bot token in the URL with a confusing 404.
            msg = "TELEGRAM_BOT_TOKEN is not configured."
            raise ChannelDeliveryError(msg)

        try:
            response = self._client.post(
                f"/bot{self._bot_token.get_secret_value()}/sendMessage",
                json={"chat_id": destination, "text": message},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # Covers both a non-2xx response (HTTPStatusError) and a failed request itself
            # (ConnectError/TimeoutException/...) — either way, the send didn't happen, and
            # send_notification's retry logic only needs to know "this attempt failed," not why.
            raise ChannelDeliveryError(str(exc)) from exc
