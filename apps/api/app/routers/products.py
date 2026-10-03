import uuid

from fastapi import APIRouter, Query, status

from app.deps import DB, OrgId
from app.models import Product, ProductCategory
from app.schemas.catalog import ProductCreate, ProductRead, ProductUpdate
from app.services import crud

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=list[ProductRead])
def list_products(
    db: DB, org_id: OrgId, limit: int = Query(100, le=500), offset: int = 0
) -> list[Product]:
    return list(crud.list_scoped(db, Product, org_id, limit=limit, offset=offset))


@router.get("/{product_id}", response_model=ProductRead)
def get_product(db: DB, org_id: OrgId, product_id: uuid.UUID) -> Product:
    return crud.get_scoped(db, Product, org_id, product_id)


@router.post("", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
def create_product(db: DB, org_id: OrgId, body: ProductCreate) -> Product:
    if body.category_id:
        crud.assert_owned(db, ProductCategory, org_id, body.category_id)
    return crud.create_scoped(db, Product, org_id, body)


@router.patch("/{product_id}", response_model=ProductRead)
def update_product(db: DB, org_id: OrgId, product_id: uuid.UUID, body: ProductUpdate) -> Product:
    if body.category_id:
        crud.assert_owned(db, ProductCategory, org_id, body.category_id)
    return crud.update_scoped(db, Product, org_id, product_id, body)
