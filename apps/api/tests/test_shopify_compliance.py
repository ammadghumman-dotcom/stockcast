"""Shopify mandatory compliance webhooks (GDPR) + app/uninstalled."""

import base64
import hashlib
import hmac
import json
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import (
    AuditLog,
    BomLine,
    Channel,
    ChannelListing,
    ChannelType,
    Product,
    ProductType,
    SalesDaily,
)

SHOP = "demo-candle.myshopify.com"


def _post(client, path: str, payload: dict, *, secret: bytes = b"test-secret"):
    body = json.dumps(payload).encode()
    digest = hmac.new(secret, body, hashlib.sha256).digest()
    return client.post(
        f"/webhooks/shopify/{path}",
        content=body,
        headers={
            "X-Shopify-Hmac-Sha256": base64.b64encode(digest).decode(),
            "X-Shopify-Shop-Domain": SHOP,
            "Content-Type": "application/json",
        },
    )


def _product(db, org, sku: str) -> Product:
    p = Product(org_id=org.id, sku=sku, name=sku, type=ProductType.finished)
    db.add(p)
    db.flush()
    return p


def _list(db, org, channel, product, ext: str) -> None:
    db.add(
        ChannelListing(org_id=org.id, channel_id=channel.id, product_id=product.id, external_id=ext)
    )
    db.flush()


@pytest.mark.parametrize(
    "path", ["customers-data-request", "customers-redact", "shop-redact", "app-uninstalled"]
)
def test_compliance_webhooks_reject_bad_hmac(client, path) -> None:
    assert _post(client, path, {"shop_domain": SHOP}, secret=b"wrong").status_code == 401


@pytest.mark.parametrize("path", ["customers-data-request", "customers-redact", "shop-redact"])
def test_unknown_shop_is_acknowledged(client, path) -> None:
    # Shopify must get 200 even for shops we never stored (or already erased)
    assert _post(client, path, {"shop_domain": SHOP}).status_code == 200


def test_customer_requests_are_audited_without_storing_pii(
    client, db, org, shopify_channel
) -> None:
    payload = {
        "shop_domain": SHOP,
        "customer": {"id": 191167, "email": "john@example.com", "phone": "555-625-1199"},
        "orders_requested": [299938, 280263],
    }
    assert _post(client, "customers-data-request", payload).status_code == 200
    payload["orders_to_redact"] = payload.pop("orders_requested")
    assert _post(client, "customers-redact", payload).status_code == 200
    rows = db.scalars(select(AuditLog).where(AuditLog.org_id == org.id).order_by(AuditLog.at)).all()
    assert [r.action for r in rows] == [
        "shopify.customers_data_request",
        "shopify.customers_redact",
    ]
    for r in rows:
        assert r.after["orders"] == 2
        assert "john@example.com" not in json.dumps(r.after)  # no PII copied into the audit log


def test_app_uninstalled_drops_token_keeps_data(client, db, org, shopify_channel) -> None:
    p = _product(db, org, "CANDLE-1")
    _list(db, org, shopify_channel, p, "v1")
    assert _post(client, "app-uninstalled", {"domain": SHOP}).status_code == 200
    db.refresh(shopify_channel)
    assert shopify_channel.is_active is False
    assert shopify_channel.credentials_encrypted is None
    assert db.get(Product, p.id) is not None  # history kept until shop/redact


def test_shop_redact_erases_shop_data_but_keeps_shared_products(
    client, db, org, other_org, shopify_channel
) -> None:
    ebay = Channel(org_id=org.id, name="eBay", type=ChannelType.ebay)
    db.add(ebay)
    db.flush()
    only_shopify = _product(db, org, "ONLY-SHOPIFY")
    shared = _product(db, org, "SHARED")
    in_bom = _product(db, org, "WICK")
    _list(db, org, shopify_channel, only_shopify, "v1")
    _list(db, org, shopify_channel, shared, "v2")
    _list(db, org, ebay, shared, "e2")
    _list(db, org, shopify_channel, in_bom, "v3")
    db.add(
        BomLine(
            org_id=org.id,
            parent_product_id=shared.id,
            component_product_id=in_bom.id,
            qty_per_unit=Decimal(1),
        )
    )
    db.add(
        SalesDaily(
            org_id=org.id,
            date=date(2026, 9, 1),
            product_id=only_shopify.id,
            channel_id=shopify_channel.id,
            units=Decimal(3),
        )
    )
    # another org's product with the same SKU must be untouched
    rival = _product(db, other_org, "ONLY-SHOPIFY")
    db.flush()
    channel_id = shopify_channel.id
    ids = {
        n: p.id
        for n, p in [("only", only_shopify), ("shared", shared), ("bom", in_bom), ("rival", rival)]
    }

    assert _post(client, "shop-redact", {"shop_id": 1, "shop_domain": SHOP}).status_code == 200
    db.expire_all()

    assert db.get(Channel, channel_id) is None
    assert db.get(Product, ids["only"]) is None
    assert db.get(Product, ids["shared"]) is not None  # still listed on eBay
    assert db.get(Product, ids["bom"]) is not None  # used in a BOM
    assert db.get(Product, ids["rival"]) is not None
    sales_left = (
        select(func.count()).select_from(SalesDaily).where(SalesDaily.channel_id == channel_id)
    )
    assert db.scalar(sales_left) == 0
    audit_row = db.scalar(select(AuditLog).where(AuditLog.action == "shopify.shop_redact"))
    assert audit_row is not None and audit_row.after["products"] == 1

    # idempotent: a retry finds nothing left to erase
    assert _post(client, "shop-redact", {"shop_domain": SHOP}).status_code == 200
