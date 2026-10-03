"""WooCommerce connector (REST v3). Credentials JSON: {"url", "consumer_key", "consumer_secret"}."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from decimal import Decimal

from app import crypto
from app.ingest.base import BaseConnector, ConnectorError
from app.ingest.records import InventoryRecord, ProductRecord, SalesRecord
from app.ingest.woocommerce.client import WooClient
from app.models import Channel
from app.models.enums import ProductType

COUNTED_STATUSES = "completed,processing,on-hold"


def load_credentials(channel: Channel) -> dict:
    if not channel.credentials_encrypted:
        raise ConnectorError("channel has no credentials; add the WooCommerce keys first")
    creds = json.loads(crypto.decrypt(channel.credentials_encrypted))
    for k in ("url", "consumer_key", "consumer_secret"):
        if not creds.get(k):
            raise ConnectorError(f"WooCommerce credentials need {k}")
    return creds


class WooCommerceConnector(BaseConnector):
    def __init__(self, channel: Channel, client: WooClient | None = None) -> None:
        super().__init__(channel)
        if client is None:
            c = load_credentials(channel)
            client = WooClient(c["url"], c["consumer_key"], c["consumer_secret"])
        self.api = client
        self.location = f"WooCommerce {channel.name}"

    def _catalog(self) -> Iterable[tuple[dict, dict | None]]:
        """(product, variation|None) for every sellable unit."""
        for p in self.api.paginate("/products", {"status": "publish"}):
            if p.get("type") == "variable":
                for v in self.api.paginate(f"/products/{p['id']}/variations"):
                    yield p, v
            else:
                yield p, None

    def fetch_products(self) -> Iterable[ProductRecord]:
        for p, v in self._catalog():
            yield woo_to_product(p, v)

    def fetch_sales(self, since: date) -> Iterable[SalesRecord]:
        after = datetime.combine(since, datetime.min.time(), tzinfo=UTC).isoformat()
        for order in self.api.paginate("/orders", {"after": after, "status": COUNTED_STATUSES}):
            yield from order_to_records(order)

    def fetch_inventory(self) -> Iterable[InventoryRecord]:
        for p, v in self._catalog():
            unit = v or p
            if not unit.get("manage_stock"):
                continue
            yield InventoryRecord(
                external_id=str(unit["id"]),
                sku=unit.get("sku") or None,
                location=self.location,
                on_hand=Decimal(int(unit.get("stock_quantity") or 0)),
            )


# ---- pure helpers ----
def woo_to_product(p: dict, v: dict | None) -> ProductRecord:
    unit = v or p
    ext = str(unit["id"])
    sku = (unit.get("sku") or "").strip() or f"WOO-{ext}"
    name = p["name"]
    if v:
        attrs = ", ".join(a.get("option", "") for a in v.get("attributes", []) if a.get("option"))
        name = f"{p['name']} - {attrs}" if attrs else p["name"]
    cats = [c["name"] for c in p.get("categories", []) if c.get("name")]
    return ProductRecord(
        sku=sku[:100],
        name=name[:300],
        type=ProductType.finished,
        category=cats[0] if cats else None,
        external_id=ext,
        external_sku=unit.get("sku") or None,
    )


def order_to_records(order: dict) -> Iterable[SalesRecord]:
    day = datetime.fromisoformat(order["date_created_gmt"]).date()
    for li in order.get("line_items", []):
        qty = Decimal(int(li.get("quantity") or 0))
        if qty <= 0:
            continue
        ext = str(li.get("variation_id") or li.get("product_id") or "")
        if not ext or ext == "0":
            continue
        yield SalesRecord(
            date=day,
            sku=li.get("sku") or None,
            external_id=ext,
            units=qty,
            revenue=Decimal(str(li.get("total") or "0")),
        )
