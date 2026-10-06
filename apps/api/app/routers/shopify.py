"""Shopify OAuth install flow + webhook receivers.

Install:  GET /shopify/install?shop=x.myshopify.com  (X-Org-Id header) -> 302 to Shopify
Callback: GET /shopify/callback?code&hmac&shop&state   (from Shopify)   -> 302 to web app
Webhooks: POST /webhooks/shopify/{orders-create|inventory-levels-update|app-uninstalled}
Compliance (GDPR): POST /webhooks/shopify/{customers-data-request|customers-redact|shop-redact}
"""

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app import analytics, crypto
from app.billing.plans import assert_can_add_channel
from app.config import settings
from app.deps import DB, OrgId
from app.ingest import upsert
from app.ingest.base import ConnectorError
from app.ingest.records import InventoryRecord
from app.ingest.shopify import oauth
from app.ingest.shopify.connector import ShopifyConnector, webhook_order_to_records
from app.ingest.tasks import enqueue_sync
from app.models import Channel, ChannelType, ProcessedWebhook
from app.services import shopify_compliance as compliance


class InstallUrl(BaseModel):
    url: str


router = APIRouter(tags=["shopify"])


@router.get("/shopify/install", response_model=InstallUrl)
def install(db: DB, org_id: OrgId, shop: str = Query(...), redirect: bool = False):
    """Returns {"url"} for the web app to navigate to (auth headers can't ride a redirect);
    `redirect=true` answers with a 302 instead."""
    assert_can_add_channel(db, org_id)
    if not oauth.valid_shop(shop):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "shop must be *.myshopify.com")
    if not settings.shopify_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "SHOPIFY_API_KEY not configured")
    url = oauth.install_url(shop, oauth.make_state(str(org_id)))
    return RedirectResponse(url, 302) if redirect else {"url": url}


@router.get("/shopify/callback")
def callback(request: Request, db: DB, shop: str, code: str, state: str):
    params = dict(request.query_params)
    if not oauth.valid_shop(shop) or not oauth.verify_callback_hmac(params):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid callback signature")
    try:
        org_id = uuid.UUID(oauth.read_state(state))
        token = oauth.exchange_code(shop, code)
    except ConnectorError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    channel = db.scalar(
        select(Channel).where(
            Channel.org_id == org_id,
            Channel.type == ChannelType.shopify,
            Channel.external_shop_id == shop,
        )
    )
    if channel is None:
        assert_can_add_channel(db, org_id)
        channel = Channel(
            org_id=org_id,
            name=shop.removesuffix(".myshopify.com"),
            type=ChannelType.shopify,
            external_shop_id=shop,
        )
        db.add(channel)
    channel.credentials_encrypted = crypto.encrypt(
        json.dumps({"shop": shop, "access_token": token})
    )
    channel.is_active = True
    db.commit()
    db.refresh(channel)

    try:
        ShopifyConnector(channel).register_webhooks()
        channel.webhooks_registered = True
        db.commit()
    except ConnectorError:
        pass  # sync still works; webhooks retried on next install

    enqueue_sync(db, channel, trigger="install", full=True)
    analytics.track(db, org_id, "channel_connected", props={"type": "shopify"})
    return RedirectResponse(f"{settings.web_base_url}/onboarding?connected={channel.id}", 302)


# ---- webhooks ----
async def _receive(request: Request, db, topic: str) -> tuple[Channel, dict] | None:
    body = await request.body()
    if not oauth.verify_webhook(body, request.headers.get("X-Shopify-Hmac-Sha256")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad hmac")
    shop = request.headers.get("X-Shopify-Shop-Domain", "")
    webhook_id = request.headers.get("X-Shopify-Webhook-Id", "")
    channel = db.scalar(
        select(Channel).where(Channel.type == ChannelType.shopify, Channel.external_shop_id == shop)
    )
    if channel is None:
        return None  # unknown shop: 200 so Shopify stops retrying
    # dedupe: RETURNING yields a row only when the insert actually happened
    inserted = db.execute(
        pg_insert(ProcessedWebhook)
        .values(
            id=uuid.uuid4(),
            channel_id=channel.id,
            webhook_id=webhook_id or str(uuid.uuid4()),
            topic=topic,
            received_at=datetime.now(UTC),
        )
        .on_conflict_do_nothing(constraint="uq_processed_webhooks")
        .returning(ProcessedWebhook.id)
    ).first()
    if inserted is None:
        return None  # already processed
    return channel, json.loads(body)


@router.post("/webhooks/shopify/orders-create", status_code=200)
async def orders_create(request: Request, db: DB):
    got = await _receive(request, db, "orders/create")
    if got:
        channel, payload = got
        upsert.increment_sales(db, channel.org_id, channel, webhook_order_to_records(payload))
    db.commit()
    return {"ok": True}


# ---- mandatory compliance (GDPR) webhooks + uninstall ----
# Configured once per app (shopify.app.toml `compliance_topics`), signed with the app secret.
# Every handler is idempotent, so Shopify retries need no dedupe table.
async def _compliance(request: Request) -> tuple[str, dict]:
    body = await request.body()
    if not oauth.verify_webhook(body, request.headers.get("X-Shopify-Hmac-Sha256")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad hmac")
    payload = json.loads(body or b"{}")
    shop = request.headers.get("X-Shopify-Shop-Domain") or payload.get("shop_domain") or ""
    return shop, payload


@router.post("/webhooks/shopify/customers-data-request", status_code=200)
async def customers_data_request(request: Request, db: DB):
    shop, payload = await _compliance(request)
    compliance.customers_data_request(db, shop, payload)
    db.commit()
    return {"ok": True}


@router.post("/webhooks/shopify/customers-redact", status_code=200)
async def customers_redact(request: Request, db: DB):
    shop, payload = await _compliance(request)
    compliance.customers_redact(db, shop, payload)
    db.commit()
    return {"ok": True}


@router.post("/webhooks/shopify/shop-redact", status_code=200)
async def shop_redact(request: Request, db: DB):
    shop, _ = await _compliance(request)
    compliance.shop_redact(db, shop)
    db.commit()
    return {"ok": True}


@router.post("/webhooks/shopify/app-uninstalled", status_code=200)
async def app_uninstalled(request: Request, db: DB):
    shop, _ = await _compliance(request)
    compliance.app_uninstalled(db, shop)
    db.commit()
    return {"ok": True}


@router.post("/webhooks/shopify/inventory-levels-update", status_code=200)
async def inventory_levels_update(
    request: Request, db: DB, x_shopify_shop_domain: str | None = Header(None)
):
    got = await _receive(request, db, "inventory_levels/update")
    if got:
        channel, payload = got
        # payload: {inventory_item_id, location_id, available, ...}; we map via variant lookup
        from app.models import ChannelListing, Location

        inv_item = str(payload.get("inventory_item_id", ""))
        listing = db.scalar(
            select(ChannelListing).where(
                ChannelListing.channel_id == channel.id,
                ChannelListing.external_sku == f"inv:{inv_item}",
            )
        )
        loc = db.scalar(
            select(Location).where(
                Location.org_id == channel.org_id,
                Location.name == str(payload.get("location_name") or payload.get("location_id")),
            )
        )
        if listing and payload.get("available") is not None:
            upsert.upsert_inventory(
                db,
                channel.org_id,
                [
                    InventoryRecord(
                        external_id=listing.external_id,
                        location=loc.name if loc else f"shopify:{payload.get('location_id')}",
                        on_hand=Decimal(payload["available"]),
                    )
                ],
                channel,
            )
    db.commit()
    return {"ok": True}
