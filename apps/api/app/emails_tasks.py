"""Scheduled transactional email: trial-ending reminders (daily) and the stockout digest (Mon)."""

from __future__ import annotations

from datetime import date

from celery.utils.log import get_task_logger
from sqlalchemy import select

from app import emails
from app.db import SessionLocal
from app.models import Organization
from app.worker import celery

log = get_task_logger(__name__)


@celery.task(name="emails.trial_ending")
def trial_ending() -> int:
    """Daily 09:00 UTC: email orgs whose trial ends in 3 days or tomorrow (deduped per day-left)."""
    n = 0
    with SessionLocal() as db:
        for org, days_left in emails.trial_ending_orgs(db):
            if emails.send_trial_ending(db, org, days_left) is not None:
                n += 1
    return n


@celery.task(name="emails.weekly_digest")
def weekly_digest() -> int:
    """Monday 07:00 UTC: stockout digest from each org's latest successful planning run."""
    n = 0
    with SessionLocal() as db:
        for org in db.scalars(select(Organization)).all():
            run = emails.latest_run_for_digest(db, org.id)
            if run is None:
                continue
            if emails.send_weekly_digest(db, org, run, date.today()) is not None:
                n += 1
    return n
