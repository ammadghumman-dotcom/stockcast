"""Regions, holiday events (built-in seeding + custom), learned/prior uplifts, promotions."""

import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.deps import DB, OrgId
from app.forecast.holidays_seed import seed_region_holidays
from app.models import (
    CategoryHolidayUplift,
    Channel,
    HolidayEvent,
    ProductCategory,
    Promotion,
    Region,
)
from app.models.enums import HolidaySource
from app.schemas.calendar import (
    HolidayEventCreate,
    HolidayEventRead,
    HolidayEventUpdate,
    PromotionCreate,
    PromotionRead,
    PromotionUpdate,
    RegionCreate,
    RegionRead,
    UpliftRead,
    UpliftUpdate,
)
from app.services import crud

router = APIRouter(tags=["calendar"])


# ---- regions ----
@router.get("/regions", response_model=list[RegionRead])
def list_regions(db: DB, org_id: OrgId):
    return list(crud.list_scoped(db, Region, org_id))


@router.post("/regions", response_model=RegionRead, status_code=status.HTTP_201_CREATED)
def create_region(db: DB, org_id: OrgId, body: RegionCreate, seed_holidays: bool = True):
    region = crud.create_scoped(db, Region, org_id, body)
    if seed_holidays:
        seed_region_holidays(db, org_id, region)
        db.commit()
    return region


@router.post("/regions/{region_id}/holidays/seed", response_model=dict)
def seed_holidays(
    db: DB, org_id: OrgId, region_id: uuid.UUID, years: list[int] | None = Query(None)
):
    region = crud.get_scoped(db, Region, org_id, region_id)
    n = seed_region_holidays(db, org_id, region, years)
    db.commit()
    return {"region_id": str(region_id), "added": n}


# ---- holiday events ----
@router.get("/holiday-events", response_model=list[HolidayEventRead])
def list_events(
    db: DB, org_id: OrgId, region_id: uuid.UUID | None = None, limit: int = Query(500, le=2000)
):
    stmt = select(HolidayEvent).where(HolidayEvent.org_id == org_id)
    if region_id:
        stmt = stmt.where(HolidayEvent.region_id == region_id)
    return list(db.scalars(stmt.order_by(HolidayEvent.start_date).limit(limit)).all())


@router.post(
    "/holiday-events", response_model=HolidayEventRead, status_code=status.HTTP_201_CREATED
)
def create_event(db: DB, org_id: OrgId, body: HolidayEventCreate):
    crud.assert_owned(db, Region, org_id, body.region_id)
    ev = HolidayEvent(org_id=org_id, source=HolidaySource.custom, **body.model_dump())
    db.add(ev)
    crud._commit(db)
    db.refresh(ev)
    return ev


@router.patch("/holiday-events/{event_id}", response_model=HolidayEventRead)
def update_event(db: DB, org_id: OrgId, event_id: uuid.UUID, body: HolidayEventUpdate):
    return crud.update_scoped(db, HolidayEvent, org_id, event_id, body)


@router.delete("/holiday-events/{event_id}", status_code=204)
def delete_event(db: DB, org_id: OrgId, event_id: uuid.UUID):
    ev = crud.get_scoped(db, HolidayEvent, org_id, event_id)
    db.delete(ev)
    db.commit()


# ---- uplifts (learned + editable priors) ----
@router.get("/category-uplifts", response_model=list[UpliftRead])
def list_uplifts(
    db: DB, org_id: OrgId, category_id: uuid.UUID | None = None, learned: bool | None = None
):
    stmt = select(CategoryHolidayUplift).where(CategoryHolidayUplift.org_id == org_id)
    if category_id:
        stmt = stmt.where(CategoryHolidayUplift.category_id == category_id)
    if learned is not None:
        stmt = stmt.where(CategoryHolidayUplift.learned.is_(learned))
    return list(db.scalars(stmt.order_by(CategoryHolidayUplift.event_name)).all())


@router.patch("/category-uplifts/{uplift_id}", response_model=UpliftRead)
def update_uplift(db: DB, org_id: OrgId, uplift_id: uuid.UUID, body: UpliftUpdate):
    """Editing a value makes it manual: forecasts use it as is and learning never replaces it."""
    row = crud.get_scoped(db, CategoryHolidayUplift, org_id, uplift_id)
    row.uplift_pct, row.learned, row.sample_size = body.uplift_pct, False, 0
    row.manual = True
    db.commit()
    db.refresh(row)
    return row


# ---- promotions ----
@router.get("/promotions", response_model=list[PromotionRead])
def list_promotions(db: DB, org_id: OrgId, limit: int = Query(200, le=1000)):
    return list(crud.list_scoped(db, Promotion, org_id, limit=limit))


@router.get("/promotions/{promotion_id}", response_model=PromotionRead)
def get_promotion(db: DB, org_id: OrgId, promotion_id: uuid.UUID):
    return crud.get_scoped(db, Promotion, org_id, promotion_id)


@router.post("/promotions", response_model=PromotionRead, status_code=status.HTTP_201_CREATED)
def create_promotion(db: DB, org_id: OrgId, body: PromotionCreate):
    _check_promo_refs(db, org_id, body.channel_id, body.category_id)
    data = body.model_dump()
    data["product_ids"] = [str(x) for x in body.product_ids] if body.product_ids else None
    promo = Promotion(org_id=org_id, **data)
    db.add(promo)
    crud._commit(db)
    db.refresh(promo)
    return promo


@router.patch("/promotions/{promotion_id}", response_model=PromotionRead)
def update_promotion(db: DB, org_id: OrgId, promotion_id: uuid.UUID, body: PromotionUpdate):
    return crud.update_scoped(db, Promotion, org_id, promotion_id, body)


@router.delete("/promotions/{promotion_id}", status_code=204)
def delete_promotion(db: DB, org_id: OrgId, promotion_id: uuid.UUID):
    db.delete(crud.get_scoped(db, Promotion, org_id, promotion_id))
    db.commit()


def _check_promo_refs(db, org_id, channel_id, category_id):
    if channel_id:
        crud.assert_owned(db, Channel, org_id, channel_id)
    if category_id:
        crud.assert_owned(db, ProductCategory, org_id, category_id)
