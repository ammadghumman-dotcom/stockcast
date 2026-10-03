import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.deps import DB, OrgId
from app.models import BomLine, Product
from app.schemas.catalog import BomLineCreate, BomLineRead, BomLineUpdate
from app.services import crud

router = APIRouter(prefix="/bom-lines", tags=["bom"])


@router.get("", response_model=list[BomLineRead])
def list_bom_lines(
    db: DB,
    org_id: OrgId,
    parent_product_id: uuid.UUID | None = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
) -> list[BomLine]:
    stmt = select(BomLine).where(BomLine.org_id == org_id)
    if parent_product_id:
        stmt = stmt.where(BomLine.parent_product_id == parent_product_id)
    return list(db.scalars(stmt.order_by(BomLine.created_at).limit(limit).offset(offset)).all())


@router.get("/{bom_line_id}", response_model=BomLineRead)
def get_bom_line(db: DB, org_id: OrgId, bom_line_id: uuid.UUID) -> BomLine:
    return crud.get_scoped(db, BomLine, org_id, bom_line_id)


@router.post("", response_model=BomLineRead, status_code=status.HTTP_201_CREATED)
def create_bom_line(db: DB, org_id: OrgId, body: BomLineCreate) -> BomLine:
    crud.assert_owned(db, Product, org_id, body.parent_product_id)
    crud.assert_owned(db, Product, org_id, body.component_product_id)
    return crud.create_scoped(db, BomLine, org_id, body)


@router.patch("/{bom_line_id}", response_model=BomLineRead)
def update_bom_line(db: DB, org_id: OrgId, bom_line_id: uuid.UUID, body: BomLineUpdate) -> BomLine:
    return crud.update_scoped(db, BomLine, org_id, bom_line_id, body)
