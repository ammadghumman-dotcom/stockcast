"""Sync tasks. Idempotent: every write is an upsert, so a retried run converges."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from celery.utils.log import get_task_logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.plans import PlanLimitError, assert_can_add_skus
from app.config import settings
from app.db import SessionLocal
from app.ingest import upsert
from app.ingest.base import ConnectorError
from app.ingest.registry import connector_for
from app.models import Channel, ChannelType, SyncRun
from app.worker import celery

log = get_task_logger(__name__)


def run_sync(db: Session, run: SyncRun, *, full: bool = False) -> SyncRun:
    """Execute one SyncRun synchronously. Raises ConnectorError on upstream failure."""
    channel = db.get(Channel, run.channel_id)
    if channel is None:
        run.status, run.error = "failed", "channel not found"
        db.commit()
        return run
    run.status, run.started_at, run.attempts = "running", datetime.now(UTC), run.attempts + 1
    db.commit()
    try:
        conn = connector_for(channel)
        since = _since(channel, full)

        products = list(conn.fetch_products())
        assert_can_add_skus(
            db, channel.org_id, upsert.count_new_skus(db, channel.org_id, products, channel)
        )
        r = upsert.upsert_products(db, channel.org_id, products, channel)
        run.rows_products = r.inserted + r.updated
        r = upsert.upsert_sales(db, channel.org_id, channel, conn.fetch_sales(since))
        run.rows_sales = r.inserted
        r = upsert.upsert_inventory(db, channel.org_id, conn.fetch_inventory(), channel)
        run.rows_inventory = r.inserted

        channel.last_synced_at = datetime.now(UTC)
        run.status, run.finished_at = "success", datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        msg = exc.message if isinstance(exc, PlanLimitError) else str(exc)
        run.status, run.error, run.finished_at = "failed", msg[:2000], datetime.now(UTC)
        db.commit()
        raise
    return run


def _since(channel: Channel, full: bool) -> date:
    today = date.today()
    if full or channel.last_synced_at is None:
        return today - timedelta(days=settings.shopify_backfill_days)
    # overlap 7 days so late edits/refunds are picked up (upsert = SET, so no double count)
    return channel.last_synced_at.date() - timedelta(days=7)


@celery.task(
    name="ingest.sync_channel",
    bind=True,
    autoretry_for=(ConnectorError,),
    retry_backoff=60,  # 60s, 120s, 240s, 480s, 960s
    retry_backoff_max=3600,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def sync_channel(self, run_id: str, full: bool = False) -> dict:
    with SessionLocal() as db:
        run = db.get(SyncRun, uuid.UUID(run_id))
        if run is None:
            return {"status": "missing"}
        if run.status == "success":
            return {"status": "already-done"}  # redelivered message after ack loss
        try:
            run = run_sync(db, run, full=full)
        except ConnectorError:
            if self.request.retries >= self.max_retries:
                notify_sync_failed(db, run)
            raise
        except Exception:
            notify_sync_failed(db, run)  # not retried: plan limit, bug, bad data
            raise
        return {"status": run.status, "sales": run.rows_sales}


def notify_sync_failed(db: Session, run: SyncRun) -> None:
    from app.emails import send_sync_failed

    try:
        send_sync_failed(db, run)
    except Exception:  # never let email break the task
        log.exception("sync_failed email for run %s", run.id)


@celery.task(name="ingest.sync_all_channels")
def sync_all_channels() -> int:
    """Nightly: enqueue a sync for every active, connected, non-CSV channel."""
    with SessionLocal() as db:
        channels = db.scalars(
            select(Channel).where(
                Channel.is_active.is_(True),
                Channel.type != ChannelType.csv,
                Channel.credentials_encrypted.is_not(None),
            )
        ).all()
        n = 0
        for ch in channels:
            run = SyncRun(org_id=ch.org_id, channel_id=ch.id, trigger="nightly")
            db.add(run)
            db.commit()
            sync_channel.delay(str(run.id))
            n += 1
    return n


def enqueue_sync(db: Session, channel: Channel, *, trigger: str, full: bool = False) -> SyncRun:
    run = SyncRun(org_id=channel.org_id, channel_id=channel.id, trigger=trigger)
    db.add(run)
    db.commit()
    db.refresh(run)
    if settings.celery_task_always_eager:
        # In tests/dev-without-redis run inline on the caller's session so rollback works.
        try:
            run_sync(db, run, full=full)
        except ConnectorError:
            pass  # recorded on the run row
    else:
        sync_channel.delay(str(run.id), full)
    return run
