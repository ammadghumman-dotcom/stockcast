"""PII minimisation: connectors never ask for or model customer identity."""

from __future__ import annotations

import inspect

from app.ingest import records
from app.ingest.amazon import connector as amazon
from app.ingest.ebay import connector as ebay
from app.ingest.shopify import client as shopify
from app.ingest.woocommerce import connector as woo

FORBIDDEN = ("customer", "email", "phone", "shippingAddress", "billingAddress", "buyer")


def test_shopify_queries_fetch_no_customer_fields() -> None:
    for q in (shopify.PRODUCTS_QUERY, shopify.ORDERS_QUERY, shopify.INVENTORY_QUERY):
        for word in FORBIDDEN:
            assert word not in q, f"Shopify query requests {word}"


def test_normalized_records_have_no_identity_fields() -> None:
    for model in (records.ProductRecord, records.SalesRecord, records.InventoryRecord):
        fields = set(model.model_fields)
        assert not fields & {"customer", "email", "name_on_order", "address", "phone"}, model


def test_connectors_do_not_read_buyer_payloads() -> None:
    """Order parsing touches line items only (the eBay/Amazon/Woo payloads carry buyer blocks)."""
    for mod, fn in (
        (amazon, amazon.order_item_to_records),
        (amazon, amazon.report_rows_to_records),
        (ebay, ebay.order_to_records),
        (woo, woo.order_to_records),
    ):
        src = inspect.getsource(fn)
        for word in ("buyer", "Buyer", "customer", "billing", "shipping", "email"):
            assert word not in src, f"{mod.__name__}.{fn.__name__} reads {word}"
