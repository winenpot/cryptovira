#!/usr/bin/env bash
# Container entrypoint: one image, several roles. `web`, `worker`, `beat`, or any raw command.
#
# Migrations are deliberately NOT run here — three replicas starting at once would race.
# Run them as a one-off (`docker compose run --rm web migrate`) or a deploy job.
set -euo pipefail

role="${1:-web}"
shift || true

case "${role}" in
  web)
    exec gunicorn cryptovira.asgi:application \
      --worker-class uvicorn_worker.UvicornWorker \
      --bind "0.0.0.0:${PORT:-8000}" \
      --workers "${WEB_CONCURRENCY:-3}" \
      --timeout "${WEB_TIMEOUT:-60}" \
      --access-logfile - \
      --error-logfile -
    ;;
  devserver)
    exec python manage.py runserver 0.0.0.0:"${PORT:-8000}"
    ;;
  worker)
    exec celery -A cryptovira worker \
      --loglevel="${CELERY_LOG_LEVEL:-info}" \
      --queues="${CELERY_QUEUES:-default,market,strategy,orders,notifications}" \
      --concurrency="${CELERY_CONCURRENCY:-4}"
    ;;
  beat)
    # Beat persists each task's last run time to this file. It defaults to the working
    # directory, which the non-root user cannot write — hence an explicit writable path.
    exec celery -A cryptovira beat \
      --loglevel="${CELERY_LOG_LEVEL:-info}" \
      --schedule="${CELERY_BEAT_SCHEDULE_PATH:-/app/run/celerybeat-schedule}"
    ;;
  migrate)
    exec python manage.py migrate --noinput
    ;;
  *)
    exec "${role}" "$@"
    ;;
esac
