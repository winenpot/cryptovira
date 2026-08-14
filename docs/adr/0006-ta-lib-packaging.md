# ADR 0006 — TA-Lib via prebuilt wheels, no compile toolchain

**Status:** Accepted · 2026-08-14

## Context

TA-Lib is a C library; `old-version/devops/Dockerfile` and every "install TA-Lib in Docker"
tutorial from the last decade (e.g. the widely-linked
[artiya4u.medium.com article](https://artiya4u.medium.com/building-docker-image-for-python-app-with-ta-lib-c2fc4516a648))
follows the same shape: `apt-get install build-essential`, download and `./configure && make &&
make install` the C library from source, `pip install TA-Lib`, then — in a careful multi-stage
build — discard the compiler and build tools so they don't ship in the production image.
`docs/roadmap.md` flagged this exact trade-off ("bundled wheels vs a pure-Python implementation")
as needing its own decision before step 4.

That trade-off turned out to be moot. As of `ta-lib-python` **0.6.5** (May 2025), the project
publishes prebuilt wheels via GitHub Actions for Linux (`manylinux2014`/`manylinux_2_28`,
x86_64 and aarch64), Windows, and macOS, across CPython 3.9–3.14. manylinux/Windows wheel policy
requires third-party shared-library dependencies to be **vendored inside the wheel** (via
`auditwheel`/`delvewheel`) — so the C library ships *inside* `ta_lib-0.7.1-*.whl`, not as a
separate system dependency the wheel merely links against.

## Decision

Depend on plain `ta-lib>=0.7.1` (`pyproject.toml`) with no Dockerfile changes and no build-stage
apt packages. Verified directly rather than assumed:

- `uv add ta-lib` on this Windows dev machine installed a wheel — no compiler invoked, confirmed
  by the absence of any build step in `uv`'s output.
- The existing `docker/Dockerfile` (unmodified) produces an image where `import talib` and real
  indicator calls (`SMA`, `RSI`) work, using only the runtime stage's existing `libpq5`/`curl` —
  no `libta-lib0`, no build-essential, added or removed.
- `tests/test_talib.py` pins this down permanently: function-count sanity check, a hand-computed
  SMA value, and an RSI-bounds check, so a future dependency bump that silently regresses to a
  source build (no matching wheel for a new Python version, e.g.) fails CI immediately instead of
  surfacing as a mysterious production crash.

## Consequences

- Zero image-size or attack-surface cost: no compiler ever enters even the builder stage for this
  dependency, so there's nothing to "delete safely afterward" — the multi-stage cleanup step that
  every tutorial describes doesn't apply here.
- Tied to upstream publishing wheels for our exact interpreter/platform combination. `cp314` wheels
  exist today for every platform this project targets (checked directly against PyPI's file list,
  not assumed); if a future CPython bump outruns upstream's wheel builds, `uv sync` would fall
  back to a source build and this ADR's "no compiler needed" claim would need re-verifying — at
  which point the old apt-get/configure/make approach is the fallback, not a rewrite of the
  decision.
- TA-Lib actually ships `py.typed` plus real `.pyi` stubs for the indicator functions
  (`SMA`/`RSI`/etc. are fully typed) — no `ignore_missing_imports` entry needed or added. The one
  gap found: `get_functions()` itself is a plain, unannotated function in `talib/__init__.py`,
  handled with a narrow, commented `# type: ignore[no-untyped-call]` at its one call site
  (`tests/test_talib.py`) rather than a blanket module ignore that would also hide real bugs in
  the (properly typed) indicator calls the strategy engine will actually depend on.

## We would revisit if

A CPython version this project needs ships without a corresponding `ta-lib` wheel, or if the
pure-Python reimplementation (mentioned as the roadmap's other option) becomes preferable for
reasons unrelated to packaging — e.g. wanting indicator logic to be readable/steppable Python
for the interview-study goal, not just correct.
