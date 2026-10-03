"""Shopify OAuth (authorization-code grant) and webhook HMAC verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.ingest.base import ConnectorError

SHOP_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")
STATE_TTL = 600


def valid_shop(shop: str) -> bool:
    return bool(SHOP_RE.match(shop or ""))


# ---- signed state (carries org_id through the redirect without server-side storage) ----
def make_state(org_id: str) -> str:
    payload = json.dumps({"o": org_id, "n": secrets.token_hex(8), "t": int(time.time())})
    raw = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"{raw}.{_sign(raw)}"


def read_state(state: str) -> str:
    try:
        raw, sig = state.rsplit(".", 1)
    except ValueError as exc:
        raise ConnectorError("malformed state") from exc
    if not hmac.compare_digest(sig, _sign(raw)):
        raise ConnectorError("state signature mismatch")
    data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    if time.time() - data["t"] > STATE_TTL:
        raise ConnectorError("state expired; start the install again")
    return data["o"]


def _sign(raw: str) -> str:
    return hmac.new(settings.shopify_api_secret.encode(), raw.encode(), hashlib.sha256).hexdigest()


# ---- install URL + callback verification ----
def install_url(shop: str, state: str) -> str:
    params = {
        "client_id": settings.shopify_api_key,
        "scope": settings.shopify_scopes,
        "redirect_uri": f"{settings.app_base_url}/shopify/callback",
        "state": state,
    }
    return f"https://{shop}/admin/oauth/authorize?{urlencode(params)}"


def verify_callback_hmac(params: dict[str, str]) -> bool:
    """Shopify signs the callback query string (all params except hmac) with the app secret."""
    given = params.get("hmac", "")
    msg = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "hmac")
    digest = hmac.new(
        settings.shopify_api_secret.encode(), msg.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(digest, given)


def exchange_code(shop: str, code: str, client: httpx.Client | None = None) -> str:
    c = client or httpx.Client(timeout=20)
    res = c.post(
        f"https://{shop}/admin/oauth/access_token",
        json={
            "client_id": settings.shopify_api_key,
            "client_secret": settings.shopify_api_secret,
            "code": code,
        },
    )
    if res.status_code != 200:
        raise ConnectorError(f"token exchange failed: {res.status_code} {res.text[:200]}")
    return res.json()["access_token"]


# ---- webhook body verification ----
def verify_webhook(body: bytes, header_hmac: str | None) -> bool:
    if not header_hmac:
        return False
    digest = hmac.new(settings.shopify_api_secret.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), header_hmac)
