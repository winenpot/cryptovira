"""Shared abstract base models.

Every write-mutable domain model added from here on (``Currency``, ``Strategy``,
``NotificationRecipient`` now; ``Order``, ``Plan``, ``Subscription`` in later steps) needs the
same two bookkeeping columns — declaring them once and inheriting avoids five copy-pasted field
pairs drifting out of sync. Append-only models (``Candle``, ``StrategyEvaluation``, ``Signal``)
deliberately don't inherit this: an ``updated_at`` that always equals ``created_at`` would
misrepresent the row as mutable. ``NotificationDelivery`` is the interesting middle case — it's
mutated by the system itself across retries, not by a human editing config, but ``updated_at``
still means something real there ("last delivery attempt"), so it inherits this too.
"""

from __future__ import annotations

from django.db import models


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
