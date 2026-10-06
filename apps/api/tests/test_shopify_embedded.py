"""Embedded Shopify app: session tokens, token-exchange install, expiring tokens, Billing API."""

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import jwt
import pytest
from sqlalchemy import select

from app import crypto
from app.billing.plans import LOCKED, effective_plan
from app.ingest.base import ConnectorError
from app.ingest.shopify import connector as shopify_connector
from app.ingest.shopify import oauth
from app.ingest.shopify.client import ShopifyGraphQL
from app.models import AuditLog, Channel, ChannelType, Organization
from app.services import shopify_app

SHOP = "wick-and-wax.myshopify.com"


def session_token(
    shop: str = SHOP, *, aud: str = "test-key", exp_in: int = 60, iss_shop=None
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": f"https://{iss_shop or shop}/admin",
            "dest": f"https://{shop}",
            "aud": aud,
            "sub": "42",
            "exp": now + exp_in,
            "nbf": now - 5,
            "iat": now - 5,
            "jti": "x",
            "sid": "y",
        },
        "test-secret",
        algorithm="HS256",
    )


def bearer(token: str | None = None) -> dict:
    return {"Authorization": f"Bearer {token or session_token()}"}


@pytest.fixture
def no_network(monkeypatch):
    """Install side effects replaced: token exchange, webhook registration, backfill."""
    calls = {"exchange": 0, "sync": 0}

    def fake_exchange(shop, id_token, client=None):
        calls["exchange"] += 1
        return oauth.credentials_from(
            shop,
            {
                "access_token": "shpat_x",
                "refresh_token": "shprt_x",
                "expires_in": 3600,
                "refresh_token_expires_in": 7776000,
            },
        )

    monkeypatch.setattr(oauth, "token_exchange", fake_exchange)
    monkeypatch.setattr(shopify_app.ShopifyConnector, "register_webhooks", lambda self: ["w"])
    monkeypatch.setattr(
        "app.ingest.tasks.enqueue_sync",
        lambda db, ch, trigger, full=False: calls.__setitem__("sync", calls["sync"] + 1),
    )
    return calls


# ---- session tokens ---------------------------------------------------------------------------
def test_verify_session_token() -> None:
    assert oauth.verify_session_token(session_token())["shop"] == SHOP
    for bad in (
        session_token(aud="other-app"),
        session_token(exp_in=-120),
        session_token(iss_shop="evil.myshopify.com"),
        "not-a-jwt",
    ):
        with pytest.raises(oauth.InvalidSessionToken):
            oauth.verify_session_token(bad)


def test_session_token_authenticates_and_provisions_one_workspace(client, db) -> None:
    assert client.get("/products", headers=bearer()).status_code == 200
    assert client.get("/products", headers=bearer()).status_code == 200
    orgs = db.scalars(select(Organization).where(Organization.shopify_shop == SHOP)).all()
    assert len(orgs) == 1 and orgs[0].name == "Wick And Wax" and orgs[0].plan == "trial"


def test_stale_session_token_asks_app_bridge_to_retry(client) -> None:
    r = client.get("/products", headers=bearer(session_token(exp_in=-120)))
    assert r.status_code == 401
    assert r.headers["X-Shopify-Retry-Invalid-Session-Request"] == "1"


def test_session_installs_once(client, db, no_network) -> None:
    r = client.post("/shopify/session", headers=bearer())
    assert r.status_code == 200 and r.json()["installed"] is True and r.json()["shop"] == SHOP
    r2 = client.post("/shopify/session", headers=bearer())
    assert r2.json()["installed"] is False
    assert no_network == {"exchange": 1, "sync": 1}
    ch = db.scalar(select(Channel).where(Channel.external_shop_id == SHOP))
    creds = json.loads(crypto.decrypt(ch.credentials_encrypted))
    assert creds["refresh_token"] == "shprt_x" and creds["expires_at"] > time.time()


