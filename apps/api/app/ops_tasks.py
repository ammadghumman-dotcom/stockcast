"""Celery: ops.check_health every 15 minutes -> alerts (see app/ops.py)."""

from __future__ import annotations

from celery.utils.log import get_task_logger

from app.db import SessionLocal
from app.ops import run_checks
from app.worker import celery

log = get_task_logger(__name__)


@celery.task(name="ops.check_health")
def check_health() -> int:
    with SessionLocal() as db:
        raised = run_checks(db)
    if raised:
        log.warning("ops alerts raised: %s", raised)
    return len(raised)
