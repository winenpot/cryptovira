"""No `integration` marker: pure computation."""

from __future__ import annotations

import json

import httpx
import pytest

from cryptovira.apps.signals.channels.base import ChannelDeliveryError
from cryptovira.apps.signals.channels.webhook import WebhookChannel


def test_send_posts_the_message_as_json() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["body"] = json.loads(request.content)
        return httpx.Response(200)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    channel = WebhookChannel(client=client)

    channel.send(destination="https://example.test/hook", message="hello")

    assert captured["url"] == "https://example.test/hook"
    assert captured["method"] == "POST"
    assert captured["body"] == {"message": "hello"}


def test_send_raises_channel_delivery_error_on_non_2xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    channel = WebhookChannel(client=client)

    with pytest.raises(ChannelDeliveryError):
        channel.send(destination="https://example.test/hook", message="hello")


def test_send_raises_channel_delivery_error_on_connection_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    channel = WebhookChannel(client=client)

    with pytest.raises(ChannelDeliveryError):
        channel.send(destination="https://example.test/hook", message="hello")
