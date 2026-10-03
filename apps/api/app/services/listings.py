"""SKU mapping: suggest which catalog product a channel listing belongs to, and re-point it.

Connectors auto-create a product for every unknown channel SKU, so "the same candle on Amazon
and Shopify" can land as two products. `suggest()` ranks other products by fuzzy similarity of
SKU and name (rapidfuzz); `override()` moves the listing — and its channel's sales/stock rows —
onto the chosen product and removes the now-empty auto-created one. Many listings may point at
one product; sales are summed per product across channels downstream.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from rapidfuzz import fuzz, process
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import BomLine, ChannelListing, InventoryLevel, Product, SalesDaily

MIN_SCORE = 40


@dataclass
class Suggestion:
    product_id: uuid.UUID
    sku: str
    name: str
    score: float
    reason: str


def _norm(s: str | None) -> str:
    return (s or "").lower().replace("_", "-").replace(" ", "")


def score_pair(
    ext_sku: str | None, listing_name: str, cand_sku: str, cand_name: str
) -> tuple[float, str]:
    """0..100 similarity + which signal won. SKU matches dominate; names break ties."""
    sku_score = fuzz.ratio(_norm(ext_sku), _norm(cand_sku)) if ext_sku else 0.0
    contained = bool(ext_sku) and (
        _norm(ext_sku) in _norm(cand_sku) or _norm(cand_sku) in _norm(ext_sku)
    )
    if contained and min(len(_norm(ext_sku)), len(_norm(cand_sku))) >= 4:
        sku_score = max(sku_score, 90.0)
    name_score = fuzz.token_set_ratio(listing_name.lower(), cand_name.lower())
    if sku_score >= name_score:
        return sku_score, "sku"
    return 0.6 * name_score + 0.4 * sku_score, "name"


def suggest(
    db: Session,
    org_id: uuid.UUID,
    listing: ChannelListing,
    *,
    limit: int = 5,
    candidates: list[Product] | None = None,
) -> list[Suggestion]:
    current = db.get(Product, listing.product_id)
    assert current is not None
    if candidates is None:
        candidates = list(
            db.scalars(
                select(Product).where(Product.org_id == org_id, Product.id != current.id)
            ).all()
        )
    query_name = current.name
    ext_sku = listing.external_sku or current.sku
    # rapidfuzz pre-filter on name keeps big catalogs fast, then rescore the top slice
    names = {str(p.id): p.name for p in candidates}
    top = process.extract(query_name, names, scorer=fuzz.token_set_ratio, limit=max(limit * 5, 25))
    by_id = {str(p.id): p for p in candidates}
    pool = {pid for _, _, pid in top}
    for p in candidates:  # also anything whose SKU looks alike, regardless of name
        if ext_sku and fuzz.ratio(_norm(ext_sku), _norm(p.sku)) >= 70:
            pool.add(str(p.id))
    scored: list[Suggestion] = []
    for pid in pool:
        p = by_id[pid]
        s, reason = score_pair(ext_sku, query_name, p.sku, p.name)
        if s >= MIN_SCORE:
            scored.append(Suggestion(p.id, p.sku, p.name, round(s, 1), reason))
    scored.sort(key=lambda x: -x.score)
    return scored[:limit]


def override(
    db: Session, org_id: uuid.UUID, listing: ChannelListing, product_id: uuid.UUID
) -> dict:
    """Point `listing` at `product_id`; migrate the channel's rows; drop an orphaned product."""
    old_id = listing.product_id
    if old_id == product_id:
        return {"moved_sales_rows": 0, "deleted_product": False}
    target = db.get(Product, product_id)
    assert target is not None and target.org_id == org_id

    # sales: SET semantics -> add onto any existing (date, target, channel) row
    rows = db.execute(
        select(SalesDaily.date, SalesDaily.units, SalesDaily.revenue, SalesDaily.region_id).where(
            SalesDaily.product_id == old_id, SalesDaily.channel_id == listing.channel_id
        )
    ).all()
    moved = 0
    for d, units, revenue, region_id in rows:
        stmt = pg_insert(SalesDaily).values(
            date=d,
            product_id=product_id,
            channel_id=listing.channel_id,
            region_id=region_id,
            org_id=org_id,
            units=units,
            revenue=revenue,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["date", "product_id", "channel_id"],
            set_={
                "units": SalesDaily.units + stmt.excluded.units,
                "revenue": SalesDaily.revenue + stmt.excluded.revenue,
            },
        )
        db.execute(stmt)
        moved += 1
    db.execute(
        delete(SalesDaily).where(
            SalesDaily.product_id == old_id, SalesDaily.channel_id == listing.channel_id
        )
    )
    # inventory snapshots of the orphan move too (summed per location)
    for lvl in db.scalars(select(InventoryLevel).where(InventoryLevel.product_id == old_id)):
        existing = db.scalar(
            select(InventoryLevel).where(
                InventoryLevel.product_id == product_id,
                InventoryLevel.location_id == lvl.location_id,
            )
        )
        if existing:
            existing.on_hand = Decimal(existing.on_hand) + Decimal(lvl.on_hand)
            existing.inbound = Decimal(existing.inbound) + Decimal(lvl.inbound)
            db.delete(lvl)
        else:
            lvl.product_id = product_id

    listing.product_id = product_id
    db.flush()

    deleted = False
    still_used = (
        db.scalar(
            select(func.count())
            .select_from(ChannelListing)
            .where(ChannelListing.product_id == old_id)
        )
        or db.scalar(
            select(func.count()).select_from(SalesDaily).where(SalesDaily.product_id == old_id)
        )
        or db.scalar(
            select(func.count())
            .select_from(BomLine)
            .where((BomLine.parent_product_id == old_id) | (BomLine.component_product_id == old_id))
        )
    )
    if not still_used:
        db.execute(delete(Product).where(Product.id == old_id, Product.org_id == org_id))
        deleted = True
    else:
        db.execute(update(Product).where(Product.id == old_id).values(is_active=False))
    db.flush()
    return {"moved_sales_rows": moved, "deleted_product": deleted}
