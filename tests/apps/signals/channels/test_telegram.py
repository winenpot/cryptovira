"""No `integration` marker: pure computation, same posture as
`tests/apps/market/sources/test_binance.py`."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from cryptovira.apps.signals.channels.base import ChannelDeliveryError
from cryptovira.apps.signals.channels.telegram import TelegramChannel


def test_send_posts_chat_id_and_text_to_the_bot_token_path() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["method"] = request.method
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test")
    channel = TelegramChannel(client=client, bot_token=SecretStr("test-token"))

    channel.send(destination="12345", message="hello")

    assert captured["path"] == "/bottest-token/sendMessage"
    assert captured["method"] == "POST"
    assert captured["body"] == {"chat_id": "12345", "text": "hello"}


def test_send_raises_channel_delivery_error_on_non_2xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"ok": False})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="https://example.test")
    channel = TelegramChannel(client=client, bot_token=SecretStr("test-token"))

    with pytest.raises(ChannelDeliveryError):
        channel.send(destination="12345", message="hello")


def test_send_without_a_configured_token_raises_clearly() -> None:
    channel = TelegramChannel(client=httpx.Client(), bot_token=None)

    with pytest.raises(ChannelDeliveryError, match="TELEGRAM_BOT_TOKEN"):
        channel.send(destination="12345", message="hello")
