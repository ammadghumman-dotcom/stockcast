"""What-if: apply a draft promotion to the latest forecast and explode the delta through BOMs."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.forecast import covariates as cov
from app.forecast.engine import latest_successful_run
from app.models import BomLine, Forecast, Product, Promotion
from app.models.enums import PromotionScope, PromotionType


@dataclass
class DraftPromotion:
    name: str
    type: PromotionType
    start_date: date
    end_date: date
    discount_pct: Decimal | None = None
    spend_amount: Decimal | None = None
    channel_id: uuid.UUID | None = None
    scope: PromotionScope = PromotionScope.all
    category_id: uuid.UUID | None = None
    product_ids: list[uuid.UUID] | None = None


@dataclass
class ProductDelta:
    product_id: uuid.UUID
    sku: str
    base_units: float
    promo_units: float
    delta_units: float
    post_dip_units: float


@dataclass
class MaterialDelta:
    product_id: uuid.UUID
    sku: str
    unit: str
    delta_qty: float


@dataclass
class SimulationResult:
    run_id: uuid.UUID | None
    lift: float
    post_dip: float
    products: list[ProductDelta]
    materials: list[MaterialDelta]
    total_delta_units: float


def simulate(db: Session, org_id: uuid.UUID, draft: DraftPromotion) -> SimulationResult:
    run = latest_successful_run(db, org_id)
    if run is None:
        return SimulationResult(None, 1.0, 1.0, [], [], 0.0)
    coef, post_dip = cov.load_promo_model(db, org_id)
    cat_names = cov.category_name_map(db, org_id)

    products = {
        p.id: p
        for p in db.scalars(
            select(Product).where(Product.org_id == org_id, Product.is_active.is_(True))
        )
    }
    targets = [p for p in products.values() if _applies(draft, p)]
    if not targets:
        return SimulationResult(run.id, 1.0, post_dip, [], [], 0.0)

    window_end = draft.end_date + timedelta(days=cov.POST_PROMO_DAYS)
    rows = db.execute(
        select(Forecast.product_id, Forecast.date, Forecast.p50).where(
            Forecast.run_id == run.id,
            Forecast.product_id.in_([p.id for p in targets]),
            Forecast.date.between(draft.start_date, window_end),
        )
    ).all()
    by_product: dict[uuid.UUID, dict[date, float]] = defaultdict(dict)
    for pid, d, p50 in rows:
        by_product[pid][d] = float(p50)

    deltas: list[ProductDelta] = []
    for p in targets:
        fc = by_product.get(p.id, {})
        cat = cat_names.get(p.category_id) if p.category_id else None
        lift = cov.predict_lift(_as_promo(draft), coef, cat)
        base = sum(v for d, v in fc.items() if d <= draft.end_date)
        after = sum(v for d, v in fc.items() if d > draft.end_date)
        promo_units = base * lift
        dip_units = after * (post_dip - 1.0)  # negative: lost after the promo
        deltas.append(ProductDelta(p.id, p.sku, base, promo_units, promo_units - base, dip_units))

    # BOM explosion (multi-level) of the net incremental units
    net = {d.product_id: d.delta_units + d.post_dip_units for d in deltas}
    materials = _explode(db, org_id, net, products)
    lift_overall = (
        sum(d.promo_units for d in deltas) / sum(d.base_units for d in deltas)
        if sum(d.base_units for d in deltas) > 0
        else cov.predict_lift(_as_promo(draft), coef, None)
    )
    return SimulationResult(
        run.id,
        lift_overall,
        post_dip,
        deltas,
        materials,
        sum(d.delta_units + d.post_dip_units for d in deltas),
    )


def _applies(draft: DraftPromotion, p: Product) -> bool:
    if p.type.value == "raw_material":
        return False
    if draft.scope == PromotionScope.all:
        return True
    if draft.scope == PromotionScope.category:
        return draft.category_id is not None and p.category_id == draft.category_id
    return p.id in (draft.product_ids or [])


def _as_promo(d: DraftPromotion) -> Promotion:
    return Promotion(
        name=d.name,
        type=d.type,
        start_date=d.start_date,
        end_date=d.end_date,
        discount_pct=d.discount_pct,
        spend_amount=d.spend_amount,
        channel_id=d.channel_id,
        scope=d.scope,
        category_id=d.category_id,
        product_ids=[str(x) for x in d.product_ids] if d.product_ids else None,
    )


def _explode(
    db: Session, org_id: uuid.UUID, net_units: dict[uuid.UUID, float], products: dict
) -> list[MaterialDelta]:
    lines = db.scalars(select(BomLine).where(BomLine.org_id == org_id)).all()
    bom: dict[uuid.UUID, list[tuple[uuid.UUID, float]]] = defaultdict(list)
    for ln in lines:
        bom[ln.parent_product_id].append((ln.component_product_id, float(ln.qty_per_unit)))
    need: dict[uuid.UUID, float] = defaultdict(float)
    stack = list(net_units.items())
    depth = 0
    while stack and depth < 10:
        nxt = []
        for pid, qty in stack:
            for comp, per in bom.get(pid, []):
                need[comp] += qty * per
                if comp in bom:
                    nxt.append((comp, qty * per))
        stack, depth = nxt, depth + 1
    return [
        MaterialDelta(cid, products[cid].sku, products[cid].unit, q)
        for cid, q in need.items()
        if cid in products and abs(q) > 1e-9
    ]
