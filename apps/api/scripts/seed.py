"""Seed a demo organization: 20 finished SKUs, 3 raw materials, 1 BOM, 365 days of sales.

Usage:  uv run python -m scripts.seed   (idempotent: re-running resets the demo org)
"""

from __future__ import annotations

import math
import random
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    BomLine,
    Channel,
    ChannelListing,
    ChannelType,
    InventoryLevel,
    Location,
    Organization,
    Product,
    ProductCategory,
    ProductType,
    Promotion,
    PromotionScope,
    PromotionType,
    Region,
    SalesDaily,
    Supplier,
    SupplierProduct,
    User,
)

DEMO_ORG_ID = uuid.UUID("00000000-0000-0000-0000-00000000d3a0")
DEMO_SLUG = "demo-candle-co"

CATEGORIES = ["Candles", "Perfume Oils", "Eau de Parfum", "Gift Sets"]

# (sku, name, category, unit_cost, base_daily_units)
FINISHED_SKUS: list[tuple[str, str, str, str, float]] = [
    ("CND-VAN-200", "Vanilla Candle 200g", "Candles", "4.20", 6.0),
    ("CND-LAV-200", "Lavender Candle 200g", "Candles", "4.20", 5.0),
    ("CND-OUD-200", "Oud Candle 200g", "Candles", "5.10", 3.5),
    ("CND-CIT-200", "Citrus Candle 200g", "Candles", "4.00", 4.0),
    ("CND-ROS-200", "Rose Candle 200g", "Candles", "4.30", 3.0),
    ("CND-VAN-400", "Vanilla Candle 400g", "Candles", "7.50", 2.5),
    ("CND-LAV-400", "Lavender Candle 400g", "Candles", "7.50", 2.0),
    ("CND-OUD-400", "Oud Candle 400g", "Candles", "9.00", 1.5),
    ("OIL-MUSK-10", "White Musk Oil 10ml", "Perfume Oils", "2.80", 7.0),
    ("OIL-OUD-10", "Oud Oil 10ml", "Perfume Oils", "4.50", 5.5),
    ("OIL-AMB-10", "Amber Oil 10ml", "Perfume Oils", "3.10", 4.5),
    ("OIL-ROSE-10", "Rose Oil 10ml", "Perfume Oils", "3.40", 3.5),
    ("OIL-SND-10", "Sandalwood Oil 10ml", "Perfume Oils", "3.60", 3.0),
    ("EDP-NOIR-50", "Noir EDP 50ml", "Eau de Parfum", "9.80", 2.5),
    ("EDP-BLNC-50", "Blanc EDP 50ml", "Eau de Parfum", "9.60", 2.0),
    ("EDP-OUD-50", "Oud Royale EDP 50ml", "Eau de Parfum", "12.40", 1.5),
    ("EDP-NOIR-100", "Noir EDP 100ml", "Eau de Parfum", "15.50", 1.0),
    ("GFT-CND-3", "Candle Trio Gift Set", "Gift Sets", "13.00", 1.2),
    ("GFT-OIL-3", "Oil Trio Gift Set", "Gift Sets", "9.50", 1.5),
    ("GFT-DISC", "Discovery Set", "Gift Sets", "6.80", 2.0),
]

RAW_MATERIALS: list[tuple[str, str, str, str]] = [
    ("RM-WAX-SOY", "Soy Wax", "g", "0.0045"),
    ("RM-JAR-200", "Glass Jar 200g", "unit", "0.65"),
    ("RM-WICK-CT", "Cotton Wick", "unit", "0.08"),
]

# BOM: 1 x CND-VAN-200 = 200 g wax + 1 jar + 1 wick
BOM_PARENT = "CND-VAN-200"
BOM_LINES = [("RM-WAX-SOY", "200"), ("RM-JAR-200", "1"), ("RM-WICK-CT", "1")]

# Category x holiday uplift multipliers used to shape synthetic sales
# order: Candles, Gift Sets, Eau de Parfum, Perfume Oils
_UPLIFT_CATS = ("Candles", "Gift Sets", "Eau de Parfum", "Perfume Oils")
HOLIDAY_UPLIFT = {
    name: dict(zip(_UPLIFT_CATS, vals, strict=True))
    for name, vals in {
        "Christmas": (2.4, 3.0, 1.8, 1.4),
        "Black Friday": (1.8, 2.2, 1.9, 1.6),
        "Valentine's Day": (1.6, 2.0, 1.7, 1.3),
        "Mother's Day": (1.7, 2.1, 1.6, 1.2),
    }.items()
}


