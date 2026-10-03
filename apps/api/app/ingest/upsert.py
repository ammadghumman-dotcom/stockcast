"""Idempotent upserts from normalized records into the org's tables.

All functions are org-scoped and safe to re-run: products by (org, sku), listings by
(channel, external_id), sales by (date, product, channel) with SET semantics, inventory by
(product, location), BOM lines by (parent, component).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.ingest.records import (
    BomRecord,
    IngestResult,
    InventoryRecord,
    ProductRecord,
    RowError,
    SalesRecord,
)
from app.models import (
    BomLine,
    Channel,
    ChannelListing,
    InventoryLevel,
    Location,
    Product,
    ProductCategory,
    SalesDaily,
)


class ProductResolver:
    """Maps sku / external_id -> product_id for one org (+ channel), cached per sync."""

    def __init__(self, db: Session, org_id: uuid.UUID, channel: Channel | None = None) -> None:
        self.db, self.org_id, self.channel = db, org_id, channel
        self._by_sku: dict[str, uuid.UUID] = {
            sku: pid
            for sku, pid in db.execute(
                select(Product.sku, Product.id).where(Product.org_id == org_id)
            )
        }
        self._by_ext: dict[str, uuid.UUID] = {}
        if channel is not None:
            self._by_ext = {
                ext: pid
                for ext, pid in db.execute(
                    select(ChannelListing.external_id, ChannelListing.product_id).where(
                        ChannelListing.channel_id == channel.id
                    )
                )
            }

    def resolve(self, sku: str | None, external_id: str | None) -> uuid.UUID | None:
        if external_id and external_id in self._by_ext:
            return self._by_ext[external_id]
        if sku and sku in self._by_sku:
            return self._by_sku[sku]
        return None

    def remember(self, product: Product, external_id: str | None = None) -> None:
        self._by_sku[product.sku] = product.id
        if external_id:
            self._by_ext[external_id] = product.id


def upsert_products(
    db: Session,
    org_id: uuid.UUID,
    records: Iterable[ProductRecord],
    channel: Channel | None = None,
) -> IngestResult:
    res = IngestResult(kind="products")
    resolver = ProductResolver(db, org_id, channel)
    categories = {
        name: cid
        for name, cid in db.execute(
            select(ProductCategory.name, ProductCategory.id).where(ProductCategory.org_id == org_id)
        )
    }
    for i, rec in enumerate(records, start=1):
        res.received += 1
        category_id = None
        if rec.category:
            category_id = categories.get(rec.category)
            if category_id is None:
                cat = ProductCategory(org_id=org_id, name=rec.category)
                db.add(cat)
                db.flush()
                categories[rec.category] = category_id = cat.id

        pid = resolver.resolve(rec.sku, rec.external_id)
        if pid is None:
            product = Product(
                org_id=org_id,
                sku=rec.sku,
                name=rec.name,
                type=rec.type,
                unit_cost=rec.unit_cost,
                unit=rec.unit,
                category_id=category_id,
            )
            db.add(product)
            db.flush()
            res.inserted += 1
        else:
            product = db.get(Product, pid)
            assert product is not None
            product.name = rec.name
            product.type = rec.type
            product.unit = rec.unit
            if rec.unit_cost:
                product.unit_cost = rec.unit_cost
            if category_id:
                product.category_id = category_id
            res.updated += 1

        if channel is not None and rec.external_id:
            stmt = pg_insert(ChannelListing).values(
                id=uuid.uuid4(),
                org_id=org_id,
                product_id=product.id,
                channel_id=channel.id,
                external_id=rec.external_id,
                external_sku=rec.external_sku,
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_channel_listings_channel_ext",
                set_={"product_id": product.id, "external_sku": rec.external_sku},
            )
            db.execute(stmt)
        resolver.remember(product, rec.external_id)
        _ = i
    db.flush()
    return res


def upsert_sales(
    db: Session, org_id: uuid.UUID, channel: Channel, records: Iterable[SalesRecord]
) -> IngestResult:
    """Aggregate to (date, product) then SET units/revenue. Re-running a backfill is a no-op."""
    res = IngestResult(kind="sales")
    resolver = ProductResolver(db, org_id, channel)
    agg: dict[tuple, list[Decimal]] = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for i, rec in enumerate(records, start=1):
        res.received += 1
        pid = resolver.resolve(rec.sku, rec.external_id)
        if pid is None:
            res.errors.append(
                RowError(row=i, message=f"unknown product sku={rec.sku!r} ext={rec.external_id!r}")
            )
            continue
        key = (rec.date, pid)
        agg[key][0] += rec.units
        agg[key][1] += rec.revenue
    rows = [
        {
            "date": d,
            "product_id": pid,
            "channel_id": channel.id,
            "region_id": channel.region_id,
            "org_id": org_id,
            "units": u,
            "revenue": r,
        }
        for (d, pid), (u, r) in agg.items()
    ]
    for chunk in _chunks(rows, 2000):
        stmt = pg_insert(SalesDaily).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["date", "product_id", "channel_id"],
            set_={
                "units": stmt.excluded.units,
                "revenue": stmt.excluded.revenue,
                "region_id": stmt.excluded.region_id,
            },
        )
        db.execute(stmt)
    res.inserted = len(rows)
    db.flush()
    return res


def increment_sales(
    db: Session, org_id: uuid.UUID, channel: Channel, records: Iterable[SalesRecord]
) -> IngestResult:
    """ADD units/revenue (webhook deltas). Callers must dedupe deliveries first."""
    res = IngestResult(kind="sales")
    resolver = ProductResolver(db, org_id, channel)
    for i, rec in enumerate(records, start=1):
        res.received += 1
        pid = resolver.resolve(rec.sku, rec.external_id)
        if pid is None:
            res.errors.append(RowError(row=i, message=f"unknown product ext={rec.external_id!r}"))
            continue
        stmt = pg_insert(SalesDaily).values(
            date=rec.date,
            product_id=pid,
            channel_id=channel.id,
            region_id=channel.region_id,
            org_id=org_id,
            units=rec.units,
            revenue=rec.revenue,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["date", "product_id", "channel_id"],
            set_={
                "units": SalesDaily.units + stmt.excluded.units,
                "revenue": SalesDaily.revenue + stmt.excluded.revenue,
            },
        )
        db.execute(stmt)
        res.inserted += 1
    db.flush()
    return res


def upsert_inventory(
    db: Session,
    org_id: uuid.UUID,
    records: Iterable[InventoryRecord],
    channel: Channel | None = None,
) -> IngestResult:
    res = IngestResult(kind="inventory")
    resolver = ProductResolver(db, org_id, channel)
    locations = {
        name: lid
        for name, lid in db.execute(
            select(Location.name, Location.id).where(Location.org_id == org_id)
        )
    }
    now = datetime.now(UTC)
    for i, rec in enumerate(records, start=1):
        res.received += 1
        pid = resolver.resolve(rec.sku, rec.external_id)
        if pid is None:
            res.errors.append(
                RowError(row=i, message=f"unknown product sku={rec.sku!r} ext={rec.external_id!r}")
            )
            continue
        lid = locations.get(rec.location)
        if lid is None:
            loc = Location(org_id=org_id, name=rec.location, kind="warehouse")
            db.add(loc)
            db.flush()
            locations[rec.location] = lid = loc.id
        stmt = pg_insert(InventoryLevel).values(
            id=uuid.uuid4(),
            org_id=org_id,
            product_id=pid,
            location_id=lid,
            on_hand=rec.on_hand,
            inbound=rec.inbound,
            as_of=now,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_inventory_levels_product_loc",
            set_={"on_hand": rec.on_hand, "inbound": rec.inbound, "as_of": now},
        )
        db.execute(stmt)
        res.inserted += 1
    db.flush()
    return res


def upsert_bom(db: Session, org_id: uuid.UUID, records: Iterable[BomRecord]) -> IngestResult:
    res = IngestResult(kind="bom")
    resolver = ProductResolver(db, org_id)
    for i, rec in enumerate(records, start=1):
        res.received += 1
        parent = resolver.resolve(rec.parent_sku, None)
        comp = resolver.resolve(rec.component_sku, None)
        if parent is None or comp is None:
            missing = rec.parent_sku if parent is None else rec.component_sku
            res.errors.append(RowError(row=i, message=f"unknown product sku={missing!r}"))
            continue
        if parent == comp:
            res.errors.append(RowError(row=i, message="parent and component are the same sku"))
            continue
        stmt = pg_insert(BomLine).values(
            id=uuid.uuid4(),
            org_id=org_id,
            parent_product_id=parent,
            component_product_id=comp,
            qty_per_unit=rec.qty_per_unit,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_bom_lines_parent_component", set_={"qty_per_unit": rec.qty_per_unit}
        )
        db.execute(stmt)
        res.inserted += 1
    db.flush()
    return res


def _chunks[T](items: list[T], size: int) -> Iterable[list[T]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]
