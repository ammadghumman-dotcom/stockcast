"""Celery application. Run: `celery -A app.worker worker -B -l info`."""

from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery = Celery(
    "stockcast",
    broker=settings.celery_broker_url,
    include=["app.ingest.tasks", "app.forecast.tasks"],
)
celery.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    timezone="UTC",
    beat_schedule={
        "nightly-sync-all-channels": {
            "task": "ingest.sync_all_channels",
            "schedule": crontab(hour=2, minute=0),
        },
        "nightly-forecast-all-orgs": {
            "task": "forecast.run_all_orgs",
            "schedule": crontab(hour=3, minute=30),  # after syncs have landed
        },
    },
)
