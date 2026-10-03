"""Amazon, eBay and WooCommerce connectors against recorded cassettes (tests/cassettes/*.yaml)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.ingest.amazon.connector import AmazonConnector, parse_tsv, report_rows_to_records
from app.ingest.ebay.connector import EbayConnector
from app.ingest.http import TokenBucket
from app.ingest.tasks import enqueue_sync
from app.ingest.woocommerce.connector import WooCommerceConnector
from app.models import ChannelListing, InventoryLevel, Location, Product, SalesDaily

REST = {"match_on": ["method", "host", "path"]}


def _units(recs):
    out: dict[tuple, Decimal] = {}
    for r in recs:
        out[(r.date, r.sku)] = out.get((r.date, r.sku), Decimal(0)) + r.units
    return out


# --------------------------------------------------------------------------- Amazon
@pytest.mark.vcr("amazon_products.yaml", **REST)
def test_amazon_products_report_polling_and_catalog_fill(amazon_channel) -> None:
    conn = AmazonConnector(amazon_channel)
    recs = list(conn.fetch_products())
    assert [r.sku for r in recs] == ["CND-VAN-200", "CND-VAN-400", "OUD-10"]  # junk row dropped
    assert recs[0].external_id == "B0VAN20000" and recs[0].name == "Vanilla Candle 200g"
    # blank item-name filled from the Catalog Items API, incl. product type as category
    assert recs[1].name == "Vanilla Candle 400g (Catalog)" and recs[1].category == "CANDLE"
    assert conn.location == "FBA US"


@pytest.mark.vcr("amazon_orders_report.yaml", **REST)
def test_amazon_backfill_uses_all_orders_report(amazon_channel) -> None:
    since = date.today() - timedelta(days=60)
    recs = list(AmazonConnector(amazon_channel).fetch_sales(since))
    u = _units(recs)
    assert u[(date(2026, 9, 1), "CND-VAN-200")] == 3  # two orders same day aggregated
    assert (date(2026, 9, 2), "OUD-10") not in u  # cancelled + pending dropped
    assert u[(date(2026, 9, 3), "CND-VAN-400")] == 1
    rev = next(r for r in recs if r.sku == "CND-VAN-200").revenue
    assert rev == Decimal("42.00")


@pytest.mark.vcr("amazon_orders_api.yaml", **REST)
def test_amazon_incremental_uses_orders_api(amazon_channel) -> None:
    since = date.today() - timedelta(days=3)
    recs = list(AmazonConnector(amazon_channel).fetch_sales(since))
    u = _units(recs)
    # 222-2 is Canceled -> no orderItems call for it; NextToken page followed
    assert u == {
        (date(2026, 10, 1), "CND-VAN-200"): 2,
        (date(2026, 10, 1), "OUD-10"): 1,
        (date(2026, 10, 2), "CND-VAN-400"): 3,
    }


@pytest.mark.vcr("amazon_inventory.yaml", **REST)
def test_amazon_fba_inventory_on_hand_and_inbound(amazon_channel) -> None:
    recs = list(AmazonConnector(amazon_channel).fetch_inventory())
    assert len(recs) == 3  # two pages
    van = recs[0]
    assert van.sku == "CND-VAN-200" and van.external_id == "B0VAN20000"
    assert van.location == "FBA US" and van.on_hand == 40 and van.inbound == 100


@pytest.mark.vcr("amazon_throttled.yaml", **REST)
def test_amazon_429_is_retried(amazon_channel) -> None:
    recs = list(AmazonConnector(amazon_channel).fetch_inventory())
    assert [r.sku for r in recs] == ["OUD-10"]


def test_amazon_report_rows_helper() -> None:
    rows = parse_tsv(
        "sku\tasin\tpurchase-date\torder-status\tquantity\titem-price\nA\tB1\t2026-01-01T00:00:00Z\tShipped\t2\t10\n"
    )
    recs = list(report_rows_to_records(rows))
    assert recs[0].units == 2 and recs[0].external_id == "B1" and recs[0].date == date(2026, 1, 1)


def test_token_bucket_waits_when_burst_exhausted(monkeypatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("app.ingest.http._sleep", lambda s: slept.append(s))
    b = TokenBucket(rate=2.0, burst=2)
    b.take()
    b.take()
    b.take()  # third call within the same instant must wait ~0.5 s
    assert len(slept) == 1 and 0.4 <= slept[0] <= 0.5


@pytest.mark.vcr("amazon_full_sync.yaml", **REST)
def test_amazon_full_sync_upserts(db, org, amazon_channel) -> None:
    run = enqueue_sync(db, amazon_channel, trigger="manual", full=True)
    assert run.status == "success", run.error
    assert (run.rows_products, run.rows_sales, run.rows_inventory) == (3, 2, 3)
    skus = set(db.scalars(select(Product.sku).where(Product.org_id == org.id)))
    assert skus == {"CND-VAN-200", "CND-VAN-400", "OUD-10"}
    listings = dict(
        db.execute(
            select(ChannelListing.external_id, Product.sku)
            .join(Product, Product.id == ChannelListing.product_id)
            .where(ChannelListing.channel_id == amazon_channel.id)
        ).all()
    )
    assert listings == {
        "B0VAN20000": "CND-VAN-200",
        "B0VAN40000": "CND-VAN-400",
        "B0OUD10000": "OUD-10",
    }
    loc = db.scalar(select(Location).where(Location.org_id == org.id, Location.name == "FBA US"))
    assert loc is not None
    van = db.scalar(select(Product).where(Product.org_id == org.id, Product.sku == "CND-VAN-200"))
    lvl = db.scalar(
        select(InventoryLevel).where(
            InventoryLevel.product_id == van.id, InventoryLevel.location_id == loc.id
        )
    )
    assert lvl.on_hand == 40 and lvl.inbound == 100
    total = db.scalar(
        select(func.sum(SalesDaily.units)).where(SalesDaily.channel_id == amazon_channel.id)
    )
    assert total == 4
    # re-running the same sync converges (upserts), no duplicates
    run2 = enqueue_sync(db, amazon_channel, trigger="manual", full=True)
    assert run2.status == "success"
    assert db.scalar(select(func.count()).select_from(Product).where(Product.org_id == org.id)) == 3


# --------------------------------------------------------------------------- eBay
@pytest.mark.vcr("ebay_products.yaml", **REST)
def test_ebay_products_paginate_inventory_items(ebay_channel) -> None:
    conn = EbayConnector(ebay_channel)
    recs = list(conn.fetch_products())
    assert [r.sku for r in recs] == ["CND-VAN-200", "OUD-10", "SET-DISC"]
    assert recs[0].name == "Vanilla Soy Candle 200g" and recs[0].external_id == "CND-VAN-200"
    assert conn.location == "eBay US"


@pytest.mark.vcr("ebay_orders.yaml", **REST)
def test_ebay_orders_skip_cancelled_and_unpaid(ebay_channel) -> None:
    recs = list(EbayConnector(ebay_channel).fetch_sales(date(2026, 9, 1)))
    assert _units(recs) == {
        (date(2026, 9, 1), "CND-VAN-200"): 2,
        (date(2026, 9, 1), "OUD-10"): 1,
    }
    assert recs[0].revenue == Decimal("28.00")


@pytest.mark.vcr("ebay_inventory.yaml", **REST)
def test_ebay_inventory_quantities(ebay_channel) -> None:
    recs = list(EbayConnector(ebay_channel).fetch_inventory())
    assert {r.sku: r.on_hand for r in recs} == {"CND-VAN-200": 15, "OUD-10": 4, "SET-DISC": 0}
    assert recs[0].location == "eBay US"


@pytest.mark.vcr("ebay_full_sync.yaml", **REST)
def test_ebay_full_sync_upserts(db, org, ebay_channel) -> None:
    run = enqueue_sync(db, ebay_channel, trigger="manual", full=True)
    assert run.status == "success", run.error
    assert (run.rows_products, run.rows_sales, run.rows_inventory) == (3, 2, 3)


# --------------------------------------------------------------------------- WooCommerce
@pytest.mark.vcr("woo_products.yaml", **REST)
def test_woo_products_expand_variations(woo_channel) -> None:
    recs = list(WooCommerceConnector(woo_channel).fetch_products())
    assert [(r.sku, r.name) for r in recs] == [
        ("CND-VAN-200", "Vanilla Candle - 200g"),
        ("WOO-12", "Vanilla Candle - 400g"),  # no SKU -> synthetic, external id = variation id
        ("OUD-10", "Oud Oil 10ml"),
    ]
    assert recs[0].category == "Candles" and recs[0].external_id == "11"


@pytest.mark.vcr("woo_orders.yaml", **REST)
def test_woo_orders_follow_total_pages(woo_channel) -> None:
    recs = list(WooCommerceConnector(woo_channel).fetch_sales(date(2026, 9, 1)))
    assert [(r.date, r.external_id, r.units) for r in recs] == [
        (date(2026, 9, 1), "11", 2),
        (date(2026, 9, 1), "20", 1),
        (date(2026, 9, 2), "12", 1),
    ]


@pytest.mark.vcr("woo_inventory.yaml", **REST)
def test_woo_inventory_only_managed_stock(woo_channel) -> None:
    recs = list(WooCommerceConnector(woo_channel).fetch_inventory())
    assert {r.external_id: r.on_hand for r in recs} == {"11": 25, "12": 3, "20": 7}


@pytest.mark.vcr("woo_full_sync.yaml", **REST)
def test_woo_full_sync_upserts(db, org, woo_channel) -> None:
    run = enqueue_sync(db, woo_channel, trigger="manual", full=True)
    assert run.status == "success", run.error
    assert (run.rows_products, run.rows_sales, run.rows_inventory) == (3, 3, 3)