def _holidays(year: int) -> list[tuple[str, date, date]]:
    return [
        ("Valentine's Day", date(year, 2, 1), date(year, 2, 14)),
        ("Mother's Day", date(year, 4, 28), date(year, 5, 12)),
        ("Black Friday", date(year, 11, 20), date(year, 12, 2)),
        ("Christmas", date(year, 11, 25), date(year, 12, 24)),
    ]


def _uplift_for(day: date, category: str) -> float:
    for name, start, end in _holidays(day.year):
        if start <= day <= end:
            peak = HOLIDAY_UPLIFT[name].get(category, 1.0)
            # ramp up to the peak over the window
            progress = (day - start).days / max((end - start).days, 1)
            return 1.0 + (peak - 1.0) * (0.4 + 0.6 * progress)
    return 1.0


def reset_demo_org(db: Session) -> Organization:
    existing = db.scalar(select(Organization).where(Organization.id == DEMO_ORG_ID))
    if existing:
        db.execute(delete(Organization).where(Organization.id == DEMO_ORG_ID))  # cascades
        db.commit()
    org = Organization(
        id=DEMO_ORG_ID,
        name="Demo Candle Co",
        slug=DEMO_SLUG,
        plan="scale",  # demo org: no limits, no trial countdown
        plan_status="active",
    )
    db.add(org)
    db.commit()
    return org


