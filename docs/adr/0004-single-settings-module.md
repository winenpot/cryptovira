# ADR 0004 — One settings module, typed environment configuration

**Status:** Accepted · 2026-08-13

## Context

The old project had `core/settings/{base,development,production,aws}.py` plus an empty
`core/settings/__init__.py` that `manage.py` pointed at by default — so running any management
command without setting `DJANGO_SETTINGS_MODULE` failed with a confusing error. `base.py` contained
literal API keys and bot tokens. Because each module could override anything, the only way to know
what production actually ran was to read all four files and the compose overlays together.

Two failure modes followed from this: secrets in version control, and configuration bugs that only
appeared in the environment nobody could run locally.

## Decision

**One** Django settings module (`src/cryptovira/settings.py`), whose variable parts come from a
validated `pydantic-settings` object (`src/cryptovira/config.py`).

- Environment variables are read in exactly one place. `os.environ` appears nowhere else.
- Every variable is typed, so `DEBUG=1`, `DEBUG=true`, and `DEBUG=yes` all parse, and
  `DATABASE_CONN_MAX_AGE=sixty` fails at boot with a field-level error.
- Cross-field rules are validators: staging/production refuse the development `SECRET_KEY`, refuse
  `DEBUG=true`, and require `ALLOWED_HOSTS`. A misconfigured deploy fails to start rather than
  starting insecurely — the loudest possible failure at the cheapest possible time.
- Secrets are `SecretStr`, so they do not appear in logs, tracebacks, or `repr()`.
- `.env.example` is the documented contract; `.env` is gitignored and `gitleaks` runs pre-commit.

## Consequences

- Adding configuration means adding a typed field plus an `.env.example` line — slightly more
  ceremony than `os.environ.get("FOO")`, and that ceremony is the point.
- Settings differences between environments are visible as data (`env | grep`), not as code.
- Tests construct `Settings(_env_file=None, …)` directly, so configuration rules are unit-testable
  without touching the real environment — see `tests/test_config.py`.
- One extra runtime dependency (`pydantic-settings`), already pulled in by other tooling.

## We would revisit if

Secrets moved into a manager like AWS Secrets Manager or Vault, in which case `config.py` would
grow a source that fetches at boot — still one place, still validated.
