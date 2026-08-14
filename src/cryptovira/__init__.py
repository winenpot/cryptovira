"""Cryptovira — crypto trading-signal platform."""

from cryptovira.celery import app as celery_app

__all__ = ["celery_app"]
