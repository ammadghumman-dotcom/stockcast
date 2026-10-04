"""Operational checks that turn into alerts (Celery beat every 15 minutes).

- sync failure rate over the last 24 h > ALERT_SYNC_FAILURE_RATE (default 5 %)
- any forecast run that took, or has been running, longer than ALERT_FORECAST_MAX_MINUTES
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import ForecastRun, SyncRun
from app.observability import alert


def sync_failure_rate(db: Session, since: datetime) -> tuple[float, int, int]:
    total, failed = db.execute(
        select(
            func.count(),
            func.count().filter(SyncRun.status == "failed"),
        ).where(SyncRun.created_at >= since, SyncRun.status.in_(["success", "failed"]))
    ).one()
    total, failed = int(total or 0), int(failed or 0)
    return (failed / total if total else 0.0), failed, total


def slow_forecast_runs(db: Session, since: datetime, max_minutes: int) -> list[ForecastRun]:
    limit = timedelta(minutes=max_minutes)
    now = datetime.now(UTC)
    runs = db.scalars(
        select(ForecastRun).where(
            ForecastRun.created_at >= since, ForecastRun.started_at.is_not(None)
        )
    ).all()
    out = []
    for r in runs:
        assert r.started_at is not None
        end = r.finished_at or now
        if end - r.started_at > limit:
            out.append(r)
    return out


def run_checks(db: Session, now: datetime | None = None) -> list[dict]:
    """Evaluate every check; fire alerts; return the alerts raised (for tests / logs)."""
    now = now or datetime.now(UTC)
    since = now - timedelta(hours=24)
    raised: list[dict] = []
    rate, failed, total = sync_failure_rate(db, since)
    if total >= 5 and rate > settings.alert_sync_failure_rate:
        detail = {"failed": failed, "total": total, "rate": f"{rate:.1%}", "window": "24h"}
        alert("Channel sync failure rate above threshold", detail)
        raised.append({"check": "sync_failure_rate", **detail})
    for r in slow_forecast_runs(db, since, settings.alert_forecast_max_minutes):
        assert r.started_at is not None
        mins = ((r.finished_at or now) - r.started_at).total_seconds() / 60
        detail = {
            "run_id": str(r.id),
            "org_id": str(r.org_id),
            "status": r.status,
            "minutes": f"{mins:.0f}",
            "skus": r.skus_total,
        }
        alert("Forecast run exceeded time budget", detail, level="warning")
        raised.append({"check": "forecast_duration", **detail})
    return raised
