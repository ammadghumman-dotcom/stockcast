"""Shopify connector: products/variants, daily order aggregates, inventory per location."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal

from app import crypto
from app.config import settings
from app.ingest.base import BaseConnector, ConnectorError
from app.ingest.records import InventoryRecord, ProductRecord, SalesRecord
from app.ingest.shopify import oauth
from app.ingest.shopify.client import (
    INVENTORY_QUERY,
    ORDERS_QUERY,
    PRODUCTS_QUERY,
    WEBHOOK_CREATE,
    ShopifyGraphQL,
    gid_to_id,
)
from app.models import Channel
from app.models.enums import ProductType

WEBHOOK_TOPICS = {
    "ORDERS_CREATE": "orders-create",
    "INVENTORY_LEVELS_UPDATE": "inventory-levels-update",
    "APP_UNINSTALLED": "app-uninstalled",
    "APP_SUBSCRIPTIONS_UPDATE": "app-subscriptions-update",
}


def load_credentials(channel: Channel) -> dict:
    if not channel.credentials_encrypted:
        raise ConnectorError("channel has no credentials; complete the Shopify install first")
    return json.loads(crypto.decrypt(channel.credentials_encrypted))


def fresh_credentials(channel: Channel, *, force: bool = False) -> dict:
    """Credentials with a usable access token, refreshing (and re-encrypting onto the channel —
    the caller's session commits it) when an expiring token is close to expiry."""
    creds = load_credentials(channel)
    if force or oauth.needs_refresh(creds):
        if not creds.get("refresh_token"):
            raise ConnectorError("Shopify access expired; open Stockcast from your Shopify admin")
        creds = oauth.refresh(creds)
        channel.credentials_encrypted = crypto.encrypt(json.dumps(creds))
    return creds


class ShopifyConnector(BaseConnector):
    def __init__(self, channel: Channel, client: ShopifyGraphQL | None = None) -> None:
        super().__init__(channel)
        if client is None:
            creds = fresh_credentials(channel)
            can_refresh = bool(creds.get("refresh_token"))
            client = ShopifyGraphQL(
                creds["shop"],
                creds["access_token"],
                refresh=(lambda: fresh_credentials(channel, force=True)["access_token"])
                if can_refresh
                else None,
            )
        self.gql = client

    # ---- products ----
    def fetch_products(self) -> Iterable[ProductRecord]:
        for product in self.gql.paginate(PRODUCTS_QUERY, "products"):
            for edge in product["variants"]["edges"]:
                v = edge["node"]
                yield variant_to_record(product, v)

    # ---- sales ----
    def fetch_sales(self, since: date) -> Iterable[SalesRecord]:
        q = f"created_at:>={since.isoformat()} AND financial_status:paid"
        for order in self.gql.paginate(ORDERS_QUERY, "orders", {"q": q}):
            yield from order_to_records(order)

    # ---- inventory ----
    def fetch_inventory(self) -> Iterable[InventoryRecord]:
        for item in self.gql.paginate(INVENTORY_QUERY, "inventoryItems"):
            variant_id = gid_to_id((item.get("variant") or {}).get("id"))
            for edge in item["inventoryLevels"]["edges"]:
                lvl = edge["node"]
                qty = {q["name"]: q["quantity"] for q in lvl["quantities"]}
                yield InventoryRecord(
                    external_id=variant_id,
                    sku=item.get("sku") or None,
                    location=lvl["location"]["name"],
                    on_hand=Decimal(qty.get("available", 0)),
                    inbound=Decimal(qty.get("incoming", 0)),
                )

    # ---- webhooks ----
    def register_webhooks(self) -> list[str]:
        ids = []
        for topic, path in WEBHOOK_TOPICS.items():
            url = f"{settings.app_base_url}/webhooks/shopify/{path}"
            data = self.gql.query(WEBHOOK_CREATE, {"topic": topic, "url": url})
            payload = data["webhookSubscriptionCreate"]
            errs = payload.get("userErrors") or []
            # "already exists" is fine on re-install
            if errs and not any("taken" in e["message"] for e in errs):
                raise ConnectorError(f"webhook {topic}: {errs[0]['message']}")
            if payload.get("webhookSubscription"):
                ids.append(payload["webhookSubscription"]["id"])
        return ids


# ---- pure mapping helpers (unit-tested without network) ----
def variant_to_record(product: dict, v: dict) -> ProductRecord:
    vid = gid_to_id(v["id"]) or ""
    sku = (v.get("sku") or "").strip() or f"SHOPIFY-{vid}"
    name = (
        product["title"]
        if v.get("title") in (None, "Default Title")
        else (f"{product['title']} - {v['title']}")
    )
    cost = ((v.get("inventoryItem") or {}).get("unitCost") or {}).get("amount")
    return ProductRecord(
        sku=sku,
        name=name[:300],
        type=ProductType.finished,
        unit_cost=Decimal(cost) if cost else Decimal(0),
        category=(product.get("productType") or None),
        external_id=vid,
        external_sku=v.get("sku") or None,
    )


def order_to_records(order: dict) -> Iterable[SalesRecord]:
    if order.get("cancelledAt") or order.get("test"):
        return
    day = datetime.fromisoformat(order["createdAt"].replace("Z", "+00:00")).date()
    for edge in order["lineItems"]["edges"]:
        li = edge["node"]
        variant = li.get("variant") or {}
        vid = gid_to_id(variant.get("id"))
        if not vid:
            continue  # custom/deleted line item
        yield SalesRecord(
            date=day,
            external_id=vid,
            sku=variant.get("sku") or None,
            units=Decimal(li["quantity"]),
            revenue=Decimal(li["discountedTotalSet"]["shopMoney"]["amount"]),
        )


def webhook_order_to_records(payload: dict) -> Iterable[SalesRecord]:
    """REST-shaped orders/create webhook payload -> records."""
    if payload.get("cancelled_at") or payload.get("test"):
        return
    day = datetime.fromisoformat(payload["created_at"]).date()
    agg: dict[str, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for li in payload.get("line_items", []):
        if not li.get("variant_id"):
            continue
        vid = str(li["variant_id"])
        qty = Decimal(li["quantity"])
        price = Decimal(str(li.get("price", "0")))
        discount = sum(Decimal(str(d["amount"])) for d in li.get("discount_allocations", []) or [])
        agg[vid][0] += qty
        agg[vid][1] += qty * price - discount
    for vid, (units, revenue) in agg.items():
        yield SalesRecord(date=day, external_id=vid, units=units, revenue=max(revenue, 0))
