"""Shopify connector against recorded cassettes (tests/cassettes/*.yaml)."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.ingest.shopify.connector import ShopifyConnector, webhook_order_to_records
from app.ingest.tasks import enqueue_sync
from app.models import ChannelListing, InventoryLevel, Product, SalesDaily


@pytest.mark.vcr("shopify_products.yaml")
def test_fetch_products_paginates_and_maps_variants(shopify_channel) -> None:
    recs = list(ShopifyConnector(shopify_channel).fetch_products())
    assert [r.external_id for r in recs] == ["101", "102", "201", "301"]
    van = recs[0]
    assert van.sku == "CND-VAN-200" and van.name == "Vanilla Candle - 200g"
    assert van.unit_cost == Decimal("4.20") and van.category == "Candles"
    # variant with no SKU gets a stable synthetic one; Default Title is not appended
    oud = recs[2]
    assert oud.sku == "SHOPIFY-201" and oud.name == "Oud Oil 10ml" and oud.unit_cost == 0


@pytest.mark.vcr("shopify_orders.yaml")
def test_fetch_sales_skips_cancelled_and_test_orders(shopify_channel) -> None:
    recs = list(ShopifyConnector(shopify_channel).fetch_sales(date(2026, 9, 1)))
    # 6 orders: one cancelled (5004) and one test (5006) are dropped -> 5 line items remain
    assert len(recs) == 5
    by_day = {}
    for r in recs:
        by_day.setdefault((r.date, r.external_id), Decimal(0))
        by_day[(r.date, r.external_id)] += r.units
    assert by_day[(date(2026, 9, 1), "101")] == 3
    assert by_day[(date(2026, 9, 3), "301")] == 2


@pytest.mark.vcr("shopify_inventory.yaml")
def test_fetch_inventory_per_location(shopify_channel) -> None:
    recs = list(ShopifyConnector(shopify_channel).fetch_inventory())
    assert len(recs) == 5
    fba = next(r for r in recs if r.location == "FBA US")
    assert fba.external_id == "101" and fba.on_hand == 40 and fba.inbound == 100


@pytest.mark.vcr("shopify_throttled.yaml")
def test_throttled_response_is_retried(shopify_channel, monkeypatch) -> None:
    monkeypatch.setattr("app.ingest.shopify.client.time.sleep", lambda s: None)
    recs = list(ShopifyConnector(shopify_channel).fetch_products())
    assert [r.sku for r in recs] == ["GFT-DISC"]


@pytest.mark.vcr("shopify_full_sync.yaml")
def test_full_sync_populates_tables_and_is_idempotent(db, org, shopify_channel) -> None:
    run = enqueue_sync(db, shopify_channel, trigger="manual", full=True)
    assert run.status == "success", run.error
    assert (run.rows_products, run.rows_sales, run.rows_inventory) == (4, 4, 5)

    assert db.scalar(select(func.count()).select_from(Product).where(Product.org_id == org.id)) == 4
    assert db.scalar(select(func.count()).select_from(ChannelListing)) == 4
    van = db.scalar(select(Product).where(Product.sku == "CND-VAN-200"))
    units_sep1 = db.scalar(
        select(SalesDaily.units).where(
            SalesDaily.product_id == van.id, SalesDaily.date == date(2026, 9, 1)
        )
    )
    assert units_sep1 == 3  # orders 5001 (2) + 5002 (1)
    assert shopify_channel.last_synced_at is not None

    # Re-running the same sync must not double-count (upsert = SET)
    # (cassette is consumed, so replay the aggregate path directly)
    from app.ingest import upsert
    from app.ingest.records import SalesRecord

    upsert.upsert_sales(
        db,
        org.id,
        shopify_channel,
        [SalesRecord(date=date(2026, 9, 1), external_id="101", units=3, revenue="40.60")],
    )
    assert (
        db.scalar(
            select(SalesDaily.units).where(
                SalesDaily.product_id == van.id, SalesDaily.date == date(2026, 9, 1)
            )
        )
        == 3
    )
    assert db.scalar(select(func.count()).select_from(InventoryLevel)) == 5


def test_webhook_order_mapping() -> None:
    payload = {
        "id": 1,
        "created_at": "2026-09-10T12:00:00-04:00",
        "test": False,
        "cancelled_at": None,
        "line_items": [
            {
                "variant_id": 101,
                "quantity": 2,
                "price": "14.00",
                "discount_allocations": [{"amount": "2.80"}],
            },
            {"variant_id": 101, "quantity": 1, "price": "14.00", "discount_allocations": []},
            {"variant_id": None, "quantity": 1, "price": "5.00"},  # custom item, ignored
        ],
    }
    recs = list(webhook_order_to_records(payload))
    assert len(recs) == 1
    assert recs[0].external_id == "101" and recs[0].units == 3
    assert recs[0].revenue == Decimal("39.20")
    assert recs[0].date == date(2026, 9, 10)
