"""Product categories + per-product sales history / inventory by location (for the UI)."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.deps import DB, OrgId
from app.models import InventoryLevel, Location, Product, ProductCategory, SalesDaily
from app.schemas.common import OrmModel, Timestamped
from app.services import crud

router = APIRouter(tags=["catalog"])


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class CategoryRead(Timestamped):
    org_id: uuid.UUID
    name: str


@router.get("/product-categories", response_model=list[CategoryRead])
def list_categories(db: DB, org_id: OrgId):
    return list(
        db.scalars(
            select(ProductCategory)
            .where(ProductCategory.org_id == org_id)
            .order_by(ProductCategory.name)
        ).all()
    )


@router.post(
    "/product-categories", response_model=CategoryRead, status_code=status.HTTP_201_CREATED
)
def create_category(db: DB, org_id: OrgId, body: CategoryCreate):
    return crud.create_scoped(db, ProductCategory, org_id, body)


@router.patch("/product-categories/{category_id}", response_model=CategoryRead)
def update_category(db: DB, org_id: OrgId, category_id: uuid.UUID, body: CategoryCreate):
    return crud.update_scoped(db, ProductCategory, org_id, category_id, body)


class SalesPoint(BaseModel):
    date: date
    units: Decimal
    revenue: Decimal


@router.get("/products/{product_id}/sales", response_model=list[SalesPoint])
def product_sales(
    db: DB, org_id: OrgId, product_id: uuid.UUID, days: int = Query(180, ge=7, le=730)
):
    crud.get_scoped(db, Product, org_id, product_id)
    since = date.today() - timedelta(days=days)
    rows = db.execute(
        select(SalesDaily.date, func.sum(SalesDaily.units), func.sum(SalesDaily.revenue))
        .where(
            SalesDaily.org_id == org_id,
            SalesDaily.product_id == product_id,
            SalesDaily.date >= since,
        )
        .group_by(SalesDaily.date)
        .order_by(SalesDaily.date)
    ).all()
    return [SalesPoint(date=d, units=u, revenue=r) for d, u, r in rows]


class InventoryRow(OrmModel):
    location_id: uuid.UUID
    location_name: str
    on_hand: Decimal
    inbound: Decimal


@router.get("/products/{product_id}/inventory", response_model=list[InventoryRow])
def product_inventory(db: DB, org_id: OrgId, product_id: uuid.UUID):
    crud.get_scoped(db, Product, org_id, product_id)
    rows = db.execute(
        select(
            InventoryLevel.location_id,
            Location.name,
            InventoryLevel.on_hand,
            InventoryLevel.inbound,
        )
        .join(Location, Location.id == InventoryLevel.location_id)
        .where(InventoryLevel.org_id == org_id, InventoryLevel.product_id == product_id)
        .order_by(Location.name)
    ).all()
    return [
        InventoryRow(location_id=a, location_name=b, on_hand=c, inbound=d) for a, b, c, d in rows
    ]
