"""Celery application. Run: `celery -A app.worker worker -B -l info`."""

from celery import Celery
from celery.schedules import crontab

from app.config import settings
from app.observability import configure_logging, configure_sentry, configure_tracing

configure_logging()
configure_sentry("worker")
configure_tracing()

celery = Celery(
    "stockcast",
    broker=settings.celery_broker_url,
    include=[
        "app.ingest.tasks",
        "app.forecast.tasks",
        "app.planning.tasks",
        "app.emails_tasks",
        "app.ops_tasks",
    ],
)
celery.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=3 * 3600,  # a runaway forecast never blocks a worker forever
    task_soft_time_limit=3 * 3600 - 60,
    broker_connection_retry_on_startup=True,
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
        "nightly-planning-all-orgs": {
            "task": "planning.run_all_orgs",
            "schedule": crontab(hour=4, minute=30),  # after forecasts
        },
        "weekly-stockout-digest": {
            "task": "emails.weekly_digest",
            "schedule": crontab(hour=7, minute=0, day_of_week="mon"),
        },
        "daily-trial-ending": {
            "task": "emails.trial_ending",
            "schedule": crontab(hour=9, minute=0),
        },
        "ops-check-health": {
            "task": "ops.check_health",
            "schedule": crontab(minute="*/15"),
        },
    },
)
