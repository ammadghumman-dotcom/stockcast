"""Run one forecast pass for an org: load series -> route/backtest/forecast -> persist."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.forecast.features import Series, load_series
from app.forecast.router import forecast_batch, wape
from app.models import Forecast, ForecastAccuracy, ForecastRun

DEFAULT_HORIZON = 90


def run_forecast(
    db: Session,
    run: ForecastRun,
    *,
    as_of: date | None = None,
    product_ids: list[uuid.UUID] | None = None,
) -> ForecastRun:
    as_of = as_of or (date.today() - timedelta(days=1))
    run.status, run.started_at, run.as_of = "running", datetime.now(UTC), as_of
    db.commit()
    try:
        series = load_series(db, run.org_id, as_of=as_of, product_ids=product_ids)
        run.skus_total = len(series)
        priors = _category_priors(series)
        scored = forecast_batch(series, run.horizon_days, category_prior=priors)

        # drop any rows from a previous attempt of this run (idempotent retry)
        db.execute(delete(Forecast).where(Forecast.run_id == run.id))
        db.execute(delete(ForecastAccuracy).where(ForecastAccuracy.run_id == run.id))

        fc_rows, acc_rows = [], []
        tot_abs_err = tot_abs_act = 0.0
        for s, sc in scored.items():
            dates = [as_of + timedelta(days=i + 1) for i in range(run.horizon_days)]
            for d, p10, p50, p90 in zip(
                dates, sc.bands.p10, sc.bands.p50, sc.bands.p90, strict=True
            ):
                fc_rows.append(
                    {
                        "run_id": run.id,
                        "org_id": run.org_id,
                        "product_id": s.product_id,
                        "date": d,
                        "p10": _dec(p10),
                        "p50": _dec(p50),
                        "p90": _dec(p90),
                        "model": sc.model,
                    }
                )
            acc_rows.append(
                {
                    "id": uuid.uuid4(),
                    "run_id": run.id,
                    "org_id": run.org_id,
                    "product_id": s.product_id,
                    "model": sc.model,
                    "history_days": s.history_days,
                    "zero_share": _dec(s.zero_share, 4),
                    "holdout_days": sc.holdout_days,
                    "mape": _dec(sc.mape, 4),
                    "wape": _dec(sc.wape, 4),
                    "wape_chronos": _dec(sc.wape_chronos, 4),
                    "wape_stats": _dec(sc.wape_stats, 4),
                }
            )
            if sc.wape is not None and sc.holdout_days:
                # reconstruct org-level WAPE from per-sku numbers weighted by actual volume
                actual_vol = float(np.nansum(s.y[-sc.holdout_days :]))
                tot_abs_err += sc.wape * actual_vol
                tot_abs_act += actual_vol
            if sc.model == "chronos":
                run.skus_chronos += 1
            elif sc.model == "croston":
                run.skus_croston += 1
            elif sc.model == "fallback":
                run.skus_fallback += 1

        for i in range(0, len(fc_rows), 5000):
            db.bulk_insert_mappings(Forecast, fc_rows[i : i + 5000])
        if acc_rows:
            db.bulk_insert_mappings(ForecastAccuracy, acc_rows)
        run.wape = _dec(tot_abs_err / tot_abs_act, 4) if tot_abs_act else None
        run.status, run.finished_at = "success", datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        run.status, run.error, run.finished_at = "failed", str(exc)[:2000], datetime.now(UTC)
        db.commit()
        raise
    return run


def latest_successful_run(db: Session, org_id: uuid.UUID) -> ForecastRun | None:
    return db.scalar(
        select(ForecastRun)
        .where(ForecastRun.org_id == org_id, ForecastRun.status == "success")
        .order_by(ForecastRun.finished_at.desc())
        .limit(1)
    )


def _category_priors(series: list[Series]) -> dict:
    """Median daily demand per category from SKUs that have real history (for cold starts)."""
    by_cat: dict = {}
    for s in series:
        if s.history_days >= 60 and s.category_id is not None:
            by_cat.setdefault(s.category_id, []).append(float(np.nanmean(s.y[-90:])))
    return {c: float(np.median(v)) for c, v in by_cat.items()}


def _dec(x, places: int = 4) -> Decimal | None:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return Decimal(f"{float(x):.{places}f}")


__all__ = ["DEFAULT_HORIZON", "latest_successful_run", "run_forecast", "wape"]
