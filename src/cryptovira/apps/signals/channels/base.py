"""The delivery-mechanism interface. Mirrors `apps/market/sources/base.py` exactly: a
`Protocol`, not `abc.ABC` — structural typing, so a test fake needs no inheritance relationship
to satisfy it, matching the "tests never hit the network" posture established in Step 3.
"""

from __future__ import annotations

from typing import Protocol


class ChannelDeliveryError(Exception):
    """Raised by any `NotificationChannel` on a failed send — the one exception type
    `tasks.py::send_notification`'s retry logic needs to know about, regardless of the
    underlying cause (an `httpx` timeout, a non-2xx response, a misconfigured destination)."""


class NotificationChannel(Protocol):
    def send(self, *, destination: str, message: str) -> None:
        """Deliver `message` to `destination`. Raises `ChannelDeliveryError` on failure —
        never returns a success/failure boolean, so a caller can't forget to check it."""
        ...
