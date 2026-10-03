"""Organizations + team members. Pre-Clerk (Step 7): no auth, used by onboarding and settings."""

import re
import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from app.deps import DB, OrgId
from app.models import Organization, PlanningSettings, Region, User
from app.schemas.common import Timestamped
from app.services import crud

router = APIRouter(tags=["orgs"])


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    region_code: str = Field(default="US", min_length=2, max_length=8)
    currency: str = Field(default="USD", min_length=3, max_length=3)


class OrgRead(Timestamped):
    name: str
    slug: str


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(default="viewer", pattern="^(owner|admin|viewer)$")


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: str | None = Field(default=None, pattern="^(owner|admin|viewer)$")


class UserRead(Timestamped):
    org_id: uuid.UUID
    email: str
    name: str
    role: str


@router.post("/orgs", response_model=OrgRead, status_code=status.HTTP_201_CREATED)
def create_org(db: DB, body: OrgCreate):
    base = re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-") or "org"
    slug, n = base, 1
    while db.scalar(select(Organization.id).where(Organization.slug == slug)):
        n += 1
        slug = f"{base}-{n}"
    org = Organization(name=body.name, slug=slug)
    db.add(org)
    db.flush()
    region = Region(
        org_id=org.id,
        code=body.region_code.upper(),
        name=body.region_code.upper(),
        currency=body.currency.upper(),
    )
    db.add(region)
    db.add(PlanningSettings(org_id=org.id))
    db.flush()
    from app.forecast.holidays_seed import seed_region_holidays

    seed_region_holidays(db, org.id, region)
    db.commit()
    db.refresh(org)
    return org


@router.get("/orgs/me", response_model=OrgRead)
def current_org(db: DB, org_id: OrgId):
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return org


@router.get("/users", response_model=list[UserRead])
def list_users(db: DB, org_id: OrgId):
    return list(crud.list_scoped(db, User, org_id))


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(db: DB, org_id: OrgId, body: UserCreate):
    return crud.create_scoped(db, User, org_id, body)


@router.patch("/users/{user_id}", response_model=UserRead)
def update_user(db: DB, org_id: OrgId, user_id: uuid.UUID, body: UserUpdate):
    return crud.update_scoped(db, User, org_id, user_id, body)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(db: DB, org_id: OrgId, user_id: uuid.UUID):
    db.delete(crud.get_scoped(db, User, org_id, user_id))
    db.commit()
