"""Stripe Checkout, Customer Portal and webhook handling.

Design:
- Checkout session carries `client_reference_id = org_id` and `metadata.plan`.
- Webhooks are the single source of truth for `org.plan` / `plan_status`; the API never flips
  the plan on the redirect back from Checkout.
- Every event id is recorded in `stripe_events` first (unique) — a replayed delivery is
  acknowledged and ignored, so handlers are idempotent.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import stripe
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.billing.plans import PLANS
from app.config import settings
from app.models import Organization, StripeEvent
from app.services import audit

log = logging.getLogger(__name__)

HANDLED = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.payment_failed",
    "invoice.paid",
}


def _require_keys() -> None:
    if not settings.stripe_secret_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "billing is not configured")
    stripe.api_key = settings.stripe_secret_key


def _customer(db: Session, org: Organization, email: str | None) -> str:
    if org.stripe_customer_id:
        return org.stripe_customer_id
    cust = stripe.Customer.create(
        name=org.name, email=email or org.billing_email, metadata={"org_id": str(org.id)}
    )
    org.stripe_customer_id = cust.id
    org.billing_email = org.billing_email or email
    db.commit()
    return cust.id


def create_checkout(db: Session, org: Organization, plan_key: str, email: str | None) -> str:
    _require_keys()
    plan = PLANS.get(plan_key)
    if plan is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown plan {plan_key!r}")
    if not plan.price_id:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"no Stripe price for {plan_key}")
    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=_customer(db, org, email),
        client_reference_id=str(org.id),
        line_items=[{"price": plan.price_id, "quantity": 1}],
        allow_promotion_codes=True,
        success_url=f"{settings.web_base_url}/settings?billing=success",
        cancel_url=f"{settings.web_base_url}/settings?billing=cancelled",
        metadata={"org_id": str(org.id), "plan": plan_key},
        subscription_data={"metadata": {"org_id": str(org.id), "plan": plan_key}},
    )
    return session.url


def create_portal(db: Session, org: Organization, email: str | None) -> str:
    _require_keys()
    session = stripe.billing_portal.Session.create(
        customer=_customer(db, org, email),
        return_url=f"{settings.web_base_url}/settings",
    )
    return session.url


# --------------------------------------------------------------------------- webhooks
def parse_event(payload: bytes, signature: str | None) -> dict[str, Any]:
    if not settings.stripe_webhook_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "STRIPE_WEBHOOK_SECRET not set")
    if not signature:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing Stripe-Signature")
    try:
        stripe.Webhook.construct_event(payload, signature, settings.stripe_webhook_secret)
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid webhook: {exc}") from exc
    return json.loads(payload)  # verified above; plain dict keeps handlers SDK-version-proof


def _plan_from_subscription(sub: dict[str, Any]) -> str | None:
    meta = sub.get("metadata") or {}
    if meta.get("plan") in PLANS:
        return meta["plan"]
    items = (sub.get("items") or {}).get("data") or []
    for item in items:
        price = (item.get("price") or {}).get("id")
        for key, plan in PLANS.items():
            if price and price == plan.price_id:
                return key
    return None


def _find_org(db: Session, obj: dict[str, Any]) -> Organization | None:
    meta = obj.get("metadata") or {}
    org_ref = obj.get("client_reference_id") or meta.get("org_id")
    if org_ref:
        try:
            org = db.get(Organization, uuid.UUID(org_ref))
            if org:
                return org
        except ValueError:
            pass
    customer = obj.get("customer")
    if isinstance(customer, dict):
        customer = customer.get("id")
    if customer:
        return db.scalar(select(Organization).where(Organization.stripe_customer_id == customer))
    return None


def handle_event(db: Session, event: dict[str, Any]) -> str:
    """Apply one Stripe event. Returns 'duplicate' | 'ignored' | 'applied'."""
    event_id, etype = event["id"], event["type"]
    if db.execute(_insert_ignore(event_id, etype)).first() is None:
        db.commit()
        return "duplicate"
    if etype not in HANDLED:
        db.commit()
        return "ignored"

    obj = (event.get("data") or {}).get("object") or {}
    org = _find_org(db, obj)
    if org is None:
        log.warning("stripe event %s (%s): no matching org", event_id, etype)
        db.commit()
        return "ignored"
    before = audit.snapshot(org, ("plan", "plan_status", "stripe_subscription_id"))

    if etype == "checkout.session.completed":
        org.stripe_customer_id = org.stripe_customer_id or _as_id(obj.get("customer"))
        org.stripe_subscription_id = _as_id(obj.get("subscription"))
        plan = (obj.get("metadata") or {}).get("plan")
        if plan in PLANS:
            org.plan, org.plan_status = plan, "active"
        org.billing_email = org.billing_email or (obj.get("customer_details") or {}).get("email")
    elif etype in {"customer.subscription.created", "customer.subscription.updated"}:
        org.stripe_subscription_id = obj.get("id")
        plan = _plan_from_subscription(obj)
        if plan:
            org.plan = plan
        org.plan_status = obj.get("status") or org.plan_status
    elif etype == "customer.subscription.deleted":
        if org.stripe_subscription_id in (None, obj.get("id")):
            org.plan_status = "canceled"
            org.stripe_subscription_id = None
    elif etype == "invoice.payment_failed":
        org.plan_status = "past_due"
    elif etype == "invoice.paid":
        if org.plan in PLANS:
            org.plan_status = "active"

    after = audit.snapshot(org, ("plan", "plan_status", "stripe_subscription_id"))
    if after != before:
        audit.record(
            db,
            None,
            org_id=org.id,
            actor="stripe",
            action=f"billing.{etype}",
            entity="organization",
            entity_id=org.id,
            before=before,
            after=after,
        )
    db.commit()
    return "applied"


def _as_id(v: Any) -> str | None:
    if isinstance(v, dict):
        return v.get("id")
    return v


def _insert_ignore(event_id: str, etype: str):
    return (
        insert(StripeEvent)
        .values(id=uuid.uuid4(), event_id=event_id, type=etype, received_at=datetime.now(UTC))
        .on_conflict_do_nothing(index_elements=["event_id"])
        .returning(StripeEvent.id)
    )
