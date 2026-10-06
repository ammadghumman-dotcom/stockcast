"""OAuth connect flows for Amazon (LWA / SP-API) and eBay.

  GET /amazon/install?channel_id=   -> 302 to Seller Central consent (needs AMAZON_APP_ID)
  GET /amazon/callback?spapi_oauth_code&state&selling_partner_id   (from Amazon)
  GET /ebay/install?channel_id=     -> 302 to eBay consent (needs EBAY_CLIENT_ID + EBAY_RU_NAME)
  GET /ebay/callback?code&state     (from eBay)

The channel row (type amazon|ebay, marketplace in external_shop_id) is created first via
POST /channels; the callback stores the refresh token encrypted and enqueues a full sync.
WooCommerce needs no OAuth: POST /channels with {url, consumer_key, consumer_secret}.
"""

from __future__ import annotations

import base64
import json
import uuid
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app import analytics, crypto
from app.config import settings
from app.deps import DB, Ctx
from app.ingest.amazon.client import LWA_TOKEN_URL
from app.ingest.base import ConnectorError
from app.ingest.ebay.client import API_BASE as EBAY_API
from app.ingest.ebay.client import SCOPES as EBAY_SCOPES
from app.ingest.ebay.client import TOKEN_PATH
from app.ingest.oauth_state import make_state, read_state
from app.ingest.tasks import enqueue_sync
from app.models import Channel, ChannelType
from app.services import crud

router = APIRouter(tags=["connect"])

AMAZON_CONSENT = {
    "na": "https://sellercentral.amazon.com/apps/authorize/consent",
    "eu": "https://sellercentral-europe.amazon.com/apps/authorize/consent",
    "fe": "https://sellercentral-japan.amazon.com/apps/authorize/consent",
}
EBAY_CONSENT = "https://auth.ebay.com/oauth2/authorize"


def _http_client() -> httpx.Client:
    return httpx.Client(timeout=20)


def _channel(db, ctx: Ctx, channel_id: uuid.UUID, ctype: ChannelType) -> Channel:
    ch = crud.get_scoped(db, Channel, ctx.org_id, channel_id)
    if ch.type != ctype:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"channel is not {ctype.value}")
    return ch


def _finish(db, state: str, ctype: ChannelType) -> tuple[Channel, dict]:
    try:
        data = read_state(state)
    except ConnectorError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    ch = db.get(Channel, uuid.UUID(data["c"]))
    if ch is None or str(ch.org_id) != data["o"] or ch.type != ctype:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "channel mismatch")
    return ch, data


def _store_and_sync(db, ch: Channel, creds: dict) -> RedirectResponse:
    ch.credentials_encrypted = crypto.encrypt(json.dumps(creds))
    ch.is_active = True
    db.commit()
    enqueue_sync(db, ch, trigger="install", full=True)
    analytics.track(db, ch.org_id, "channel_connected", props={"type": ch.type.value})
    return RedirectResponse(f"{settings.web_base_url}/onboarding?connected={ch.id}", 302)


# --------------------------------------------------------------------------- Amazon
class UrlResponse(BaseModel):
    url: str


def _go(url: str, redirect: bool):
    return RedirectResponse(url, 302) if redirect else UrlResponse(url=url)


@router.get("/amazon/install", response_model=UrlResponse)
def amazon_install(db: DB, ctx: Ctx, channel_id: uuid.UUID = Query(...), redirect: bool = False):
    ctx.require("admin")
    ch = _channel(db, ctx, channel_id, ChannelType.amazon)
    if not settings.amazon_app_id or not settings.amazon_lwa_client_id:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AMAZON_APP_ID not configured")
    from app.ingest.amazon.client import MARKETPLACE_REGION

    region = MARKETPLACE_REGION.get(ch.external_shop_id or "", "na")
    params = {
        "application_id": settings.amazon_app_id,
        "state": make_state(o=str(ch.org_id), c=str(ch.id)),
        "redirect_uri": f"{settings.app_base_url}/amazon/callback",
    }
    return _go(f"{AMAZON_CONSENT[region]}?{urlencode(params)}", redirect)


@router.get("/amazon/callback")
def amazon_callback(
    db: DB, state: str, spapi_oauth_code: str, selling_partner_id: str | None = None
):
    ch, _ = _finish(db, state, ChannelType.amazon)
    res = _http_client().post(
        LWA_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": spapi_oauth_code,
            "client_id": settings.amazon_lwa_client_id,
            "client_secret": settings.amazon_lwa_client_secret,
            "redirect_uri": f"{settings.app_base_url}/amazon/callback",
        },
    )
    if res.status_code != 200:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"LWA exchange failed: {res.text[:200]}")
    creds = {
        "refresh_token": res.json()["refresh_token"],
        "marketplace_id": ch.external_shop_id,
        "seller_id": selling_partner_id,
    }
    return _store_and_sync(db, ch, creds)


# --------------------------------------------------------------------------- eBay
@router.get("/ebay/install", response_model=UrlResponse)
def ebay_install(db: DB, ctx: Ctx, channel_id: uuid.UUID = Query(...), redirect: bool = False):
    ctx.require("admin")
    ch = _channel(db, ctx, channel_id, ChannelType.ebay)
    if not settings.ebay_client_id or not settings.ebay_ru_name:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "EBAY_CLIENT_ID/RU_NAME not set")
    params = {
        "client_id": settings.ebay_client_id,
        "redirect_uri": settings.ebay_ru_name,
        "response_type": "code",
        "scope": " ".join(EBAY_SCOPES),
        "state": make_state(o=str(ch.org_id), c=str(ch.id)),
    }
    return _go(f"{EBAY_CONSENT}?{urlencode(params)}", redirect)


@router.get("/ebay/callback")
def ebay_callback(db: DB, state: str, code: str):
    ch, _ = _finish(db, state, ChannelType.ebay)
    basic = base64.b64encode(
        f"{settings.ebay_client_id}:{settings.ebay_client_secret}".encode()
    ).decode()
    res = _http_client().post(
        f"{EBAY_API}{TOKEN_PATH}",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.ebay_ru_name,
        },
        headers={"Authorization": f"Basic {basic}"},
    )
    if res.status_code != 200:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"eBay exchange failed: {res.text[:200]}")
    creds = {
        "refresh_token": res.json()["refresh_token"],
        "marketplace_id": ch.external_shop_id or "EBAY_US",
    }
    return _store_and_sync(db, ch, creds)
