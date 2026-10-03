import uuid

from fastapi import APIRouter, Query, status

from app.deps import DB, OrgId
from app.models import Supplier
from app.schemas.catalog import SupplierCreate, SupplierRead, SupplierUpdate
from app.services import crud

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
