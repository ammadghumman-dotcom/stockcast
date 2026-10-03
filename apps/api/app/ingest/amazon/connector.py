"""Amazon connector.

products  — GET_MERCHANT_LISTINGS_ALL_DATA report (seller-sku, asin, item-name, price), with the
            Catalog Items API filling in names for rows the report leaves blank.
sales     — backfill (since older than ORDERS_API_WINDOW_DAYS) via the
            GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL report; incremental via the
            Orders API (orders + orderItems, token-bucketed).
inventory — FBA Inventory API summaries: fulfillable = on_hand, inbound working/shipped/
            receiving = inbound. Location "FBA <marketplace>".

Credentials JSON: {"refresh_token": ..., "marketplace_id": ..., "seller_id": ...?}
"""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from app import crypto
from app.ingest.amazon.client import AmazonClient
from app.ingest.base import BaseConnector, ConnectorError
from app.ingest.records import InventoryRecord, ProductRecord, SalesRecord
from app.models import Channel
from app.models.enums import ProductType

LISTINGS_REPORT = "GET_MERCHANT_LISTINGS_ALL_DATA"
ORDERS_REPORT = "GET_FLAT_FILE_ALL_ORDERS_DATA_BY_ORDER_DATE_GENERAL"
ORDERS_API_WINDOW_DAYS = 14  # newer than this: Orders API; older: one report instead of N calls
COUNTED_STATUSES = {"Shipped", "Unshipped", "PartiallyShipped", "InvoiceUnconfirmed"}

MARKETPLACE_NAMES = {
    "ATVPDKIKX0DER": "US",
    "A2EUQ1WTGCTBG2": "CA",
    "A1AM78C64UM0Y8": "MX",
    "A1F83G8C2ARO7P": "UK",
    "A1PA6795UKMFR9": "DE",
    "A13V1IB3VIYZZH": "FR",
    "APJ6JRA9NG5V4": "IT",
    "A1RKKUPIHCS9HS": "ES",
    "A1VC38T7YXB528": "JP",
    "A39IBJ37TRP1C6": "AU",
}


def load_credentials(channel: Channel) -> dict:
    if not channel.credentials_encrypted:
        raise ConnectorError("channel has no credentials; connect Amazon first")
    creds = json.loads(crypto.decrypt(channel.credentials_encrypted))
    if not creds.get("refresh_token") or not creds.get("marketplace_id"):
        raise ConnectorError("Amazon credentials need refresh_token and marketplace_id")
    return creds


class AmazonConnector(BaseConnector):
    def __init__(self, channel: Channel, client: AmazonClient | None = None) -> None:
        super().__init__(channel)
        if client is None:
            creds = load_credentials(channel)
            client = AmazonClient(creds["refresh_token"], creds["marketplace_id"])
        self.api = client
        self.location = f"FBA {MARKETPLACE_NAMES.get(client.marketplace_id, client.marketplace_id)}"

    # ---- products ----
    def fetch_products(self) -> Iterable[ProductRecord]:
        rows = parse_tsv(self.api.run_report(LISTINGS_REPORT))
        listings = [r for r in rows if r.get("seller-sku")]
        missing = sorted(
            {r["asin1"] for r in listings if r.get("asin1") and not r.get("item-name")}
        )
        names = self.api.catalog_items(missing) if missing else {}
        for r in listings:
            yield listing_to_record(r, names.get(r.get("asin1") or "", {}))

    # ---- sales ----
    def fetch_sales(self, since: date) -> Iterable[SalesRecord]:
        if since <= date.today() - timedelta(days=ORDERS_API_WINDOW_DAYS):
            yield from self._sales_from_report(since)
        else:
            yield from self._sales_from_orders_api(since)

    def _sales_from_report(self, since: date) -> Iterable[SalesRecord]:
        start = datetime.combine(since, datetime.min.time(), tzinfo=UTC)
        text = self.api.run_report(
            ORDERS_REPORT, dataStartTime=start.isoformat().replace("+00:00", "Z")
        )
        yield from report_rows_to_records(parse_tsv(text))

    def _sales_from_orders_api(self, since: date) -> Iterable[SalesRecord]:
        created_after = datetime.combine(since, datetime.min.time(), tzinfo=UTC).isoformat()
        for order in self.api.iter_orders(created_after.replace("+00:00", "Z")):
            if order.get("OrderStatus") not in COUNTED_STATUSES:
                continue
            day = datetime.fromisoformat(order["PurchaseDate"].replace("Z", "+00:00")).date()
            for item in self.api.order_items(order["AmazonOrderId"]):
                yield from order_item_to_records(day, item)

    # ---- inventory ----
    def fetch_inventory(self) -> Iterable[InventoryRecord]:
        for s in self.api.iter_fba_summaries():
            d = s.get("inventoryDetails") or {}
            inbound = sum(
                int(d.get(k) or 0)
                for k in (
                    "inboundWorkingQuantity",
                    "inboundShippedQuantity",
                    "inboundReceivingQuantity",
                )
            )
            yield InventoryRecord(
                external_id=s.get("asin") or None,
                sku=s.get("sellerSku") or None,
                location=self.location,
                on_hand=Decimal(int(d.get("fulfillableQuantity") or s.get("totalQuantity") or 0)),
                inbound=Decimal(inbound),
            )


# ---- pure helpers (unit-tested without network) ----
def parse_tsv(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")), delimiter="\t")
    return [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]


def _dec(v: str | None) -> Decimal:
    try:
        return Decimal(v) if v else Decimal(0)
    except InvalidOperation:
        return Decimal(0)


def listing_to_record(row: dict[str, str], catalog: dict) -> ProductRecord:
    asin = row.get("asin1") or None
    name = row.get("item-name") or catalog.get("itemName") or asin or row["seller-sku"]
    return ProductRecord(
        sku=row["seller-sku"][:100],
        name=name[:300],
        type=ProductType.finished,
        unit_cost=Decimal(0),  # Amazon never knows your COGS
        category=catalog.get("productType") or None,
        external_id=asin,
        external_sku=row["seller-sku"],
    )


def report_rows_to_records(rows: list[dict[str, str]]) -> Iterable[SalesRecord]:
    """All-orders flat file -> daily (date, sku/asin) records; cancelled/pending rows dropped."""
    agg: dict[tuple, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    keys: dict[tuple, tuple[str | None, str | None]] = {}
    for r in rows:
        if r.get("order-status") not in COUNTED_STATUSES:
            continue
        qty = _dec(r.get("quantity"))
        if qty <= 0:
            continue
        day = datetime.fromisoformat(r["purchase-date"].replace("Z", "+00:00")).date()
        key = (day, r.get("asin") or "", r.get("sku") or "")
        agg[key][0] += qty
        agg[key][1] += _dec(r.get("item-price"))
        keys[key] = (r.get("sku") or None, r.get("asin") or None)
    for key, (units, revenue) in agg.items():
        sku, asin = keys[key]
        yield SalesRecord(date=key[0], sku=sku, external_id=asin, units=units, revenue=revenue)


def order_item_to_records(day: date, item: dict) -> Iterable[SalesRecord]:
    qty = Decimal(int(item.get("QuantityOrdered") or 0))
    if qty <= 0:
        return
    price = _dec((item.get("ItemPrice") or {}).get("Amount"))
    yield SalesRecord(
        date=day,
        sku=item.get("SellerSKU") or None,
        external_id=item.get("ASIN") or None,
        units=qty,
        revenue=price,
    )
