"""Product analytics: activation milestones (our db) + event capture (PostHog).

`track()` is called from request handlers after the main write. It records first-time
milestones in `org_milestones` (the source of truth for the weekly cohort report) and queues
the event for PostHog. Analytics must never break a request: every failure is logged and
swallowed.

Events
- channel_connected      every store/marketplace connection (props: type, first)
- forecast_viewed        first time a workspace opens a product forecast (milestone only)
- po_created             every draft PO batch (props: count, first)
Milestones: first_channel_connected, first_forecast_viewed, first_po_created.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models import OrgMilestone

log = logging.getLogger(__name__)

MILESTONES = {
    "channel_connected": "first_channel_connected",
    "forecast_viewed": "first_forecast_viewed",
    "po_created": "first_po_created",
}
ONLY_FIRST = {"forecast_viewed"}  # high-volume reads: capture the milestone, not every view


def reach(db: Session, org_id: uuid.UUID, key: str, props: dict[str, Any] | None = None) -> bool:
    """Record a milestone once per workspace. True only the first time (caller commits)."""
    row = db.execute(
        pg_insert(OrgMilestone)
        .values(id=uuid.uuid4(), org_id=org_id, key=key, at=datetime.now(UTC), props=props)
        .on_conflict_do_nothing(constraint="uq_org_milestones_org_key")
        .returning(OrgMilestone.id)
    ).first()
    return row is not None


def track(
    db: Session,
    org_id: uuid.UUID,
    event: str,
    *,
    user_id: uuid.UUID | None = None,
    props: dict[str, Any] | None = None,
    commit: bool = True,
) -> bool:
    """Record the milestone (if any) and queue the event. Returns whether this was a first."""
    props = dict(props or {})
    first = False
    try:
        milestone = MILESTONES.get(event)
        if milestone:
            with db.begin_nested():
                first = reach(db, org_id, milestone, props or None)
            if commit:
                db.commit()
        props["first"] = first
        if event not in ONLY_FIRST:
            capture(event, org_id, user_id, props)
        if first and milestone:
            capture(milestone, org_id, user_id, props)
    except Exception:  # pragma: no cover - analytics never breaks a request
        log.exception("analytics track %s failed", event)
    return first


def capture(
    event: str, org_id: uuid.UUID, user_id: uuid.UUID | None, props: dict[str, Any]
) -> None:
    if not settings.posthog_api_key:
        return
    from app.analytics_tasks import capture_event

    payload = {
        "api_key": settings.posthog_api_key,
        "event": event,
        "distinct_id": str(user_id) if user_id else f"org:{org_id}",
        "timestamp": datetime.now(UTC).isoformat(),
        "properties": {
            **props,
            "org_id": str(org_id),
            "env": settings.env,
            "$groups": {"organization": str(org_id)},
        },
    }
    try:
        capture_event.delay(payload)
    except Exception:  # broker down: drop the event rather than fail the request
        log.warning("analytics: could not queue %s", event)
