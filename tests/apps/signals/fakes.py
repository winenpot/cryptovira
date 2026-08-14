"""`FakeChannel` is the test double `NotificationChannel` exists for — mirrors
`tests/apps/market/fakes.py::FakeMarketDataSource`. Tests inject it by monkeypatching
`get_channel` itself, since a channel instance can't travel as a Celery task argument.
"""

from __future__ import annotations

from cryptovira.apps.signals.channels.base import ChannelDeliveryError


class FakeChannel:
    def __init__(self, *, always_fails: bool = False) -> None:
        self.always_fails = always_fails
        self.sent: list[tuple[str, str]] = []

    def send(self, *, destination: str, message: str) -> None:
        if self.always_fails:
            raise ChannelDeliveryError("FakeChannel configured to always fail")
        self.sent.append((destination, message))
