"""OAuth install/callback and webhook endpoints (HTTP layer, no network)."""

import base64
import hashlib
import hmac
import json
from datetime import date
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.config import settings
from app.ingest.base import ConnectorError
from app.ingest.shopify import oauth
from app.models import Channel, ChannelListing, Product, SalesDaily

SHOP = "demo-candle.myshopify.com"


def test_install_redirects_to_shopify(client, headers) -> None:
    r = client.get(
        "/shopify/install",
        params={"shop": SHOP, "redirect": "true"},
        headers=headers,
        follow_redirects=False,
    )
    assert r.status_code == 302
    j = client.get("/shopify/install", params={"shop": SHOP}, headers=headers)
    assert j.status_code == 200 and j.json()["url"].startswith(f"https://{SHOP}/admin/oauth")
    u = urlparse(r.headers["location"])
    assert u.netloc == SHOP and u.path == "/admin/oauth/authorize"
    q = parse_qs(u.query)
    assert q["client_id"] == ["test-key"]
    assert "read_orders" in q["scope"][0]
    assert q["redirect_uri"] == [f"{settings.app_base_url}/shopify/callback"]
    assert oauth.read_state(q["state"][0]) == headers["X-Org-Id"]


def test_install_rejects_bad_shop(client, headers) -> None:
    r = client.get("/shopify/install", params={"shop": "evil.com"}, headers=headers)
    assert r.status_code == 422


def test_state_tamper_detected() -> None:
    s = oauth.make_state("abc")
    raw, sig = s.rsplit(".", 1)
    with pytest.raises(ConnectorError, match="signature"):
        oauth.read_state(raw + ".deadbeef")


def _signed_callback_params(org_id: str) -> dict:
    params = {"shop": SHOP, "code": "authcode", "state": oauth.make_state(org_id), "timestamp": "1"}
    msg = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    params["hmac"] = hmac.new(b"test-secret", msg.encode(), hashlib.sha256).hexdigest()
    return params


def test_callback_creates_channel_and_stores_encrypted_token(
    client, db, org, headers, monkeypatch
) -> None:
    monkeypatch.setattr(oauth, "exchange_code", lambda shop, code: "shpat_live_token")
    monkeypatch.setattr(
        "app.routers.shopify.ShopifyConnector.register_webhooks", lambda self: ["gid://w/1"]
    )
    # the post-install full sync would hit the network; stub it
    monkeypatch.setattr("app.routers.shopify.enqueue_sync", lambda *a, **k: None)

    r = client.get(
        "/shopify/callback", params=_signed_callback_params(str(org.id)), follow_redirects=False
    )
    assert r.status_code == 302, r.text
    assert r.headers["location"].startswith(f"{settings.web_base_url}/onboarding?connected=")

    ch = db.scalar(select(Channel).where(Channel.external_shop_id == SHOP))
    assert ch is not None and ch.org_id == org.id and ch.webhooks_registered
    assert "shpat_live_token" not in (ch.credentials_encrypted or "")
    from app import crypto

    assert (
        json.loads(crypto.decrypt(ch.credentials_encrypted))["access_token"] == "shpat_live_token"
    )
    # API never leaks credentials
    body = client.get(f"/channels/{ch.id}", headers=headers).json()
    assert body["is_connected"] is True and "credentials" not in json.dumps(body)


def test_callback_rejects_bad_hmac(client, org) -> None:
    params = _signed_callback_params(str(org.id))
    params["hmac"] = "0" * 64
    assert client.get("/shopify/callback", params=params).status_code == 400


def _webhook_headers(body: bytes, webhook_id: str) -> dict:
    digest = hmac.new(b"test-secret", body, hashlib.sha256).digest()
    return {
        "X-Shopify-Hmac-Sha256": base64.b64encode(digest).decode(),
        "X-Shopify-Shop-Domain": SHOP,
        "X-Shopify-Webhook-Id": webhook_id,
        "X-Shopify-Topic": "orders/create",
        "Content-Type": "application/json",
    }


def test_orders_webhook_increments_and_dedupes(client, db, org, shopify_channel) -> None:
    p = Product(org_id=org.id, sku="CND-VAN-200", name="Vanilla", type="finished")
    db.add(p)
    db.flush()
    db.add(
        ChannelListing(
            org_id=org.id, product_id=p.id, channel_id=shopify_channel.id, external_id="101"
        )
    )
    db.flush()
    payload = {
        "id": 9,
        "created_at": "2026-09-20T10:00:00+00:00",
        "line_items": [{"variant_id": 101, "quantity": 2, "price": "14.00"}],
    }
    body = json.dumps(payload).encode()

    r = client.post(
        "/webhooks/shopify/orders-create", content=body, headers=_webhook_headers(body, "wh-1")
    )
    assert r.status_code == 200
    r = client.post(
        "/webhooks/shopify/orders-create", content=body, headers=_webhook_headers(body, "wh-1")
    )  # redelivery
    assert r.status_code == 200
    r = client.post(
        "/webhooks/shopify/orders-create", content=body, headers=_webhook_headers(body, "wh-2")
    )  # a second real order
    assert r.status_code == 200

    row = db.scalar(select(SalesDaily).where(SalesDaily.product_id == p.id))
    assert row.date == date(2026, 9, 20) and row.units == 4 and row.revenue == Decimal("56.00")


def test_webhook_bad_signature_401(client) -> None:
    body = b"{}"
    h = _webhook_headers(body, "x")
    h["X-Shopify-Hmac-Sha256"] = "nope"
    assert (
        client.post("/webhooks/shopify/orders-create", content=body, headers=h).status_code == 401
    )
