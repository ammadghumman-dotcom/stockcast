import uuid

from fastapi import APIRouter, Query, status

from app.deps import DB, Ctx, OrgId
from app.models import Supplier
from app.schemas.catalog import (
    SupplierCreate,
    SupplierItemCreate,
    SupplierItemRead,
    SupplierItemUpdate,
    SupplierRead,
    SupplierUpdate,
)
from app.services import crud, supplier_items

router = APIRouter(prefix="/suppliers", tags=["suppliers"])


@router.get("", response_model=list[SupplierRead])
def list_suppliers(
    db: DB, org_id: OrgId, limit: int = Query(100, le=500), offset: int = 0
) -> list[Supplier]:
    return list(crud.list_scoped(db, Supplier, org_id, limit=limit, offset=offset))


@router.get("/{supplier_id}", response_model=SupplierRead)
def get_supplier(db: DB, org_id: OrgId, supplier_id: uuid.UUID) -> Supplier:
    return crud.get_scoped(db, Supplier, org_id, supplier_id)


@router.post("", response_model=SupplierRead, status_code=status.HTTP_201_CREATED)
def create_supplier(db: DB, org_id: OrgId, body: SupplierCreate) -> Supplier:
    return crud.create_scoped(db, Supplier, org_id, body)


@router.patch("/{supplier_id}", response_model=SupplierRead)
def update_supplier(
    db: DB, org_id: OrgId, supplier_id: uuid.UUID, body: SupplierUpdate
) -> Supplier:
    return crud.update_scoped(db, Supplier, org_id, supplier_id, body)


# ---- supplier items: price, pack size and lead time per product (CAT-04) ----
@router.get("/{supplier_id}/items", response_model=list[SupplierItemRead])
def list_supplier_items(db: DB, org_id: OrgId, supplier_id: uuid.UUID) -> list[SupplierItemRead]:
    return supplier_items.list_items(db, org_id, supplier_id)


@router.post(
    "/{supplier_id}/items", response_model=SupplierItemRead, status_code=status.HTTP_201_CREATED
)
def create_supplier_item(
    db: DB, ctx: Ctx, supplier_id: uuid.UUID, body: SupplierItemCreate
) -> SupplierItemRead:
    ctx.require("admin")
    return supplier_items.create(db, ctx, supplier_id, body)


@router.patch("/{supplier_id}/items/{item_id}", response_model=SupplierItemRead)
def update_supplier_item(
    db: DB, ctx: Ctx, supplier_id: uuid.UUID, item_id: uuid.UUID, body: SupplierItemUpdate
) -> SupplierItemRead:
    ctx.require("admin")
    return supplier_items.update(db, ctx, supplier_id, item_id, body)


@router.delete("/{supplier_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_supplier_item(db: DB, ctx: Ctx, supplier_id: uuid.UUID, item_id: uuid.UUID) -> None:
    ctx.require("admin")
    supplier_items.delete(db, ctx, supplier_id, item_id)
