"""Celery: nightly forecast per org after the 02:00 sync, plus on-demand."""

from __future__ import annotations

import uuid

from celery.utils.log import get_task_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.forecast.engine import DEFAULT_HORIZON, run_forecast
from app.models import ForecastRun, Organization
from app.worker import celery

log = get_task_logger(__name__)


@celery.task(name="forecast.run_org", bind=True, max_retries=2, retry_backoff=300, acks_late=True)
def forecast_org(self, run_id: str) -> dict:
    with SessionLocal() as db:
        run = db.get(ForecastRun, uuid.UUID(run_id))
        if run is None or run.status == "success":
            return {"status": "skipped"}
        try:
            run = run_forecast(db, run)
        except MemoryError as exc:  # transient on small workers
            raise self.retry(exc=exc) from exc
        return {"status": run.status, "skus": run.skus_total, "wape": str(run.wape)}


@celery.task(name="forecast.run_all_orgs")
def forecast_all_orgs() -> int:
    with SessionLocal() as db:
        n = 0
        for org_id in db.scalars(select(Organization.id)).all():
            run = ForecastRun(org_id=org_id, trigger="nightly", horizon_days=DEFAULT_HORIZON)
            db.add(run)
            db.commit()
            forecast_org.delay(str(run.id))
            n += 1
    return n


def enqueue_forecast(
    db: Session, org_id: uuid.UUID, *, trigger: str = "manual", horizon: int = DEFAULT_HORIZON
) -> ForecastRun:
    run = ForecastRun(org_id=org_id, trigger=trigger, horizon_days=horizon)
    db.add(run)
    db.commit()
    db.refresh(run)
    if settings.celery_task_always_eager:
        try:
            run_forecast(db, run)
        except Exception:  # recorded on the run row
            pass
    else:
        forecast_org.delay(str(run.id))
    return run
