"""The configuration layer is the first thing that can break a deploy, so it is tested first."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cryptovira.config import Settings


def _settings(**overrides: object) -> Settings:
    """Build settings from explicit values only, ignoring any developer's local .env."""
    defaults: dict[str, object] = {"_env_file": None}
    return Settings(**(defaults | overrides))  # type: ignore[arg-type]


def test_local_defaults_are_usable_without_any_env_vars() -> None:
    settings = _settings()

    assert settings.environment == "local"
    assert settings.debug is False
    assert settings.celery_broker_url.startswith("amqp://")


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_production_rejects_the_insecure_default_secret_key(environment: str) -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        _settings(environment=environment)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_production_rejects_debug_mode(environment: str) -> None:
    with pytest.raises(ValidationError, match="DEBUG"):
        _settings(environment=environment, secret_key="a-real-secret", debug=True)


def test_production_accepts_a_fully_specified_configuration() -> None:
    settings = _settings(
        environment="production",
        secret_key="a-real-secret",
        allowed_hosts=["api.cryptovira.example"],
    )

    assert settings.is_production_like is True
    assert settings.secret_key.get_secret_value() == "a-real-secret"


@pytest.mark.parametrize("origin", ["*", "localhost:8000", "cryptovira.com"])
def test_csrf_trusted_origins_must_carry_a_scheme(origin: str) -> None:
    with pytest.raises(ValidationError, match="must include a scheme"):
        _settings(csrf_trusted_origins=[origin])


def test_csrf_trusted_origins_accepts_schemed_and_wildcard_host_origins() -> None:
    origins = ["http://localhost:8000", "https://*.cryptovira.com"]

    assert _settings(csrf_trusted_origins=origins).csrf_trusted_origins == origins


def test_secret_key_is_not_exposed_by_repr() -> None:
    settings = _settings(secret_key="top-secret-value")

    assert "top-secret-value" not in repr(settings)
