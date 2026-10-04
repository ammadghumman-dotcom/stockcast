"""Create a load-test dataset: N orgs x M SKUs with 365 days of sales on one channel each.

    uv run python -m scripts.seed_load --orgs 50 --skus 2000      # ~100k SKUs, ~15M sales rows
    uv run python -m scripts.seed_load --orgs 2 --skus 200 --days 120   # quick local smoke

Writes with COPY-sized batches; prints org ids to loadtest/orgs.txt for k6. Idempotent per
slug (re-running recreates those orgs).
"""

from __future__ import annotations

import argparse
import random
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db import SessionLocal
from app.models import (
    Channel,
    ChannelType,
    InventoryLevel,
    Location,
    Organization,
    PlanningSettings,
    Product,
    ProductType,
    Region,
    SalesDaily,
    Supplier,
)


def seed_org(db, i: int, skus: int, days: int, today: date, rng: random.Random) -> uuid.UUID:
    slug = f"load-{i:03d}"
    old = db.scalar(select(Organization).where(Organization.slug == slug))
    if old:
        db.execute(delete(Organization).where(Organization.id == old.id))
        db.commit()
    org = Organization(name=f"Load Org {i}", slug=slug, plan="scale", plan_status="active")
    db.add(org)
    db.flush()
    region = Region(org_id=org.id, code="US", name="United States", currency="USD")
    loc = Location(org_id=org.id, name="Main", is_default=True)
    db.add_all([region, loc, PlanningSettings(org_id=org.id)])
    db.flush()
    ch = Channel(org_id=org.id, name="Shopify", type=ChannelType.shopify, region_id=region.id)
    sup = Supplier(org_id=org.id, name="Supplier", lead_time_days=14, moq=10)
    db.add_all([ch, sup])
    db.flush()
    products = [
        {
            "id": uuid.uuid4(),
            "org_id": org.id,
            "sku": f"L{i:03d}-{k:05d}",
            "name": f"Product {k}",
            "type": ProductType.finished,
            "unit_cost": Decimal("3.5"),
            "unit": "unit",
            "is_active": True,
        }
        for k in range(skus)
    ]
    for j in range(0, len(products), 2000):
        db.execute(pg_insert(Product).values(products[j : j + 2000]))
    db.execute(
        pg_insert(InventoryLevel).values(
            [
                {
                    "id": uuid.uuid4(),
                    "org_id": org.id,
                    "product_id": p["id"],
                    "location_id": loc.id,
                    "on_hand": Decimal(rng.randint(0, 400)),
                    "inbound": Decimal(0),
                }
                for p in products
            ]
        )
    )
    start = today - timedelta(days=days - 1)
    rows: list[dict] = []
    for p in products:
        rate = rng.choice([0.3, 1.0, 3.0, 8.0, 20.0])  # mix of slow and fast movers
        for d in range(days):
            day = start + timedelta(days=d)
            lam = rate * (1.3 if day.weekday() >= 5 else 1.0) * (1 + 0.4 * (day.month == 12))
            units = rng.random() < 0.9 and _poisson(rng, lam) or 0
            if units == 0:
                continue
            rows.append(
                {
                    "org_id": org.id,
                    "date": day,
                    "product_id": p["id"],
                    "channel_id": ch.id,
                    "region_id": region.id,
                    "units": Decimal(units),
                    "revenue": Decimal(units * 12),
                }
            )
            if len(rows) >= 8000:  # 7 params per row, keep under the 65k bind limit
                db.execute(pg_insert(SalesDaily).values(rows))
                rows = []
    if rows:
        db.execute(pg_insert(SalesDaily).values(rows))
    db.commit()
    return org.id


def _poisson(rng: random.Random, lam: float) -> int:
    import math

    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--orgs", type=int, default=50)
    ap.add_argument("--skus", type=int, default=2000)
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--out", default="loadtest/orgs.txt")
    a = ap.parse_args()
    rng = random.Random(42)
    ids = []
    with SessionLocal() as db:
        for i in range(a.orgs):
            ids.append(seed_org(db, i, a.skus, a.days, date.today() - timedelta(days=1), rng))
            print(f"seeded org {i + 1}/{a.orgs}", flush=True)
    try:
        with open(a.out, "w") as f:
            f.write("\n".join(str(x) for x in ids) + "\n")
    except OSError:
        pass
    print("\n".join(str(x) for x in ids))


if __name__ == "__main__":
    main()
