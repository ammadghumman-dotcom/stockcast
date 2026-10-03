import uuid

from fastapi import APIRouter, Query, status

from app.deps import DB, OrgId
from app.models import Location
from app.schemas.catalog import LocationCreate, LocationRead, LocationUpdate
from app.services import crud

router = APIRouter(prefix="/locations", tags=["locations"])


@router.get("", response_model=list[LocationRead])
def list_locations(
    db: DB, org_id: OrgId, limit: int = Query(100, le=500), offset: int = 0
) -> list[Location]:
    return list(crud.list_scoped(db, Location, org_id, limit=limit, offset=offset))


@router.get("/{location_id}", response_model=LocationRead)
def get_location(db: DB, org_id: OrgId, location_id: uuid.UUID) -> Location:
    return crud.get_scoped(db, Location, org_id, location_id)


@router.post("", response_model=LocationRead, status_code=status.HTTP_201_CREATED)
def create_location(db: DB, org_id: OrgId, body: LocationCreate) -> Location:
    return crud.create_scoped(db, Location, org_id, body)


@router.patch("/{location_id}", response_model=LocationRead)
def update_location(
    db: DB, org_id: OrgId, location_id: uuid.UUID, body: LocationUpdate
) -> Location:
    return crud.update_scoped(db, Location, org_id, location_id, body)
