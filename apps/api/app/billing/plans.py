"""Plan catalogue and limit enforcement.

trial     — 14 days, Growth limits, no card
starter   — $39/mo:  1 channel,   500 SKUs
growth    — $99/mo:  3 channels, 5,000 SKUs
scale     — $249/mo: unlimited

`effective_plan` collapses an expired trial / unpaid subscription to "locked" (Starter limits,
so existing data stays readable but nothing new can be added). While billing is disabled (no
payment provider configured) an expired trial keeps Trial limits — nobody can pay, so nobody is
locked out.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Channel, Organization, Product

UNLIMITED = 10**9


@dataclass(frozen=True)
class Plan:
    key: str
    name: str
    price_usd: int
    channels: int
    skus: int

    @property
    def price_id(self) -> str:
        return {
            "starter": settings.stripe_price_starter,
            "growth": settings.stripe_price_growth,
            "scale": settings.stripe_price_scale,
        }.get(self.key, "")


PLANS: dict[str, Plan] = {
    "starter": Plan("starter", "Starter", 39, 1, 500),
    "growth": Plan("growth", "Growth", 99, 3, 5_000),
    "scale": Plan("scale", "Scale", 249, UNLIMITED, UNLIMITED),
}
TRIAL = Plan("trial", "Trial", 0, PLANS["growth"].channels, PLANS["growth"].skus)
LOCKED = Plan("locked", "Locked", 0, 0, 0)

ACTIVE_STATUSES = {"active", "trialing", "past_due"}  # past_due keeps working during dunning


def effective_plan(org: Organization, now: datetime | None = None) -> Plan:
    now = now or datetime.now(UTC)
    if org.plan in PLANS:
        return PLANS[org.plan] if org.plan_status in ACTIVE_STATUSES else LOCKED
    # trial
    # Shopify-installed workspaces always have billing (Shopify Billing API); others need Stripe
    billing_on = settings.billing_enabled or org.shopify_shop is not None
    if org.trial_ends_at is None or org.trial_ends_at > now or not billing_on:
        return TRIAL
    return LOCKED


def limits_for(org: Organization) -> dict[str, int | None]:
    p = effective_plan(org)
    return {
        "channels": None if p.channels >= UNLIMITED else p.channels,
        "skus": None if p.skus >= UNLIMITED else p.skus,
    }


def usage_for(db: Session, org_id: uuid.UUID) -> dict[str, int]:
    """Counts toward plan limits; sample data (onboarding demo) never does."""
    channels = db.scalar(
        select(func.count())
        .select_from(Channel)
        .where(Channel.org_id == org_id, Channel.is_sample.is_(False))
    )
    skus = db.scalar(
        select(func.count())
        .select_from(Product)
        .where(Product.org_id == org_id, Product.is_sample.is_(False))
    )
    return {"channels": int(channels or 0), "skus": int(skus or 0)}


def _org(db: Session, org_id: uuid.UUID) -> Organization:
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Unknown organization")
    return org


class PlanLimitError(HTTPException):
    """402 with a human message; Celery tasks catch it to fail a sync without retrying."""

    def __init__(self, msg: str, plan: Plan) -> None:
        super().__init__(status.HTTP_402_PAYMENT_REQUIRED, {"detail": msg, "plan": plan.key})
        self.message = msg


def _limit_error(what: str, plan: Plan, limit: int) -> PlanLimitError:
    if plan is LOCKED:
        msg = "Your trial has ended or your subscription is inactive. Choose a plan to continue."
    else:
        msg = f"{plan.name} plan allows {limit:,} {what}. Upgrade to add more."
    return PlanLimitError(msg, plan)


def assert_can_add_channel(db: Session, org_id: uuid.UUID, adding: int = 1) -> None:
    plan = effective_plan(_org(db, org_id))
    if plan.channels >= UNLIMITED:
        return
    current = usage_for(db, org_id)["channels"]
    if current + adding > plan.channels:
        raise _limit_error("sales channel(s)", plan, plan.channels)


def assert_can_add_skus(db: Session, org_id: uuid.UUID, adding: int) -> None:
    """`adding` = number of NEW products the operation would create."""
    if adding <= 0:
        return
    plan = effective_plan(_org(db, org_id))
    if plan.skus >= UNLIMITED:
        return
    current = usage_for(db, org_id)["skus"]
    if current + adding > plan.skus:
        raise _limit_error("SKUs", plan, plan.skus)
