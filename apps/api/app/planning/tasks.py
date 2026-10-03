"""Celery: planning after the nightly forecast, plus on-demand."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Organization, PlanningRun
from app.planning.engine import run_planning
from app.worker import celery


@celery.task(name="planning.run_org", bind=True, max_retries=2, retry_backoff=120, acks_late=True)
def plan_org(self, run_id: str) -> dict:
    with SessionLocal() as db:
        run = db.get(PlanningRun, uuid.UUID(run_id))
        if run is None or run.status == "success":
            return {"status": "skipped"}
        run = run_planning(db, run)
        return {"status": run.status, "products": run.products_total}


@celery.task(name="planning.run_all_orgs")
def plan_all_orgs() -> int:
    with SessionLocal() as db:
        n = 0
        for org_id in db.scalars(select(Organization.id)).all():
            run = PlanningRun(org_id=org_id, trigger="nightly")
            db.add(run)
            db.commit()
            plan_org.delay(str(run.id))
            n += 1
    return n


def enqueue_planning(db: Session, org_id: uuid.UUID, *, trigger: str = "manual") -> PlanningRun:
    run = PlanningRun(org_id=org_id, trigger=trigger)
    db.add(run)
    db.commit()
    db.refresh(run)
    if settings.celery_task_always_eager:
        try:
            run_planning(db, run)
        except Exception:  # recorded on the run row
            pass
    else:
        plan_org.delay(str(run.id))
    return run
