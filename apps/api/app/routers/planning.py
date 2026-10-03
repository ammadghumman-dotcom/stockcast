import uuid

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.deps import DB, OrgId
from app.models import PlanningRun, Product, Recommendation, Supplier
from app.planning.engine import get_settings, latest_planning_run
from app.planning.tasks import enqueue_planning
from app.schemas.planning import (
    PlanningRunRead,
    PlanningSettingsRead,
    PlanningSettingsUpdate,
    ProductPlanningUpdate,
    RecommendationRead,
)
from app.services import crud

router = APIRouter(tags=["planning"])


@router.get("/planning-settings", response_model=PlanningSettingsRead)
def read_settings(db: DB, org_id: OrgId):
    s = get_settings(db, org_id)
    db.commit()
    return s


@router.patch("/planning-settings", response_model=PlanningSettingsRead)
def update_settings(db: DB, org_id: OrgId, body: PlanningSettingsUpdate):
    s = get_settings(db, org_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    db.commit()
    db.refresh(s)
    return s


@router.patch("/products/{product_id}/planning", response_model=dict)
def update_product_planning(
    db: DB, org_id: OrgId, product_id: uuid.UUID, body: ProductPlanningUpdate
):
    if body.preferred_supplier_id:
        crud.assert_owned(db, Supplier, org_id, body.preferred_supplier_id)
    p = crud.update_scoped(db, Product, org_id, product_id, body)
    return {
        "product_id": str(p.id),
        "service_level": p.service_level,
        "target_cover_days": p.target_cover_days,
        "lead_time_days": p.lead_time_days,
        "preferred_supplier_id": p.preferred_supplier_id,
    }


@router.post("/planning-runs", response_model=PlanningRunRead, status_code=202)
def trigger_planning(db: DB, org_id: OrgId):
    return enqueue_planning(db, org_id, trigger="manual")


@router.get("/planning-runs", response_model=list[PlanningRunRead])
def list_planning_runs(db: DB, org_id: OrgId, limit: int = Query(20, le=100)):
    return list(crud.list_scoped(db, PlanningRun, org_id, limit=limit))


@router.get("/recommendations", response_model=list[RecommendationRead])
def list_recommendations(
    db: DB,
    org_id: OrgId,
    run_id: uuid.UUID | None = None,
    action: str | None = Query(None, pattern="^(reorder|produce|none)$"),
    health: str | None = Query(None, pattern="^(healthy|at_risk|stockout|overstock)$"),
    product_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    limit: int = Query(500, le=5000),
):
    run = (
        crud.get_scoped(db, PlanningRun, org_id, run_id)
        if run_id
        else latest_planning_run(db, org_id)
    )
    if run is None:
        return []
    q = (
        select(Recommendation, Product.sku, Product.name, Supplier.name)
        .join(Product, Product.id == Recommendation.product_id)
        .outerjoin(Supplier, Supplier.id == Recommendation.supplier_id)
        .where(Recommendation.org_id == org_id, Recommendation.run_id == run.id)
    )
    if action:
        q = q.where(Recommendation.action == action)
    if health:
        q = q.where(Recommendation.health == health)
    if product_id:
        q = q.where(Recommendation.product_id == product_id)
    if supplier_id:
        q = q.where(Recommendation.supplier_id == supplier_id)
    q = q.order_by(
        Recommendation.order_by_date.asc().nulls_last(), Recommendation.cash_tied.desc()
    ).limit(limit)
    out = []
    for rec, sku, name, sname in db.execute(q):
        r = RecommendationRead.model_validate(rec)
        r.sku, r.product_name, r.supplier_name = sku, name, sname
        out.append(r)
    return out


@router.get("/recommendations/{rec_id}", response_model=RecommendationRead)
def get_recommendation(db: DB, org_id: OrgId, rec_id: uuid.UUID):
    rec = crud.get_scoped(db, Recommendation, org_id, rec_id)
    r = RecommendationRead.model_validate(rec)
    p = db.get(Product, rec.product_id)
    r.sku, r.product_name = (p.sku, p.name) if p else (None, None)
    if rec.supplier_id:
        s = db.get(Supplier, rec.supplier_id)
        r.supplier_name = s.name if s else None
    return r