def seed(db: Session, *, days: int = 365, today: date | None = None, seed_value: int = 42) -> None:
    rng = random.Random(seed_value)
    today = today or date.today()
    org = reset_demo_org(db)
    oid = org.id

    db.add(User(org_id=oid, email="owner@demo-candle.co", name="Demo Owner", role="owner"))

    regions = {
        code: Region(org_id=oid, code=code, name=name, currency=cur)
        for code, name, cur in [("US", "United States", "USD"), ("AE", "UAE", "AED")]
    }
    db.add_all(regions.values())
    db.flush()

    main_wh = Location(org_id=oid, name="Main Warehouse", kind="warehouse", is_default=True)
    fba = Location(org_id=oid, name="Amazon FBA US", kind="3pl")
    db.add_all([main_wh, fba])

    shopify = Channel(
        org_id=oid, name="Shopify Store", type=ChannelType.shopify, region_id=regions["US"].id
    )
    amazon = Channel(
        org_id=oid, name="Amazon US", type=ChannelType.amazon, region_id=regions["US"].id
    )
    db.add_all([shopify, amazon])

    cats = {n: ProductCategory(org_id=oid, name=n) for n in CATEGORIES}
    db.add_all(cats.values())
    db.flush()

    products: dict[str, Product] = {}
    base_rate: dict[str, float] = {}
    for sku, name, cat, cost, rate in FINISHED_SKUS:
        p = Product(
            org_id=oid,
            sku=sku,
            name=name,
            type=ProductType.finished,
            unit_cost=Decimal(cost),
            category_id=cats[cat].id,
        )
        products[sku] = p
        base_rate[sku] = rate
    for sku, name, unit, cost in RAW_MATERIALS:
        products[sku] = Product(
            org_id=oid,
            sku=sku,
            name=name,
            type=ProductType.raw_material,
            unit=unit,
            unit_cost=Decimal(cost),
        )
    db.add_all(products.values())
    db.flush()

    for comp_sku, qty in BOM_LINES:
        db.add(
            BomLine(
                org_id=oid,
                parent_product_id=products[BOM_PARENT].id,
                component_product_id=products[comp_sku].id,
                qty_per_unit=Decimal(qty),
            )
        )

    wax_co = Supplier(org_id=oid, name="Pacific Wax Co", lead_time_days=21, moq=25_000)
    glass_co = Supplier(org_id=oid, name="ClearGlass Ltd", lead_time_days=30, moq=500)
    db.add_all([wax_co, glass_co])
    db.flush()
    db.add_all(
        [
            SupplierProduct(
                org_id=oid,
                supplier_id=wax_co.id,
                product_id=products["RM-WAX-SOY"].id,
                price=Decimal("0.0040"),
                pack_size=25_000,
            ),
            SupplierProduct(
                org_id=oid,
                supplier_id=glass_co.id,
                product_id=products["RM-JAR-200"].id,
                price=Decimal("0.60"),
                pack_size=100,
            ),
            SupplierProduct(
                org_id=oid,
                supplier_id=glass_co.id,
                product_id=products["RM-WICK-CT"].id,
                price=Decimal("0.07"),
                pack_size=1000,
            ),
        ]
    )

    # Listings + inventory
    for i, p in enumerate(products.values()):
        if p.type == ProductType.finished:
            db.add(
                ChannelListing(
                    org_id=oid, product_id=p.id, channel_id=shopify.id, external_id=f"shp-{i}"
                )
            )
            db.add(
                ChannelListing(
                    org_id=oid, product_id=p.id, channel_id=amazon.id, external_id=f"B0{i:08d}"
                )
            )
            db.add(
                InventoryLevel(
                    org_id=oid,
                    product_id=p.id,
                    location_id=main_wh.id,
                    on_hand=Decimal(rng.randint(40, 400)),
                    as_of=datetime.now(UTC),
                )
            )
            db.add(
                InventoryLevel(
                    org_id=oid,
                    product_id=p.id,
                    location_id=fba.id,
                    on_hand=Decimal(rng.randint(20, 200)),
                    inbound=Decimal(rng.choice([0, 0, 100, 200])),
                    as_of=datetime.now(UTC),
                )
            )
        else:
            db.add(
                InventoryLevel(
                    org_id=oid,
                    product_id=p.id,
                    location_id=main_wh.id,
                    on_hand=Decimal(rng.randint(2000, 50_000)),
                    as_of=datetime.now(UTC),
                )
            )

    # Built-in holiday calendar for every region (covers the whole sales history + next year)
    from app.forecast.holidays_seed import seed_region_holidays

    first_year = (today - timedelta(days=days)).year
    for region in regions.values():
        seed_region_holidays(db, oid, region, list(range(first_year, today.year + 2)))

    # One past promotion (20% off candles for 10 days, ~100 days ago) so promo lift is learnable
    promo_start = today - timedelta(days=100)
    promo = Promotion(
        org_id=oid,
        name="Candle Sale 20% off",
        channel_id=shopify.id,
        type=PromotionType.discount,
        start_date=promo_start,
        end_date=promo_start + timedelta(days=9),
        discount_pct=Decimal("20"),
        spend_amount=Decimal("0"),
        scope=PromotionScope.category,
        category_id=cats["Candles"].id,
    )
    db.add(promo)

    # 365 days of synthetic sales with weekly seasonality, trend, holidays, and noise
    cat_of = {sku: cat for sku, _, cat, _, _ in FINISHED_SKUS}
    rows: list[SalesDaily] = []
    start_day = today - timedelta(days=days - 1)
    for d in range(days):
        day = start_day + timedelta(days=d)
        weekday_factor = 1.25 if day.weekday() in (4, 5, 6) else 0.9
        trend = 1.0 + 0.25 * d / days  # +25 % over the year
        for sku, rate in base_rate.items():
            p = products[sku]
            uplift = _uplift_for(day, cat_of[sku])
            if cat_of[sku] == "Candles":
                if promo.start_date <= day <= promo.end_date:
                    uplift *= 1.6
                elif promo.end_date < day <= promo.end_date + timedelta(days=7):
                    uplift *= 0.85
            mu = rate * weekday_factor * trend * uplift
            for channel, share in ((shopify, 0.6), (amazon, 0.4)):
                lam = mu * share
                units = _poisson(rng, lam)
                if units == 0 and rng.random() < 0.85:
                    continue  # sparse days exist in real data
                price = float(p.unit_cost) * 3.2
                rows.append(
                    SalesDaily(
                        org_id=oid,
                        date=day,
                        product_id=p.id,
                        channel_id=channel.id,
                        region_id=regions["US"].id,
                        units=Decimal(units),
                        revenue=Decimal(f"{units * price:.2f}"),
                    )
                )
    db.add_all(rows)
    db.commit()
    print(
        f"Seeded org {org.slug} ({org.id}): {len(products)} products, "
        f"{len(BOM_LINES)} BOM lines, {len(rows)} sales rows over {days} days"
    )


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


if __name__ == "__main__":
    with SessionLocal() as session:
        seed(session)
