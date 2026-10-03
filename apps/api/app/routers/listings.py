"""Channel listings (external id -> product) and the SKU mapping screen."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.deps import DB, Ctx, OrgId
from app.models import Channel, ChannelListing, Product
from app.services import audit, crud
from app.services import listings as svc

router = APIRouter(prefix="/listings", tags=["listings"])


class ListingRead(BaseModel):
    id: uuid.UUID
    channel_id: uuid.UUID
    external_id: str
    external_sku: str | None
    product_id: uuid.UUID
    product_sku: str
    product_name: str
    # how many listings (any channel) point at this product — 1 means "only this one"
    product_listing_count: int


class SuggestionRead(BaseModel):
    product_id: uuid.UUID
    sku: str
    name: str
    score: float
    reason: str


class MatchRequest(BaseModel):
    channel_id: uuid.UUID
    external_ids: list[str] | None = None  # default: every listing on the channel
    limit: int = Field(default=5, ge=1, le=20)
    only_unmatched: bool = True  # skip listings whose product is already shared/mapped by hand


class MatchResult(BaseModel):
    listing: ListingRead
    suggestions: list[SuggestionRead]


class OverrideRequest(BaseModel):
    product_id: uuid.UUID


class OverrideResult(BaseModel):
    listing: ListingRead
    moved_sales_rows: int
    deleted_product: bool


def _reads(db, org_id: uuid.UUID, rows: list[ChannelListing]) -> list[ListingRead]:
    pids = {r.product_id for r in rows}
    counts = dict(
        db.execute(
            select(ChannelListing.product_id, func.count())
            .where(ChannelListing.org_id == org_id, ChannelListing.product_id.in_(pids))
            .group_by(ChannelListing.product_id)
        ).all()
    )
    products = {p.id: p for p in db.scalars(select(Product).where(Product.id.in_(pids)))}
    return [
        ListingRead(
            id=r.id,
            channel_id=r.channel_id,
            external_id=r.external_id,
            external_sku=r.external_sku,
            product_id=r.product_id,
            product_sku=products[r.product_id].sku,
            product_name=products[r.product_id].name,
            product_listing_count=int(counts.get(r.product_id, 0)),
        )
        for r in rows
    ]


@router.get("", response_model=list[ListingRead])
def list_listings(
    db: DB, org_id: OrgId, channel_id: uuid.UUID | None = None, limit: int = Query(500, le=2000)
):
    stmt = select(ChannelListing).where(ChannelListing.org_id == org_id)
    if channel_id:
        crud.assert_owned(db, Channel, org_id, channel_id)
        stmt = stmt.where(ChannelListing.channel_id == channel_id)
    rows = list(db.scalars(stmt.order_by(ChannelListing.external_id).limit(limit)).all())
    return _reads(db, org_id, rows)


@router.post("/match", response_model=list[MatchResult])
def match(db: DB, org_id: OrgId, body: MatchRequest):
    crud.assert_owned(db, Channel, org_id, body.channel_id)
    stmt = select(ChannelListing).where(
        ChannelListing.org_id == org_id, ChannelListing.channel_id == body.channel_id
    )
    if body.external_ids:
        stmt = stmt.where(ChannelListing.external_id.in_(body.external_ids))
    rows = list(db.scalars(stmt.order_by(ChannelListing.external_id)).all())
    reads = {r.id: r for r in _reads(db, org_id, rows)}
    candidates = list(db.scalars(select(Product).where(Product.org_id == org_id)).all())
    out: list[MatchResult] = []
    for listing in rows:
        if body.only_unmatched and reads[listing.id].product_listing_count > 1:
            continue
        pool = [p for p in candidates if p.id != listing.product_id]
        sugg = svc.suggest(db, org_id, listing, limit=body.limit, candidates=pool)
        out.append(
            MatchResult(
                listing=reads[listing.id],
                suggestions=[SuggestionRead(**s.__dict__) for s in sugg],
            )
        )
    return out


@router.post("/{listing_id}/override", response_model=OverrideResult)
def override(db: DB, ctx: Ctx, listing_id: uuid.UUID, body: OverrideRequest):
    listing = crud.get_scoped(db, ChannelListing, ctx.org_id, listing_id)
    crud.assert_owned(db, Product, ctx.org_id, body.product_id)
    before = {"product_id": str(listing.product_id)}
    try:
        result = svc.override(db, ctx.org_id, listing, body.product_id)
    except AssertionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "bad product") from exc
    audit.record(
        db,
        ctx,
        action="listing.override",
        entity="channel_listing",
        entity_id=listing.id,
        before=before,
        after={"product_id": str(body.product_id), **result},
    )
    db.commit()
    db.refresh(listing)
    return OverrideResult(listing=_reads(db, ctx.org_id, [listing])[0], **result)
