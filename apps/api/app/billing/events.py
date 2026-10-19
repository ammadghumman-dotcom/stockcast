"""Apply a provider-neutral `BillingUpdate` to an organization (Lemon Squeezy, Paddle).

Same rules as the Stripe handler: webhooks are the only thing that changes `org.plan`; each
delivery is recorded in `billing_events` first (unique per provider) so replays are no-ops;
every change is audited with before/after.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.billing.plans import PLANS
from app.billing.providers.base import CANCELED, BillingUpdate
from app.models import BillingEvent, Organization
from app.services import audit

log = logging.getLogger(__name__)
FIELDS = ("plan", "plan_status", "billing_provider", "billing_subscription_id")
ENDING = {CANCELED, "unpaid", "paused"}


def _find_org(db: Session, provider: str, upd: BillingUpdate) -> Organization | None:
    if upd.org_ref:
        try:
            org = db.get(Organization, uuid.UUID(str(upd.org_ref)))
        except ValueError:
            org = None
        if org is not None:
            return org
    conds = []
    if upd.subscription_id:
        conds.append(Organization.billing_subscription_id == upd.subscription_id)
    if upd.customer_id:
        conds.append(Organization.billing_customer_id == upd.customer_id)
    if not conds:
        return None
    return db.scalar(
        select(Organization).where(Organization.billing_provider == provider, or_(*conds))
    )


def apply(db: Session, provider: str, upd: BillingUpdate | None) -> str:
    """Returns 'ignored' | 'duplicate' | 'applied'."""
    if upd is None:
        return "ignored"
    if not upd.event_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "event has no id")
    inserted = db.execute(
        insert(BillingEvent)
        .values(
            id=uuid.uuid4(),
            provider=provider,
            event_id=upd.event_id[:200],
            type=upd.type[:100],
            received_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(constraint="uq_billing_events_provider_event")
        .returning(BillingEvent.id)
    ).first()
    if inserted is None:
        db.commit()
        return "duplicate"
    org = _find_org(db, provider, upd)
    if org is None:
        log.warning("%s event %s (%s): no matching org", provider, upd.event_id, upd.type)
        db.commit()
        return "ignored"

    before = audit.snapshot(org, FIELDS)
    current = org.billing_subscription_id if org.billing_provider == provider else None
    other_sub = bool(current and upd.subscription_id and upd.subscription_id != current)
    if other_sub and (upd.status in ENDING or upd.status is None):
        # an old subscription ending (or paying) must not touch the one now in use
        db.commit()
        return "ignored"

    org.billing_provider = provider
    org.billing_customer_id = upd.customer_id or org.billing_customer_id
    if upd.subscription_id:
        org.billing_subscription_id = upd.subscription_id
    if upd.email and not org.billing_email:
        org.billing_email = upd.email
    if upd.plan in PLANS:
        org.plan = upd.plan
    if upd.status:
        org.plan_status = upd.status
        if upd.status == CANCELED:
            org.billing_subscription_id = None

    after = audit.snapshot(org, FIELDS)
    if after != before:
        audit.record(
            db,
            None,
            org_id=org.id,
            actor=provider,
            action=f"billing.{provider}.{upd.type}"[:60],
            entity="organization",
            entity_id=org.id,
            before=before,
            after=after,
        )
    db.commit()
    return "applied"