def test_shop_connected_earlier_keeps_its_workspace(client, db, org, no_network) -> None:
    db.add(Channel(org_id=org.id, name="w", type=ChannelType.shopify, external_shop_id=SHOP))
    db.flush()
    r = client.post("/shopify/session", headers=bearer())
    assert r.json()["org_id"] == str(org.id)
    assert db.get(Organization, org.id).shopify_shop == SHOP


def test_embedded_routes_need_a_shopify_session(client, headers) -> None:
    assert (
        client.post("/shopify/session", headers={**headers, "Authorization": "x"}).status_code
        == 403
    )
    assert client.get("/shopify/billing", headers=headers).status_code == 403


# ---- expiring offline tokens ------------------------------------------------------------------
def test_code_exchange_requests_expiring_token() -> None:
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update({k: v[0] for k, v in parse_qs(req.content.decode()).items()})
        return httpx.Response(
            200, json={"access_token": "a", "refresh_token": "r", "expires_in": 3600}
        )

    creds = oauth.exchange_code(
        SHOP, "code", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert seen["expiring"] == "1" and seen["code"] == "code"
    assert creds["refresh_token"] == "r" and creds["expires_at"] - time.time() > 3500


def test_token_exchange_maps_rejection_to_invalid_session() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400, json={})))
    with pytest.raises(oauth.InvalidSessionToken):
        oauth.token_exchange(SHOP, "stale", client=client)


def test_fresh_credentials_refreshes_near_expiry(db, org, monkeypatch) -> None:
    old = {
        "shop": SHOP,
        "access_token": "old",
        "refresh_token": "r1",
        "expires_at": int(time.time()) + 60,
    }
    ch = Channel(
        org_id=org.id,
        name="w",
        type=ChannelType.shopify,
        external_shop_id=SHOP,
        credentials_encrypted=crypto.encrypt(json.dumps(old)),
    )
    db.add(ch)
    db.flush()
    monkeypatch.setattr(
        oauth,
        "refresh",
        lambda creds, client=None: oauth.credentials_from(
            SHOP, {"access_token": "new", "refresh_token": "r2", "expires_in": 3600}
        ),
    )
    assert shopify_connector.fresh_credentials(ch)["access_token"] == "new"
    assert json.loads(crypto.decrypt(ch.credentials_encrypted))["refresh_token"] == "r2"
    legacy = {"shop": SHOP, "access_token": "forever"}
    assert not oauth.needs_refresh(legacy)


def test_client_refreshes_once_on_401() -> None:
    tokens = []

    def handler(req: httpx.Request) -> httpx.Response:
        tokens.append(req.headers["X-Shopify-Access-Token"])
        if req.headers["X-Shopify-Access-Token"] == "old":
            return httpx.Response(401, json={})
        return httpx.Response(200, json={"data": {"ok": True}})

    gql = ShopifyGraphQL(
        SHOP,
        "old",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        refresh=lambda: "new",
    )
    assert gql.query("{ ok }") == {"ok": True}
    assert tokens == ["old", "new"]


# ---- Billing API ------------------------------------------------------------------------------
def _install(client, no_network) -> None:
    assert client.post("/shopify/session", headers=bearer()).status_code == 200


def test_billing_lists_plans_with_beta_prices(client, db, no_network) -> None:
    _install(client, no_network)
    body = client.get("/shopify/billing", headers=bearer()).json()
    growth = next(p for p in body["plans"] if p["key"] == "growth")
    assert growth["price_usd"] == 99 and growth["beta_price_usd"] == 50
    assert body["current_plan"] == "trial" and body["beta_discount_months"] == 6


