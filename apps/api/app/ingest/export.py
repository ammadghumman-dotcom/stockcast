"""Export org data as CSV in the same shape the CSV importer accepts (round-trip safe)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.ingest.csv_connector import to_csv
from app.ingest.records import BomRecord, InventoryRecord, ProductRecord, SalesRecord
from app.models import (
    BomLine,
    Channel,
    InventoryLevel,
    Location,
    Product,
    ProductCategory,
    SalesDaily,
)


def export_csv(db: Session, org_id: uuid.UUID, kind: str, channel_id: uuid.UUID | None) -> str:
    return to_csv(kind, _rows(db, org_id, kind, channel_id))


def _rows(db: Session, org_id: uuid.UUID, kind: str, channel_id: uuid.UUID | None) -> Iterator:
    if kind == "products":
        q = (
            select(Product, ProductCategory.name)
            .outerjoin(ProductCategory, Product.category_id == ProductCategory.id)
            .where(Product.org_id == org_id)
            .order_by(Product.sku)
        )
        for p, cat in db.execute(q):
            yield ProductRecord(
                sku=p.sku,
                name=p.name,
                type=p.type,
                unit_cost=p.unit_cost,
                unit=p.unit,
                category=cat,
            )
    elif kind == "sales":
        qs = (
            select(SalesDaily.date, Product.sku, SalesDaily.units, SalesDaily.revenue)
            .join(Product, Product.id == SalesDaily.product_id)
            .join(Channel, Channel.id == SalesDaily.channel_id)
            .where(SalesDaily.org_id == org_id)
            .order_by(SalesDaily.date, Product.sku)
        )
        if channel_id:
            qs = qs.where(SalesDaily.channel_id == channel_id)
        for d, sku, units, revenue in db.execute(qs):
            yield SalesRecord(date=d, sku=sku, units=units, revenue=revenue)
    elif kind == "inventory":
        qi = (
            select(Product.sku, Location.name, InventoryLevel.on_hand, InventoryLevel.inbound)
            .join(Product, Product.id == InventoryLevel.product_id)
            .join(Location, Location.id == InventoryLevel.location_id)
            .where(InventoryLevel.org_id == org_id)
            .order_by(Product.sku, Location.name)
        )
        for sku, loc, on_hand, inbound in db.execute(qi):
            yield InventoryRecord(sku=sku, location=loc, on_hand=on_hand, inbound=inbound)
    elif kind == "bom":
        parent, comp = aliased(Product), aliased(Product)
        qb = (
            select(parent.sku, comp.sku, BomLine.qty_per_unit)
            .join(parent, parent.id == BomLine.parent_product_id)
            .join(comp, comp.id == BomLine.component_product_id)
            .where(BomLine.org_id == org_id)
            .order_by(parent.sku, comp.sku)
        )
        for parent_sku, comp_sku, qty in db.execute(qb):
            yield BomRecord(parent_sku=parent_sku, component_sku=comp_sku, qty_per_unit=qty)
    else:
        raise ValueError(kind)
