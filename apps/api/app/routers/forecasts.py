import uuid
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import func, select

from app.deps import DB, OrgId
from app.forecast.channels import load_channel_mix
from app.forecast.engine import latest_successful_run
from app.forecast.simulate import DraftPromotion, simulate
from app.forecast.tasks import enqueue_forecast
from app.models import Forecast, ForecastAccuracy, ForecastRun, Product
from app.ratelimit import heavy
from app.schemas.calendar import SimulateRequest, SimulateResponse
from app.schemas.forecast import (
    AccuracyRow,
    AccuracySummary,
    ChannelShare,
    ForecastPoint,
    ForecastRunRead,
    ProductForecast,
)
from app.services import crud

router = APIRouter(tags=["forecasts"])


@router.post("/forecast-runs", response_model=ForecastRunRead, status_code=202)
@heavy
def trigger_forecast(
    request: Request, db: DB, org_id: OrgId, horizon: int = Query(90, ge=7, le=365)
):
    return enqueue_forecast(db, org_id, trigger="manual", horizon=horizon)


@router.get("/forecast-runs", response_model=list[ForecastRunRead])
def list_runs(db: DB, org_id: OrgId, limit: int = Query(20, le=100)):
    return list(crud.list_scoped(db, ForecastRun, org_id, limit=limit))


@router.get("/forecasts", response_model=ProductForecast)
def get_forecast(
    db: DB,
    org_id: OrgId,
    product_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
    days: int = Query(90, ge=1, le=365),
):
    crud.assert_owned(db, Product, org_id, product_id)
    run = (
        crud.get_scoped(db, ForecastRun, org_id, run_id)
        if run_id
        else latest_successful_run(db, org_id)
    )
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no successful forecast run yet")
    rows = db.scalars(
        select(Forecast)
        .where(Forecast.run_id == run.id, Forecast.product_id == product_id)
        .order_by(Forecast.date)
        .limit(days)
    ).all()
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "product has no forecast in this run")
    points = [ForecastPoint.model_validate(r) for r in rows]
    t30 = sum((p.p50 for p in points[:30]), Decimal(0))
    t90 = sum((p.p50 for p in points[:90]), Decimal(0))
    mix = load_channel_mix(db, org_id, run.id, [product_id]).get(product_id, [])
    return ProductForecast(
        product_id=product_id,
        run_id=run.id,
        as_of=run.as_of,
        model=rows[0].model,
        points=points,
        total_p50_30d=t30,
        total_p50_90d=t90,
        channels=[
            ChannelShare(
                **m,
                p50_30d=(t30 * m["share"]).quantize(Decimal("0.01")),
                p50_90d=(t90 * m["share"]).quantize(Decimal("0.01")),
            )
            for m in mix
        ],
    )


@router.get("/forecast-accuracy", response_model=AccuracySummary)
def accuracy(
    db: DB, org_id: OrgId, run_id: uuid.UUID | None = None, worst: int = Query(10, le=100)
):
    run = (
        crud.get_scoped(db, ForecastRun, org_id, run_id)
        if run_id
        else latest_successful_run(db, org_id)
    )
    if run is None:
        return AccuracySummary(
            run_id=None, as_of=None, skus=0, wape=None, median_sku_wape=None, by_model={}, worst=[]
        )
    base = select(ForecastAccuracy).where(ForecastAccuracy.run_id == run.id)
    by_model = dict(
        db.execute(
            select(ForecastAccuracy.model, func.count())
            .where(ForecastAccuracy.run_id == run.id)
            .group_by(ForecastAccuracy.model)
        ).all()
    )
    median = db.scalar(
        select(func.percentile_cont(0.5).within_group(ForecastAccuracy.wape)).where(
            ForecastAccuracy.run_id == run.id, ForecastAccuracy.wape.is_not(None)
        )
    )
    worst_rows = db.scalars(
        base.where(ForecastAccuracy.wape.is_not(None))
        .order_by(ForecastAccuracy.wape.desc())
        .limit(worst)
    ).all()
    return AccuracySummary(
        run_id=run.id,
        as_of=run.as_of,
        skus=run.skus_total,
        wape=run.wape,
        median_sku_wape=Decimal(f"{median:.4f}") if median is not None else None,
        by_model=by_model,
        worst=[AccuracyRow.model_validate(r) for r in worst_rows],
    )


@router.post("/forecasts/simulate", response_model=SimulateResponse)
@heavy
def simulate_promotion(request: Request, db: DB, org_id: OrgId, body: SimulateRequest):
    """What-if: apply a draft promotion to the latest forecast; returns unit delta per product
    (incl. the post-promo dip) and the raw-material impact via BOM explosion."""
    from app.models import Channel, ProductCategory

    if body.channel_id:
        crud.assert_owned(db, Channel, org_id, body.channel_id)
    if body.category_id:
        crud.assert_owned(db, ProductCategory, org_id, body.category_id)
    res = simulate(db, org_id, DraftPromotion(**body.model_dump()))
    return SimulateResponse(
        run_id=res.run_id,
        lift=res.lift,
        post_dip=res.post_dip,
        total_delta_units=res.total_delta_units,
        products=[p.__dict__ for p in res.products],
        materials=[m.__dict__ for m in res.materials],
    )
