# syntax=docker/dockerfile:1.9
#
# Multi-stage build. The builder resolves and installs dependencies; the runtime image gets the
# finished virtualenv and the source, nothing else — no uv, no compilers, no lockfile.

ARG PYTHON_VERSION=3.14
ARG UV_VERSION=0.12.3

# ----------------------------------------------------------------------- builder
FROM python:${PYTHON_VERSION}-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12.3 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv 

WORKDIR /app

# Dependencies first, in their own layer: they change far less often than application code,
# so an edit to a view does not re-resolve the dependency graph.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=README.md,target=README.md \
    uv sync --frozen --no-install-project --no-dev

COPY pyproject.toml uv.lock README.md manage.py ./
COPY src/ ./src/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ----------------------------------------------------------------------- runtime
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=cryptovira.settings

# libpq is needed at runtime even with psycopg[binary]'s bundled libs on some platforms;
# curl is here only so the container healthcheck has something to call.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid app --create-home app

WORKDIR /app

COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app manage.py pyproject.toml README.md ./
COPY --chown=app:app src/ ./src/
COPY --chown=app:app docker/entrypoint.sh /usr/local/bin/entrypoint.sh

# /app/run holds runtime state the app writes (celery beat's schedule file). Everything else
# under /app stays read-only to the app user.
RUN chmod +x /usr/local/bin/entrypoint.sh && mkdir -p /app/staticfiles /app/media /app/run \
    && chown app:app /app/staticfiles /app/media /app/run

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

ENTRYPOINT ["entrypoint.sh"]
CMD ["web"]
