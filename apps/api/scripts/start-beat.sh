#!/bin/sh
# Celery beat: exactly ONE replica. Schedule lives in app/worker.py.
set -e
exec uv run --no-dev celery -A app.worker beat -l info --schedule /tmp/celerybeat-schedule
