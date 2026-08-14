"""Scoped throttles for the two endpoints that need a tighter budget than the global anon rate.

DRF's throttle mechanism: a throttle class with a ``scope`` attribute looks its rate up from
``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"][scope]`` (see settings.py) at request time, and tracks
usage in the cache (Redis here) keyed by the throttle's ``scope`` + the client's identity — IP for
anonymous requests, user id once authenticated. This is why throttling *requires* a working cache
backend: without one, `AnonRateThrottle` silently allows everything (no storage, no counting).

Login and registration get their own scopes, separate from the global ``anon`` rate, because they
are the two endpoints a credential-stuffing or account-enumeration script actually hits — a
generic "60 requests/min across the whole API" budget would let an attacker burn most of it on
password guesses while legitimate anonymous browsing still needs headroom.
"""

from __future__ import annotations

from rest_framework.throttling import AnonRateThrottle


class RegistrationRateThrottle(AnonRateThrottle):
    scope = "registration"


class LoginRateThrottle(AnonRateThrottle):
    scope = "login"
