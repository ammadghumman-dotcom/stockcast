"""Supplier items: per-product price, pack size and lead-time override for one supplier.

Planning reads these rows (planning/engine.py) to pick the cheapest supplier, round order
quantities to the pack size and use the item lead time ahead of the supplier's default; draft
POs take the item price.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import AuthContext
from app.models import Product, Supplier, SupplierProduct
from app.schemas.catalog import SupplierItemCreate, SupplierItemRead, SupplierItemUpdate
from app.services import audit, crud


def _read(item: SupplierProduct, product: Product, supplier: Supplier) -> SupplierItemRead:
    return SupplierItemRead(
        id=item.id,
        created_at=item.created_at,
        updated_at=item.updated_at,
        supplier_id=item.supplier_id,
        product_id=item.product_id,
        sku=product.sku,
        product_name=product.name,
        unit=product.unit,
        price=item.price,
        pack_size=item.pack_size,
        lead_time_days=item.lead_time_days,
        effective_lead_time_days=(
            item.lead_time_days if item.lead_time_days is not None else supplier.lead_time_days
        ),
    )


def _snap(item: SupplierProduct) -> dict:
    return {
        "product_id": str(item.product_id),
        "price": str(item.price),
        "pack_size": item.pack_size,
        "lead_time_days": item.lead_time_days,
    }


def list_items(db: Session, org_id: uuid.UUID, supplier_id: uuid.UUID) -> list[SupplierItemRead]:
    supplier = crud.get_scoped(db, Supplier, org_id, supplier_id)
    rows = db.execute(
        select(SupplierProduct, Product)
        .join(Product, Product.id == SupplierProduct.product_id)
        .where(SupplierProduct.org_id == org_id, SupplierProduct.supplier_id == supplier_id)
        .order_by(Product.sku)
    ).all()
    return [_read(i, p, supplier) for i, p in rows]


def _get(
    db: Session, org_id: uuid.UUID, supplier_id: uuid.UUID, item_id: uuid.UUID
) -> SupplierProduct:
    item = db.scalar(
        select(SupplierProduct).where(
            SupplierProduct.id == item_id,
            SupplierProduct.org_id == org_id,
            SupplierProduct.supplier_id == supplier_id,
        )
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Supplier item not found")
    return item


def create(
    db: Session, ctx: AuthContext, supplier_id: uuid.UUID, body: SupplierItemCreate
) -> SupplierItemRead:
    supplier = crud.get_scoped(db, Supplier, ctx.org_id, supplier_id)
    crud.assert_owned(db, Product, ctx.org_id, body.product_id)
    product = db.get(Product, body.product_id)
    assert product is not None
    exists = db.scalar(
        select(SupplierProduct.id).where(
            SupplierProduct.supplier_id == supplier_id,
            SupplierProduct.product_id == body.product_id,
        )
    )
    if exists:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{supplier.name} already has a price for {product.sku}. Edit that row instead.",
        )
    item = SupplierProduct(org_id=ctx.org_id, supplier_id=supplier_id, **body.model_dump())
    db.add(item)
    db.flush()
    audit.record(
        db,
        ctx,
        action="supplier_item.create",
        entity="supplier_product",
        entity_id=item.id,
        after=_snap(item),
    )
    db.commit()
    db.refresh(item)
    return _read(item, product, supplier)


def update(
    db: Session,
    ctx: AuthContext,
    supplier_id: uuid.UUID,
    item_id: uuid.UUID,
    body: SupplierItemUpdate,
) -> SupplierItemRead:
    supplier = crud.get_scoped(db, Supplier, ctx.org_id, supplier_id)
    item = _get(db, ctx.org_id, supplier_id, item_id)
    before = _snap(item)
    changes = body.model_dump(exclude_unset=True)
    for k in ("price", "pack_size"):
        if k in changes and changes[k] is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{k} cannot be empty")
    for k, v in changes.items():
        setattr(item, k, v)
    audit.record(
        db,
        ctx,
        action="supplier_item.update",
        entity="supplier_product",
        entity_id=item.id,
        before=before,
        after=_snap(item),
    )
    db.commit()
    db.refresh(item)
    product = db.get(Product, item.product_id)
    assert product is not None
    return _read(item, product, supplier)


def delete(db: Session, ctx: AuthContext, supplier_id: uuid.UUID, item_id: uuid.UUID) -> None:
    crud.get_scoped(db, Supplier, ctx.org_id, supplier_id)
    item = _get(db, ctx.org_id, supplier_id, item_id)
    audit.record(
        db,
        ctx,
        action="supplier_item.delete",
        entity="supplier_product",
        entity_id=item.id,
        before=_snap(item),
    )
    db.delete(item)
    db.commit()
