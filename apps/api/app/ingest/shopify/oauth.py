"""Shopify OAuth (authorization-code grant) and webhook HMAC verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from urllib.parse import urlencode, urlparse

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


# ---- access tokens -------------------------------------------------------------------------
# New public apps must use *expiring* offline tokens (Shopify, Apr 2026): every token request
# sends expiring=1 and we keep the refresh token. Credentials stored per channel:
# {shop, access_token, refresh_token, expires_at, refresh_expires_at} (epoch seconds);
# legacy rows with only {shop, access_token} keep working until they are re-issued.
TOKEN_EXCHANGE_GRANT = "urn:ietf:params:oauth:grant-type:token-exchange"
ID_TOKEN_TYPE = "urn:ietf:params:oauth:token-type:id_token"
OFFLINE_TOKEN_TYPE = "urn:shopify:params:oauth:token-type:offline-access-token"
REFRESH_MARGIN = 300  # refresh when less than 5 minutes are left


class InvalidSessionToken(ConnectorError):
    """ID token rejected (expired/invalid): answer 401 so App Bridge retries with a fresh one."""


def _token_request(shop: str, data: dict[str, str], client: httpx.Client | None) -> dict:
    c = client or httpx.Client(timeout=20)
    res = c.post(
        f"https://{shop}/admin/oauth/access_token",
        data={
            "client_id": settings.shopify_api_key,
            "client_secret": settings.shopify_api_secret,
            **data,
        },
        headers={"Accept": "application/json"},
    )
    if res.status_code == 400 and data.get("subject_token_type") == ID_TOKEN_TYPE:
        raise InvalidSessionToken("session token rejected by Shopify")
    if res.status_code != 200:
        raise ConnectorError(f"token request failed: {res.status_code} {res.text[:200]}")
    return dict(res.json())


def credentials_from(shop: str, payload: dict, now: float | None = None) -> dict:
    now = now or time.time()
    creds: dict = {"shop": shop, "access_token": payload["access_token"]}
    if payload.get("refresh_token"):
        creds["refresh_token"] = payload["refresh_token"]
    if payload.get("expires_in"):
        creds["expires_at"] = int(now + int(payload["expires_in"]))
    if payload.get("refresh_token_expires_in"):
        creds["refresh_expires_at"] = int(now + int(payload["refresh_token_expires_in"]))
    return creds


def exchange_code(shop: str, code: str, client: httpx.Client | None = None) -> dict:
    """Authorization-code grant (non-embedded install link). Returns stored credentials."""
    payload = _token_request(shop, {"code": code, "expiring": "1"}, client)
    return credentials_from(shop, payload)


def token_exchange(shop: str, id_token: str, client: httpx.Client | None = None) -> dict:
    """Embedded install: App Bridge ID token -> expiring offline token, no redirect."""
    payload = _token_request(
        shop,
        {
            "grant_type": TOKEN_EXCHANGE_GRANT,
            "subject_token": id_token,
            "subject_token_type": ID_TOKEN_TYPE,
            "requested_token_type": OFFLINE_TOKEN_TYPE,
            "expiring": "1",
        },
        client,
    )
    return credentials_from(shop, payload)


def refresh(creds: dict, client: httpx.Client | None = None) -> dict:
    payload = _token_request(
        creds["shop"],
        {"grant_type": "refresh_token", "refresh_token": creds["refresh_token"]},
        client,
    )
    return credentials_from(creds["shop"], payload)


def needs_refresh(creds: dict, now: float | None = None) -> bool:
    exp = creds.get("expires_at")
    return bool(exp and creds.get("refresh_token") and exp - (now or time.time()) < REFRESH_MARGIN)


# ---- App Bridge session (ID) tokens ----------------------------------------------------------
def verify_session_token(token: str) -> dict:
    """Validate an App Bridge ID token (HS256, signed with the app secret). Returns claims plus
    `shop` (from `dest`). Raises InvalidSessionToken."""
    import jwt  # PyJWT

    try:
        claims = jwt.decode(
            token,
            settings.shopify_api_secret,
            algorithms=["HS256"],
            audience=settings.shopify_api_key,
            options={"require": ["exp", "nbf", "iss", "dest", "aud"]},
            leeway=10,
        )
    except jwt.PyJWTError as exc:
        raise InvalidSessionToken(f"invalid session token: {exc}") from exc
    dest = urlparse(claims["dest"]).hostname or ""
    iss = urlparse(claims["iss"]).hostname or ""
    if dest != iss or not valid_shop(dest):
        raise InvalidSessionToken("session token iss/dest mismatch")
    claims["shop"] = dest
    return dict(claims)


# ---- webhook body verification ----
def verify_webhook(body: bytes, header_hmac: str | None) -> bool:
    if not header_hmac:
        return False
    digest = hmac.new(settings.shopify_api_secret.encode(), body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), header_hmac)
