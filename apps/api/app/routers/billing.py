"""Billing: plan + usage, checkout / portal via the active provider, provider webhooks."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.billing import (
    PLANS,
    effective_plan,
    events,
    limits_for,
    providers,
    stripe_service,
    usage_for,
)
from app.config import settings
from app.deps import DB, Ctx
from app.models import Organization
from app.services import audit

router = APIRouter(tags=["billing"])


class PlanInfo(BaseModel):
    key: str
    name: str
    price_usd: int
    channels: int | None
    skus: int | None


class BillingRead(BaseModel):
    plan: str  # what the org is on: trial | starter | growth | scale
    plan_status: str
    effective_plan: str  # what limits apply right now (trial | starter | ... | locked)
    trial_ends_at: datetime | None
    billing_email: str | None
    has_subscription: bool
    billing_enabled: bool  # false -> no payment provider configured; hide checkout in the UI
    billing_provider: str | None  # who takes new payments: lemonsqueezy | paddle | stripe
    limits: dict[str, int | None]
    usage: dict[str, int]
    plans: list[PlanInfo]


class CheckoutRequest(BaseModel):
    plan: str = Field(pattern="^(starter|growth|scale)$")


class UrlResponse(BaseModel):
    url: str


def _org(db: Session, ctx) -> Organization:
    org = db.get(Organization, ctx.org_id)
    assert org is not None
    return org


@router.get("/billing", response_model=BillingRead)
def read_billing(db: DB, ctx: Ctx) -> BillingRead:
    org = _org(db, ctx)
    eff = effective_plan(org)
    return BillingRead(
        plan=org.plan,
        plan_status=org.plan_status,
        effective_plan=eff.key,
        trial_ends_at=org.trial_ends_at,
        billing_email=org.billing_email,
        has_subscription=bool(org.stripe_subscription_id or org.billing_subscription_id),
        billing_enabled=settings.billing_enabled,
        billing_provider=settings.active_billing_provider or None,
        limits=limits_for(org),
        usage=usage_for(db, org.id),
        plans=[
            PlanInfo(
                key=p.key,
                name=p.name,
                price_usd=p.price_usd,
                channels=None if p.channels >= 10**9 else p.channels,
                skus=None if p.skus >= 10**9 else p.skus,
            )
            for p in PLANS.values()
        ],
    )


@router.post("/billing/checkout", response_model=UrlResponse)
def checkout(db: DB, ctx: Ctx, body: CheckoutRequest) -> UrlResponse:
    ctx.require("admin")
    org = _org(db, ctx)
    provider = providers.active()
    url = provider.checkout_url(db, org, body.plan, ctx.email)
    audit.record(
        db,
        ctx,
        action="billing.checkout_started",
        entity="organization",
        entity_id=org.id,
        after={"plan": body.plan, "provider": provider.name},
    )
    db.commit()
    return UrlResponse(url=url)


@router.post("/billing/portal", response_model=UrlResponse)
def portal(db: DB, ctx: Ctx) -> UrlResponse:
    ctx.require("admin")
    org = _org(db, ctx)
    if org.billing_provider is None and org.stripe_subscription_id:
        return UrlResponse(url=stripe_service.create_portal(db, org, ctx.email))
    provider = providers.for_org(org.billing_provider, org.stripe_customer_id is not None)
    return UrlResponse(url=provider.portal_url(db, org))


class WebhookAck(BaseModel):
    received: bool = True
    result: str


@router.post("/webhooks/stripe", response_model=WebhookAck)
async def stripe_webhook(
    request: Request, db: DB, stripe_signature: str | None = Header(None, alias="Stripe-Signature")
) -> WebhookAck:
    payload = await request.body()
    event = stripe_service.parse_event(payload, stripe_signature)
    return WebhookAck(result=stripe_service.handle_event(db, event))


@router.post("/webhooks/lemonsqueezy", response_model=WebhookAck)
async def lemonsqueezy_webhook(request: Request, db: DB) -> WebhookAck:
    """Signed with X-Signature (HMAC of the raw body); org comes from checkout custom data."""
    payload = await request.body()
    upd = providers.get("lemonsqueezy").parse_webhook(payload, request.headers)
    return WebhookAck(result=events.apply(db, "lemonsqueezy", upd))


@router.post("/webhooks/paddle", response_model=WebhookAck)
async def paddle_webhook(request: Request, db: DB) -> WebhookAck:
    """Signed with Paddle-Signature (ts + HMAC); org comes from transaction custom_data."""
    payload = await request.body()
    upd = providers.get("paddle").parse_webhook(payload, request.headers)
    return WebhookAck(result=events.apply(db, "paddle", upd))
