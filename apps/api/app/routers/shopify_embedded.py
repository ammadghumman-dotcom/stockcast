"""Routes for the embedded Shopify app (authenticated by App Bridge session tokens).

POST /shopify/session              bootstrap on every open: workspace + token-exchange install
GET  /shopify/billing              plans, prices (incl. beta) and the current subscription
POST /shopify/billing/subscribe    -> {confirmation_url} for App Bridge to open at _top
POST /webhooks/shopify/app-subscriptions-update   (HMAC) keeps org.plan in sync
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from app.billing.plans import PLANS, UNLIMITED, effective_plan
from app.deps import DB, Ctx
from app.ingest.base import ConnectorError
from app.ingest.shopify import oauth
from app.models import Organization
from app.services import shopify_app

router = APIRouter(tags=["shopify-embedded"])


class SessionOut(BaseModel):
    org_id: str
    org_name: str
    shop: str
    channel_id: str
    installed: bool
    plan: str
    plan_status: str
    trial_ends_at: str | None
    is_beta: bool


class PlanOut(BaseModel):
    key: str
    name: str
    price_usd: int
    beta_price_usd: int
    channels: int | None
    skus: int | None


class BillingOut(BaseModel):
    plans: list[PlanOut]
    current_plan: str
    plan_status: str
    effective_plan: str
    is_beta: bool
    beta_discount_months: int


class SubscribeIn(BaseModel):
    plan: str


class SubscribeOut(BaseModel):
    confirmation_url: str


def _shop_from_ctx(db, ctx) -> tuple[Organization, str]:
    if ctx.mode != "shopify":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "open Stockcast from your Shopify admin")
    org = db.get(Organization, ctx.org_id)
    if org is None or not org.shopify_shop:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no Shopify store for this workspace")
    return org, org.shopify_shop


@router.post("/shopify/session", response_model=SessionOut)
def session(request: Request, db: DB, ctx: Ctx) -> SessionOut:
    org, shop = _shop_from_ctx(db, ctx)
    authorization = request.headers.get("Authorization", "")
    try:
        channel, installed = shopify_app.install(
            db, org, shop, authorization.removeprefix("Bearer ").strip()
        )
    except oauth.InvalidSessionToken as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            str(exc),
            headers={"X-Shopify-Retry-Invalid-Session-Request": "1"},
        ) from exc
    except ConnectorError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return SessionOut(
        org_id=str(org.id),
        org_name=org.name,
        shop=shop,
        channel_id=str(channel.id),
        installed=installed,
        plan=org.plan,
        plan_status=org.plan_status,
        trial_ends_at=org.trial_ends_at.isoformat() if org.trial_ends_at else None,
        is_beta=org.is_beta,
    )


@router.get("/shopify/billing", response_model=BillingOut)
def billing(db: DB, ctx: Ctx) -> BillingOut:
    org, _ = _shop_from_ctx(db, ctx)
    pct = shopify_app.BETA_DISCOUNT_PCT
    return BillingOut(
        plans=[
            PlanOut(
                key=k,
                name=p.name,
                price_usd=p.price_usd,
                beta_price_usd=round(p.price_usd * (1 - pct)),
                channels=None if p.channels >= UNLIMITED else p.channels,
                skus=None if p.skus >= UNLIMITED else p.skus,
            )
            for k, p in PLANS.items()
        ],
        current_plan=org.plan,
        plan_status=org.plan_status,
        effective_plan=effective_plan(org).key,
        is_beta=org.is_beta,
        beta_discount_months=shopify_app.BETA_DISCOUNT_MONTHS,
    )


@router.post("/shopify/billing/subscribe", response_model=SubscribeOut)
def subscribe(db: DB, ctx: Ctx, body: SubscribeIn) -> SubscribeOut:
    org, shop = _shop_from_ctx(db, ctx)
    if body.plan not in PLANS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown plan")
    channel = shopify_app.shop_channel(db, org, shop)
    if channel is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "open the app once to finish installing")
    try:
        url = shopify_app.subscribe(db, org, channel, body.plan)
    except ConnectorError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return SubscribeOut(confirmation_url=url)


@router.post("/webhooks/shopify/app-subscriptions-update", status_code=200)
async def app_subscriptions_update(request: Request, db: DB):
    body = await request.body()
    if not oauth.verify_webhook(body, request.headers.get("X-Shopify-Hmac-Sha256")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad hmac")
    payload = json.loads(body or b"{}")
    shop = request.headers.get("X-Shopify-Shop-Domain", "")
    shopify_app.apply_subscription_update(db, shop, payload.get("app_subscription") or {})
    return {"ok": True}
