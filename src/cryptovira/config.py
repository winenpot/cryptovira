"""Typed, environment-driven configuration.

Every deployment difference lives here as a *value*, never as a separate settings module.
The old codebase had ``settings/base.py`` + ``development.py`` + ``production.py`` + ``aws.py``
with secrets hardcoded in ``base.py``; the failure mode was "which file is actually live?".
Here there is exactly one settings module, fed by one validated object.

Read once at import time via :func:`get_settings`; a bad or missing variable fails at boot
with a precise error instead of at 3am with an ``AttributeError``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Repository root: ``<root>/src/cryptovira/config.py`` -> ``<root>``.
BASE_DIR: Path = Path(__file__).resolve().parents[2]

Environment = Literal["local", "ci", "staging", "production"]

# Only ever used when ENVIRONMENT=local or ci, and rejected everywhere else (see below).
_INSECURE_DEV_SECRET = "django-insecure-local-only-do-not-use-anywhere-real"  # noqa: S105


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables and ``.env``."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- deployment identity -------------------------------------------------
    environment: Environment = "local"
    debug: bool = False
    secret_key: SecretStr = SecretStr(_INSECURE_DEV_SECRET)
    allowed_hosts: list[str] = Field(default_factory=lambda: ["localhost", "127.0.0.1"])
    csrf_trusted_origins: list[str] = Field(default_factory=list)

    # --- datastores ----------------------------------------------------------
    database_url: str = "postgresql://cryptovira:cryptovira@localhost:5432/cryptovira"
    database_conn_max_age: int = 60
    redis_url: str = "redis://localhost:6379/0"

    # --- task queue ----------------------------------------------------------
    celery_broker_url: str = "amqp://cryptovira:cryptovira@localhost:5672//"
    #: ``django-db`` keeps results in Postgres so they survive a broker restart.
    celery_result_backend: str = "django-db"
    celery_task_always_eager: bool = False

    # --- observability -------------------------------------------------------
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True
    sentry_dsn: SecretStr | None = None

    # --- market data -----------------------------------------------------------
    #: A field, not a hardcoded constant in the source client, so tests/CI can point this at a
    #: mock server and staging can point it at a testnet — without a code change either way.
    market_data_base_url: str = "https://api.binance.com"
    market_data_request_timeout_seconds: float = 10.0

    @property
    def is_production_like(self) -> bool:
        """True for environments that must never run with dev defaults."""
        return self.environment in ("staging", "production")

    @field_validator("csrf_trusted_origins")
    @classmethod
    def _require_scheme_on_origins(cls, origins: list[str]) -> list[str]:
        """Django rejects scheme-less origins (and bare ``*``) with a system check at command
        time; catching it here turns a confusing mid-command failure into a startup error that
        names the offending value."""
        bad = [origin for origin in origins if not origin.startswith(("http://", "https://"))]
        if bad:
            msg = (
                f"CSRF_TRUSTED_ORIGINS entries must include a scheme, got {bad}. "
                'Use e.g. ["http://localhost:8000"] or ["https://*.cryptovira.com"] — '
                'a bare "*" is not accepted by Django.'
            )
            raise ValueError(msg)
        return origins

    @model_validator(mode="after")
    def _forbid_insecure_defaults_outside_dev(self) -> Self:
        if not self.is_production_like:
            return self
        if self.secret_key.get_secret_value() == _INSECURE_DEV_SECRET:
            msg = f"SECRET_KEY must be set explicitly when ENVIRONMENT={self.environment}"
            raise ValueError(msg)
        if self.debug:
            msg = f"DEBUG must be false when ENVIRONMENT={self.environment}"
            raise ValueError(msg)
        if not self.allowed_hosts:
            msg = f"ALLOWED_HOSTS must be set when ENVIRONMENT={self.environment}"
            raise ValueError(msg)
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
