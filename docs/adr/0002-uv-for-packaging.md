# ADR 0002 — uv for packaging and the Python toolchain

**Status:** Accepted · 2026-08-13

## Context

The old project used `requirements.txt` plus `requirements.stubs.txt`, unpinned transitively. A
`pip install -r requirements.txt` in 2020 and the same command in 2026 produce different trees, so
"works on my machine" was structural, not anecdotal. It also assumed a system Python of the right
version, which every developer and CI runner had to arrange for themselves.

Candidates: pip + pip-tools, Poetry, PDM, uv.

## Decision

Use **uv** as the single tool for the interpreter, the virtualenv, dependency resolution, the
lockfile, and running commands.

- `requires-python = ">=3.14,<3.15"` and `.python-version` pin the interpreter; uv downloads it.
  No system Python is required — this machine has none, and the project still builds.
- `pyproject.toml` (PEP 621) holds runtime dependencies; PEP 735 `[dependency-groups]` holds dev
  dependencies, which are *not* shipped in the runtime image (`uv sync --no-dev`).
- `uv.lock` is committed and is the source of truth. CI runs `uv sync --frozen`, which fails if the
  lock and `pyproject.toml` disagree instead of quietly re-resolving.
- Every command is `uv run …`, so there is no "did I activate the venv?" failure mode.
- One config file: ruff, mypy, pytest, and coverage settings all live in `pyproject.toml`. The old
  project had `mypy.ini`, `.pre-commit-config.yaml`, `pyproject.toml`, and `setup.cfg` fragments.

Why uv over the alternatives: it is a single static binary (nothing to bootstrap in the Docker
builder beyond `pip install uv==<pin>`), resolution and installs are 10–100× faster than pip, it
manages interpreters as well as packages, and the lockfile is cross-platform — the same
`uv.lock` resolves on Windows laptops and Linux CI.

## Consequences

- Contributors need uv installed (one command, no Python prerequisite).
- Dependencies are added with `uv add`, never by hand-editing `pyproject.toml`, so the lock stays
  in step. A pre-commit hook (`uv-lock`) enforces this.
- Upgrades are deliberate: `uv lock --upgrade` produces a reviewable diff.
- uv is younger than pip; the mitigation is that its outputs are standard (`pyproject.toml` is
  PEP 621, the venv is a normal venv) so migrating away would not require reworking the project.

## We would revisit if

uv's maintenance stalled, or a dependency required a build backend uv could not drive.