def test_subscribe_builds_beta_test_charge(client, db, no_network, monkeypatch) -> None:
    _install(client, no_network)
    org = db.scalar(select(Organization).where(Organization.shopify_shop == SHOP))
    org.is_beta = True
    db.flush()
    sent = []

    def fake_query(self, query, variables=None):
        if "partnerDevelopment" in query:
            return {"shop": {"plan": {"partnerDevelopment": True}}}
        sent.append(variables)
        return {
            "appSubscriptionCreate": {
                "userErrors": [],
                "appSubscription": {"id": "gid://s/1"},
                "confirmationUrl": "https://admin.shopify.com/charges/1",
            }
        }

    monkeypatch.setattr(ShopifyGraphQL, "query", fake_query)
    r = client.post("/shopify/billing/subscribe", json={"plan": "growth"}, headers=bearer())
    assert r.status_code == 200 and r.json()["confirmation_url"].endswith("/charges/1")
    v = sent[0]
    assert v["name"] == "Stockcast Growth" and v["test"] is True and v["trialDays"] >= 13
    details = v["lineItems"][0]["plan"]["appRecurringPricingDetails"]
    assert details["price"] == {"amount": 99, "currencyCode": "USD"}
    assert details["discount"] == {"value": {"percentage": 0.5}, "durationLimitInIntervals": 6}
    assert (
        v["returnUrl"] == "https://admin.shopify.com/store/wick-and-wax/apps/stockcast?billing=done"
    )
    assert (
        client.post(
            "/shopify/billing/subscribe", json={"plan": "gold"}, headers=bearer()
        ).status_code
        == 422
    )


def _hook(client, payload: dict, secret: bytes = b"test-secret"):
    body = json.dumps(payload).encode()
    sig = base64.b64encode(hmac.new(secret, body, hashlib.sha256).digest()).decode()
    return client.post(
        "/webhooks/shopify/app-subscriptions-update",
        content=body,
        headers={"X-Shopify-Hmac-Sha256": sig, "X-Shopify-Shop-Domain": SHOP},
    )


def test_subscription_webhook_drives_the_plan(client, db, no_network) -> None:
    _install(client, no_network)
    org_id = db.scalar(select(Organization.id).where(Organization.shopify_shop == SHOP))
    sub = {"admin_graphql_api_id": "gid://shopify/AppSubscription/7", "name": "Stockcast Growth"}

    assert _hook(client, {"app_subscription": {**sub, "status": "DECLINED"}}).status_code == 200
    assert db.get(Organization, org_id).plan == "trial"
    _hook(client, {"app_subscription": {**sub, "status": "ACTIVE"}})
    db.expire_all()
    org = db.get(Organization, org_id)
    assert (org.plan, org.plan_status, org.shopify_subscription_id) == (
        "growth",
        "active",
        sub["admin_graphql_api_id"],
    )
    # cancelling some *other* subscription id is ignored; this one cancels
    _hook(
        client,
        {"app_subscription": {**sub, "admin_graphql_api_id": "gid://other", "status": "CANCELLED"}},
    )
    db.expire_all()
    assert db.get(Organization, org_id).plan_status == "active"
    _hook(client, {"app_subscription": {**sub, "status": "CANCELLED"}})
    db.expire_all()
    assert db.get(Organization, org_id).plan_status == "canceled"
    assert (
        db.scalar(select(AuditLog).where(AuditLog.action == "billing.shopify_subscription"))
        is not None
    )
    assert _hook(client, {"app_subscription": sub}, secret=b"wrong").status_code == 401


def test_shopify_workspace_locks_after_trial_without_stripe(db) -> None:
    org = Organization(
        name="x",
        slug="x-shop",
        shopify_shop="x.myshopify.com",
        trial_ends_at=datetime.now(UTC) - timedelta(days=1),
    )
    assert effective_plan(org) is LOCKED


def test_install_surfaces_connector_errors(client, monkeypatch) -> None:
    def boom(shop, id_token, client=None):
        raise ConnectorError("token request failed: 500")

    monkeypatch.setattr(oauth, "token_exchange", boom)
    assert client.post("/shopify/session", headers=bearer()).status_code == 502
