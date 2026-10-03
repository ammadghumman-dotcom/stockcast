#!/bin/sh
# Celery worker. Forecasting is CPU-bound (one AutoETS/Chronos process per vCPU), so
# CELERY_CONCURRENCY defaults to the vCPU count. Capacity: ~5.6 SKU/s per process
# (scripts/bench_forecast.py) -> 50 orgs x 2,000 SKUs needs >= 5 processes for the 60-min window.
set -e
CPUS="$(nproc 2>/dev/null || echo 2)"
exec uv run --no-dev celery -A app.worker worker -l info \
  --concurrency="${CELERY_CONCURRENCY:-$CPUS}" \
  --max-tasks-per-child="${CELERY_MAX_TASKS_PER_CHILD:-50}" \
  -Q "${CELERY_QUEUES:-celery}"
