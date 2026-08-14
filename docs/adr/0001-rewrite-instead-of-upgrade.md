# ADR 0001 — Rewrite rather than incrementally upgrade

**Status:** Accepted · 2026-08-13

## Context

The existing system (`old-version/`) is a Django monolith started in 2019:

- Django 3.x-era code, dependencies pinned to versions with known CVEs and no wheels for modern
  Python; `requirements.txt` with no lockfile, so no two installs are identical.
- Secrets — API keys, bot tokens, gateway credentials — committed in `core/settings/base.py`.
- Four settings modules and four docker-compose overlays that had drifted apart; the effective
  configuration of production was not knowable from the repository.
- Zero real tests: every `tests.py` is the empty Django stub.
- Large amounts of dead code (a vendored fork of `python-binance`, an unused React bundle, two
  standalone services duplicating logic that also exists inside Django).
- The Celery beat schedule lived in database rows written at runtime, so the live schedule could
  differ from the code with no record of when it changed.

The usual argument for incremental upgrade — "the tests will catch regressions" — does not apply
here, because there are no tests. Upgrading dependency-by-dependency through six years of breaking
changes, with no safety net and no ability to reproduce an environment, is slower and riskier than
rebuilding on a modern base while keeping the old code as an executable specification.

## Decision

Rebuild at the repository root on a current toolchain (Python 3.14, Django 6.1, uv, Postgres 18),
in ordered steps (`docs/roadmap.md`), each landing with tests and types. Keep `old-version/` on
disk, untracked and excluded from every tool, as the reference for *what the system did*.

Behaviour is ported, not code. A ported feature is done when it has tests that would have caught
the bug the old implementation had.

## Consequences

- Nothing ships until enough steps land; there is a window where the old system is the only
  working one. Acceptable: it is not currently in production.
- Every ported behaviour must be re-derived from the old source, which is slow but is exactly how
  the undocumented business rules get written down.
- Some old behaviour will be deliberately dropped (see the roadmap's table). Each drop is recorded
  rather than silently lost.

## We would revisit if

The old system had to run in production concurrently with the new one, in which case a
strangler-fig migration behind a shared database would beat a clean rewrite.
