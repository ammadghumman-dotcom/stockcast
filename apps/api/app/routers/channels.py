import uuid

from fastapi import APIRouter, HTTPException, Query, status

from app.billing.plans import assert_can_add_channel
from app.deps import DB, OrgId
from app.ingest.tasks import enqueue_sync
from app.models import Channel, ChannelType, Region, SyncRun
from app.schemas.ingest import ChannelCreate, ChannelRead, ChannelUpdate, SyncRunRead
from app.services import crud

router = APIRouter(prefix="/channels", tags=["channels"])


def _read(ch: Channel) -> ChannelRead:
    return ChannelRead.model_validate(
        {**ch.__dict__, "is_connected": ch.credentials_encrypted is not None}
    )


@router.get("", response_model=list[ChannelRead])
def list_channels(db: DB, org_id: OrgId, limit: int = Query(100, le=500), offset: int = 0):
    return [_read(c) for c in crud.list_scoped(db, Channel, org_id, limit=limit, offset=offset)]


@router.get("/{channel_id}", response_model=ChannelRead)
def get_channel(db: DB, org_id: OrgId, channel_id: uuid.UUID):
    return _read(crud.get_scoped(db, Channel, org_id, channel_id))


@router.post("", response_model=ChannelRead, status_code=status.HTTP_201_CREATED)
def create_channel(db: DB, org_id: OrgId, body: ChannelCreate):
    if body.region_id:
        crud.assert_owned(db, Region, org_id, body.region_id)
    if body.type == ChannelType.shopify:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Shopify channels are created by the install flow: GET /shopify/install?shop=...",
        )
    assert_can_add_channel(db, org_id)
    return _read(crud.create_scoped(db, Channel, org_id, body))


@router.patch("/{channel_id}", response_model=ChannelRead)
def update_channel(db: DB, org_id: OrgId, channel_id: uuid.UUID, body: ChannelUpdate):
    if body.region_id:
        crud.assert_owned(db, Region, org_id, body.region_id)
    return _read(crud.update_scoped(db, Channel, org_id, channel_id, body))


@router.post("/{channel_id}/sync", response_model=SyncRunRead, status_code=202)
def trigger_sync(db: DB, org_id: OrgId, channel_id: uuid.UUID, full: bool = False):
    ch = crud.get_scoped(db, Channel, org_id, channel_id)
    if ch.type == ChannelType.csv:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "CSV channels sync via upload")
    if ch.credentials_encrypted is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "channel is not connected")
    return enqueue_sync(db, ch, trigger="manual", full=full)


@router.get("/{channel_id}/sync-runs", response_model=list[SyncRunRead])
def list_sync_runs(db: DB, org_id: OrgId, channel_id: uuid.UUID, limit: int = Query(20, le=200)):
    crud.get_scoped(db, Channel, org_id, channel_id)
    from sqlalchemy import select

    return list(
        db.scalars(
            select(SyncRun)
            .where(SyncRun.org_id == org_id, SyncRun.channel_id == channel_id)
            .order_by(SyncRun.created_at.desc())
            .limit(limit)
        ).all()
    )
