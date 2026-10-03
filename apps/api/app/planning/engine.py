"""Planning engine: latest forecast + stock + open POs + BOM -> recommendations per product."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.forecast.engine import latest_successful_run
from app.models import (
    BomLine,
    Forecast,
    InventoryLevel,
    PlanningRun,
    PlanningSettings,
    POStatus,
    Product,
    ProductType,
    PurchaseOrder,
    PurchaseOrderLine,
    Recommendation,
    Supplier,
    SupplierProduct,
)
from app.planning import math as pm
from app.planning.bom import Bom, explode_demand, made_in_house


@dataclass
class SupplierPick:
    supplier_id: uuid.UUID | None
    name: str | None
    lead_time_days: int
    moq: float
    pack_size: float
    price: float | None


def get_settings(db: Session, org_id: uuid.UUID) -> PlanningSettings:
    s = db.scalar(select(PlanningSettings).where(PlanningSettings.org_id == org_id))
    if s is None:
        s = PlanningSettings(org_id=org_id)
        db.add(s)
        db.flush()
    return s


def run_planning(db: Session, run: PlanningRun, *, as_of: date | None = None) -> PlanningRun:
    run.status, run.started_at = "running", datetime.now(UTC)
    db.commit()
    try:
        settings = get_settings(db, run.org_id)
        frun = latest_successful_run(db, run.org_id)
        if frun is None:
            raise RuntimeError("no successful forecast run yet; run a forecast first")
        run.forecast_run_id = frun.id
        as_of = as_of or frun.as_of or date.today()
        run.as_of = as_of
        H = settings.horizon_days

        products = {
            p.id: p
            for p in db.scalars(
                select(Product).where(Product.org_id == run.org_id, Product.is_active.is_(True))
            )
        }
        bom = _load_bom(db, run.org_id)
        fc = _load_forecast(db, frun.id, as_of, H)  # product -> (p50, p90, factor, event)
        stock = _load_stock(db, run.org_id)
        inbound = _load_inbound(db, run.org_id, as_of, H)
        suppliers = _load_suppliers(db, run.org_id)

        # independent demand (forecast) + derived demand (BOM explosion of finished goods)
        indep = {pid: v[0] for pid, v in fc.items() if pid in products}
        derived = explode_demand(bom, indep)
        demand_p50: dict[uuid.UUID, np.ndarray] = {}
        demand_p90: dict[uuid.UUID, np.ndarray] = {}
        for pid in products:
            d50 = np.zeros(H)
            d90 = np.zeros(H)
            if pid in fc:
                d50 = d50 + fc[pid][0]
                d90 = d90 + fc[pid][1]
            if pid in derived:
                d50 = d50 + derived[pid]
                # derived uncertainty: scale parents' relative band onto the derived demand
                d90 = d90 + derived[pid] * _rel_band(fc, bom, pid)
            demand_p50[pid], demand_p90[pid] = d50, np.maximum(d90, d50)

        # derived-demand products (raw materials, components) inherit covariate context from
        # the finished goods that consume them: per day, the parent with the largest factor
        for pid in products:
            if pid in fc or pid not in derived:
                continue
            factor = np.ones(H)
            events: list[str | None] = [None] * H
            for parent, lines in bom.items():
                if parent in fc and any(c == pid for c, _ in lines):
                    pf, pe = fc[parent][2], fc[parent][3]
                    better = pf > factor
                    factor = np.where(better, pf, factor)
                    events = [pe[i] if better[i] else events[i] for i in range(H)]
            fc[pid] = (np.zeros(H), np.zeros(H), factor, events)

        db.execute(delete(Recommendation).where(Recommendation.run_id == run.id))
        rows = []
        health_counts: dict[str, int] = defaultdict(int)
        cash: dict[str, float] = defaultdict(float)
        for pid, p in products.items():
            d50, d90 = demand_p50[pid], demand_p90[pid]
            if not d50.any() and float(stock.get(pid, 0.0)) <= 0:
                continue  # nothing sells, nothing stocked: skip
            rec = _plan_product(
                p,
                d50,
                d90,
                stock.get(pid, 0.0),
                inbound.get(pid, {}),
                bom,
                suppliers,
                settings,
                as_of,
                fc.get(pid),
                run,
            )
            rows.append(rec)
            health_counts[rec["health"]] += 1
            cash[rec["health"]] += float(rec["cash_tied"])
            if rec["action"] == "reorder":
                run.n_reorder += 1
            elif rec["action"] == "produce":
                run.n_produce += 1
        if rows:
            db.bulk_insert_mappings(Recommendation, rows)
        run.products_total = len(rows)
        run.health_counts = dict(health_counts)
        run.cash_by_health = {k: round(v, 2) for k, v in cash.items()}
        run.status, run.finished_at = "success", datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        run.status, run.error, run.finished_at = "failed", str(exc)[:2000], datetime.now(UTC)
        db.commit()
        raise
    return run


# --------------------------------------------------------------------------- per product
def _plan_product(p, d50, d90, on_hand, inbound, bom, suppliers, settings, as_of, fc_row, run):
    in_house = made_in_house(bom, p.id)
    pick = _pick_supplier(p, suppliers, settings) if not in_house else None
    lead = (
        p.lead_time_days
        if p.lead_time_days is not None
        else (settings.production_lead_time_days if in_house else pick.lead_time_days)  # type: ignore[union-attr]
    )
    sl = float(p.service_level) if p.service_level is not None else float(settings.service_level)
    cover = p.target_cover_days if p.target_cover_days is not None else settings.target_cover_days

    proj = pm.project_stock(on_hand, d50, inbound)
    plan = pm.reorder(
        on_hand,
        d50,
        d90,
        inbound=inbound,
        lead_time_days=lead,
        service_level=sl,
        target_cover_days=cover,
        moq=pick.moq if pick else 1.0,
        pack_size=pick.pack_size if pick else 1.0,
    )
    health = pm.health_status(
        on_hand=on_hand,
        stockout_day=proj.stockout_day,
        lead_time_days=lead,
        at_risk_buffer_days=settings.at_risk_buffer_days,
        days_of_cover=proj.days_of_cover,
        overstock_days=settings.overstock_days,
        daily_demand=plan.daily_demand,
    )
    action = "none"
    if plan.qty > 0 and plan.order_day is not None:
        action = "produce" if in_house else "reorder"
    order_by = (
        as_of + timedelta(days=max(plan.order_day, 0)) if plan.order_day is not None else None
    )
    expected = order_by + timedelta(days=lead) if order_by else None

    event, uplift = _dominant_event(fc_row, plan.order_day, lead, cover) if fc_row else (None, None)
    reason = _reason(
        p,
        action,
        plan,
        order_by,
        expected,
        lead,
        cover,
        pick,
        proj.stockout_date(as_of),
        event,
        uplift,
        in_house,
    )
    unit_cost = float(p.unit_cost or 0)
    return {
        "id": uuid.uuid4(),
        "org_id": run.org_id,
        "run_id": run.id,
        "product_id": p.id,
        "action": action,
        "health": health,
        "qty": _dec(plan.qty),
        "order_by_date": order_by,
        "expected_date": expected,
        "supplier_id": pick.supplier_id if pick else None,
        "reason": reason,
        "on_hand": _dec(on_hand),
        "inbound": _dec(sum(inbound.values())),
        "daily_demand": _dec(plan.daily_demand),
        "lead_time_days": lead,
        "safety_stock": _dec(plan.safety_stock),
        "reorder_point": _dec(plan.reorder_point),
        "stockout_date": proj.stockout_date(as_of),
        "days_of_cover": proj.days_of_cover,
        "cash_tied": Decimal(f"{max(on_hand, 0) * unit_cost:.2f}"),
        "event": event,
        "uplift_pct": Decimal(f"{uplift:.2f}") if uplift is not None else None,
    }


def _pick_supplier(p: Product, suppliers: dict, settings: PlanningSettings) -> SupplierPick:
    """Preferred supplier if set, else the cheapest that lists the product, else no supplier."""
    offers: list[tuple[SupplierProduct, Supplier]] = suppliers["offers"].get(p.id, [])
    chosen = None
    if p.preferred_supplier_id:
        chosen = next((o for o in offers if o[1].id == p.preferred_supplier_id), None)
        if chosen is None and p.preferred_supplier_id in suppliers["by_id"]:
            s = suppliers["by_id"][p.preferred_supplier_id]
            return SupplierPick(s.id, s.name, s.lead_time_days, float(s.moq), 1.0, None)
    if chosen is None and offers:
        chosen = min(offers, key=lambda o: float(o[0].price))
    if chosen is None:
        return SupplierPick(None, None, settings.default_lead_time_days, 1.0, 1.0, None)
    sp, s = chosen
    return SupplierPick(
        s.id,
        s.name,
        sp.lead_time_days if sp.lead_time_days is not None else s.lead_time_days,
        float(s.moq),
        float(sp.pack_size or 1),
        float(sp.price),
    )


def _dominant_event(fc_row, order_day, lead, cover):
    """Strongest covariate event inside the lead-time + cover window after the order date."""
    factors, events = fc_row[2], fc_row[3]
    start = max(order_day or 0, 0)
    end = min(len(factors), start + lead + cover)
    best_i = None
    for i in range(start, end):
        if events[i] and factors[i] > 1.0 and (best_i is None or factors[i] > factors[best_i]):
            best_i = i
    if best_i is None:
        return None, None
    return events[best_i], (float(factors[best_i]) - 1.0) * 100.0


def _reason(
    p, action, plan, order_by, expected, lead, cover, pick, stockout, event, uplift, in_house
):
    if action == "none":
        if plan.daily_demand <= 0:
            return "No forecast demand."
        return (
            f"Covered: {int(plan.daily_demand)}/day demand, stock lasts past the planning horizon."
        )
    verb = "Produce" if in_house else "Reorder"
    bits = [
        f"{verb} {int(plan.qty):,} {p.unit if p.unit != 'unit' else 'units'} by {order_by:%b %d}"
    ]
    if expected:
        bits.append(f"(arrives {expected:%b %d}, {lead}d lead)")
    if stockout:
        bits.append(f"— stock runs out {stockout:%b %d}")
    bits.append(
        f"— covers {cover} days at {plan.daily_demand:.1f}/day + {int(plan.safety_stock)} safety"
    )
    if pick and pick.supplier_id:
        bits.append(f"from {pick.name}")
        if pick.moq > 1 or pick.pack_size > 1:
            bits.append(f"(MOQ {int(pick.moq):,}, pack {int(pick.pack_size):,})")
    elif not in_house:
        bits.append("— no supplier on file")
    if event and uplift and uplift > 5:
        bits.append(f"; {event} +{uplift:.0f}% in window")
    return " ".join(bits).replace(" —", " —").replace("  ", " ")


def _rel_band(fc, bom, comp_id) -> float:
    """Average relative (p90/p50) band of the parents that consume this component."""
    ratios = []
    for parent, lines in bom.items():
        if parent in fc and any(c == comp_id for c, _ in lines):
            p50, p90 = fc[parent][0], fc[parent][1]
            m = p50.sum()
            if m > 0:
                ratios.append(float(p90.sum() / m))
    # cap: a near-zero parent p50 would otherwise make the derived band (and safety stock) explode
    return float(np.clip(np.mean(ratios), 1.0, 3.0)) if ratios else 1.0


# --------------------------------------------------------------------------- loaders
def _load_bom(db: Session, org_id: uuid.UUID) -> Bom:
    bom: Bom = defaultdict(list)
    for ln in db.scalars(select(BomLine).where(BomLine.org_id == org_id)):
        bom[ln.parent_product_id].append((ln.component_product_id, float(ln.qty_per_unit)))
    return dict(bom)


def _load_forecast(db: Session, run_id: uuid.UUID, as_of: date, H: int) -> dict:
    out: dict[uuid.UUID, tuple] = {}
    rows = db.execute(
        select(
            Forecast.product_id,
            Forecast.date,
            Forecast.p50,
            Forecast.p90,
            Forecast.factor,
            Forecast.event,
        )
        .where(
            Forecast.run_id == run_id,
            Forecast.date > as_of,
            Forecast.date <= as_of + timedelta(days=H),
        )
        .order_by(Forecast.product_id, Forecast.date)
    ).all()
    by_pid: dict[uuid.UUID, list] = defaultdict(list)
    for r in rows:
        by_pid[r[0]].append(r)
    for pid, rs in by_pid.items():
        p50 = np.zeros(H)
        p90 = np.zeros(H)
        factor = np.ones(H)
        events: list[str | None] = [None] * H
        for _, d, a, b, f, e in rs:
            i = (d - as_of).days - 1
            if 0 <= i < H:
                p50[i], p90[i], factor[i], events[i] = float(a), float(b), float(f), e
        out[pid] = (p50, p90, factor, events)
    return out


def _load_stock(db: Session, org_id: uuid.UUID) -> dict[uuid.UUID, float]:
    return {
        pid: float(q or 0)
        for pid, q in db.execute(
            select(InventoryLevel.product_id, func.sum(InventoryLevel.on_hand))
            .where(InventoryLevel.org_id == org_id)
            .group_by(InventoryLevel.product_id)
        )
    }


def _load_inbound(
    db: Session, org_id: uuid.UUID, as_of: date, H: int
) -> dict[uuid.UUID, dict[int, float]]:
    """Open (sent) PO lines -> {product: {day_index: qty remaining}}. No date = assume tomorrow."""
    out: dict[uuid.UUID, dict[int, float]] = defaultdict(dict)
    rows = db.execute(
        select(
            PurchaseOrderLine.product_id,
            PurchaseOrderLine.qty,
            PurchaseOrderLine.received_qty,
            PurchaseOrder.expected_date,
        )
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(PurchaseOrder.org_id == org_id, PurchaseOrder.status == POStatus.sent)
    ).all()
    for pid, qty, recv, exp in rows:
        remaining = float(qty) - float(recv or 0)
        if remaining <= 0:
            continue
        day = max((exp - as_of).days - 1, 0) if exp else 0
        if day < H:
            out[pid][day] = out[pid].get(day, 0.0) + remaining
    return out


def _load_suppliers(db: Session, org_id: uuid.UUID) -> dict:
    by_id = {s.id: s for s in db.scalars(select(Supplier).where(Supplier.org_id == org_id))}
    offers: dict[uuid.UUID, list] = defaultdict(list)
    for sp in db.scalars(select(SupplierProduct).where(SupplierProduct.org_id == org_id)):
        if sp.supplier_id in by_id:
            offers[sp.product_id].append((sp, by_id[sp.supplier_id]))
    return {"by_id": by_id, "offers": offers}


def latest_planning_run(db: Session, org_id: uuid.UUID) -> PlanningRun | None:
    return db.scalar(
        select(PlanningRun)
        .where(PlanningRun.org_id == org_id, PlanningRun.status == "success")
        .order_by(PlanningRun.finished_at.desc())
        .limit(1)
    )


def _dec(x: float, places: int = 4) -> Decimal:
    return Decimal(f"{float(x):.{places}f}")


__all__ = ["ProductType", "get_settings", "latest_planning_run", "run_planning"]
