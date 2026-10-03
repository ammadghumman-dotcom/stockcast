"""eBay connector (Sell Fulfillment + Inventory APIs). One channel = one marketplace.

Credentials JSON: {"refresh_token": ..., "marketplace_id": "EBAY_US", "sandbox": false}
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal

from app import crypto
from app.ingest.base import BaseConnector, ConnectorError
from app.ingest.ebay.client import EbayClient
from app.ingest.records import InventoryRecord, ProductRecord, SalesRecord
from app.models import Channel
from app.models.enums import ProductType


def load_credentials(channel: Channel) -> dict:
    if not channel.credentials_encrypted:
        raise ConnectorError("channel has no credentials; connect eBay first")
    creds = json.loads(crypto.decrypt(channel.credentials_encrypted))
    if not creds.get("refresh_token"):
        raise ConnectorError("eBay credentials need refresh_token")
    creds.setdefault("marketplace_id", "EBAY_US")
    return creds


class EbayConnector(BaseConnector):
    def __init__(self, channel: Channel, client: EbayClient | None = None) -> None:
        super().__init__(channel)
        if client is None:
            creds = load_credentials(channel)
            client = EbayClient(
                creds["refresh_token"], creds["marketplace_id"], sandbox=bool(creds.get("sandbox"))
            )
        self.api = client
        self.location = f"eBay {client.marketplace_id.removeprefix('EBAY_')}"

    def _inventory_items(self) -> list[dict]:
        return list(
            self.api.paginate(
                "inventory", "/sell/inventory/v1/inventory_item", "inventoryItems", {}
            )
        )

    def fetch_products(self) -> Iterable[ProductRecord]:
        for item in self._inventory_items():
            yield inventory_item_to_product(item)

    def fetch_sales(self, since: date) -> Iterable[SalesRecord]:
        start = datetime.combine(since, datetime.min.time(), tzinfo=UTC)
        flt = f"creationdate:[{start.isoformat().replace('+00:00', 'Z')}..]"
        for order in self.api.paginate(
            "fulfillment", "/sell/fulfillment/v1/order", "orders", {"filter": flt}
        ):
            yield from order_to_records(order)

    def fetch_inventory(self) -> Iterable[InventoryRecord]:
        for item in self._inventory_items():
            qty = ((item.get("availability") or {}).get("shipToLocationAvailability") or {}).get(
                "quantity"
            )
            yield InventoryRecord(
                sku=item["sku"],
                external_id=item["sku"],
                location=self.location,
                on_hand=Decimal(int(qty or 0)),
            )


# ---- pure helpers ----
def inventory_item_to_product(item: dict) -> ProductRecord:
    product = item.get("product") or {}
    return ProductRecord(
        sku=item["sku"][:100],
        name=(product.get("title") or item["sku"])[:300],
        type=ProductType.finished,
        external_id=item["sku"],  # eBay's stable id for an inventory item IS the seller SKU
        external_sku=item["sku"],
    )


def order_to_records(order: dict) -> Iterable[SalesRecord]:
    if (order.get("cancelStatus") or {}).get("cancelState") == "CANCELED":
        return
    if order.get("orderPaymentStatus") in ("FAILED", "PENDING"):
        return
    day = datetime.fromisoformat(order["creationDate"].replace("Z", "+00:00")).date()
    for li in order.get("lineItems", []):
        qty = Decimal(int(li.get("quantity") or 0))
        if qty <= 0:
            continue
        sku = li.get("sku") or None
        yield SalesRecord(
            date=day,
            sku=sku,
            external_id=sku or li.get("legacyItemId"),
            units=qty,
            revenue=Decimal(str(((li.get("lineItemCost") or {}).get("value")) or "0")),
        )
