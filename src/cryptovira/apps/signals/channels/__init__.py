"""The swap point tests use to avoid the network: `get_channel()` is what `tasks.py` calls, and
tests `monkeypatch.setattr` this exact name to inject a fake. Unlike `apps/market/sources`'s
single-implementation factory, this one dispatches on `Channel` — there are two real channels,
not one — but the principle is the same: no settings-driven registry-of-registries, just a plain
dict keyed by the same `Channel` enum `NotificationRecipient.channel` already uses.
"""

from __future__ import annotations

from cryptovira.apps.signals.channels.base import ChannelDeliveryError, NotificationChannel
from cryptovira.apps.signals.channels.telegram import TelegramChannel
from cryptovira.apps.signals.channels.webhook import WebhookChannel
from cryptovira.apps.signals.models import Channel

__all__ = ["ChannelDeliveryError", "NotificationChannel", "get_channel"]

_CHANNELS: dict[Channel, type[NotificationChannel]] = {
    Channel.TELEGRAM: TelegramChannel,
    Channel.WEBHOOK: WebhookChannel,
}


def get_channel(channel: Channel) -> NotificationChannel:
    return _CHANNELS[channel]()
