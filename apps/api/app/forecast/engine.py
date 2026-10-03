"""Run one forecast pass for an org: load -> covariates -> route/backtest/forecast -> persist."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.forecast import covariates as cov
from app.forecast.channels import compute_channel_shares
from app.forecast.features import Series, load_series
from app.forecast.models import Bands
from app.forecast.router import forecast_batch, wape
from app.models import Forecast, ForecastAccuracy, ForecastRun, Product

DEFAULT_HORIZON = 90
LOOKBACK_DAYS = 730


def run_forecast(
    db: Session,
    run: ForecastRun,
    *,
    as_of: date | None = None,
    product_ids: list[uuid.UUID] | None = None,
    use_covariates: bool = True,
) -> ForecastRun:
    as_of = as_of or (date.today() - timedelta(days=1))
    run.status, run.started_at, run.as_of = "running", datetime.now(UTC), as_of
    db.commit()
    try:
        series = load_series(
            db, run.org_id, as_of=as_of, lookback_days=LOOKBACK_DAYS, product_ids=product_ids
        )
        run.skus_total = len(series)
        priors = _category_priors(series)
        H = run.horizon_days

        # ---- covariates (learned leak-free: only from history before the backtest holdout)
        factors: dict[uuid.UUID, cov.Factors] = {}
        if use_covariates and series:
            factors = _learn_and_build(db, run.org_id, series, as_of, H)

        # ---- base model on de-seasonalised history
        adj_series = [_divide(s, factors) for s in series]
        scored = forecast_batch(adj_series, H, category_prior=priors)
        # backtest without covariates too, so improvement is measurable
        scored_base = forecast_batch(series, H, category_prior=priors) if factors else scored

        db.execute(delete(Forecast).where(Forecast.run_id == run.id))
        db.execute(delete(ForecastAccuracy).where(ForecastAccuracy.run_id == run.id))

        rescored = _rescore_all(series, adj_series, scored, factors) if factors else {}
        fc_rows, acc_rows = [], []
        err = act = err_base = 0.0
        for s_adj, s_raw, sb in zip(adj_series, series, scored_base, strict=True):
            sc = scored[s_adj]
            f = factors.get(s_raw.product_id)
            hist_f, fut_f, fut_prior, fut_ev = (
                f.split(as_of) if f else (None, np.ones(H), np.zeros(H, bool), [None] * H)
            )
            bands = _multiply(sc.bands, fut_f, fut_prior)

            # re-score the adjusted model on the raw holdout (apples to apples with base)
            w_adj, m_adj = rescored.get(s_raw.product_id, (sc.wape, sc.mape))
            dates = [as_of + timedelta(days=i + 1) for i in range(H)]
            for i, d in enumerate(dates):
                fc_rows.append(
                    {
                        "run_id": run.id,
                        "org_id": run.org_id,
                        "product_id": s_raw.product_id,
                        "date": d,
                        "p10": _dec(bands.p10[i]),
                        "p50": _dec(bands.p50[i]),
                        "p90": _dec(bands.p90[i]),
                        "model": sc.model,
                        "factor": _dec(fut_f[i]),
                        "event": fut_ev[i],
                    }
                )
            acc_rows.append(
                {
                    "id": uuid.uuid4(),
                    "run_id": run.id,
                    "org_id": run.org_id,
                    "product_id": s_raw.product_id,
                    "model": sc.model,
                    "history_days": s_raw.history_days,
                    "zero_share": _dec(s_raw.zero_share, 4),
                    "holdout_days": sc.holdout_days,
                    "mape": _dec(m_adj, 4),
                    "wape": _dec(w_adj, 4),
                    "wape_chronos": _dec(sc.wape_chronos, 4),
                    "wape_stats": _dec(sc.wape_stats, 4),
                }
            )
            if sc.holdout_days:
                vol = float(np.nansum(s_raw.y[-sc.holdout_days :]))
                if w_adj is not None:
                    err += w_adj * vol
                    act += vol
                if scored_base[sb].wape is not None:
                    err_base += scored_base[sb].wape * vol
            _count(run, sc.model)

        for i in range(0, len(fc_rows), 5000):
            db.bulk_insert_mappings(Forecast, fc_rows[i : i + 5000])
        if acc_rows:
            db.bulk_insert_mappings(ForecastAccuracy, acc_rows)
        compute_channel_shares(db, run.org_id, run.id, as_of, product_ids=product_ids)
        run.wape = _dec(err / act, 4) if act else None
        run.wape_base = _dec(err_base / act, 4) if act and factors else run.wape
        run.status, run.finished_at = "success", datetime.now(UTC)
        db.commit()
    except Exception as exc:
        db.rollback()
        run.status, run.error, run.finished_at = "failed", str(exc)[:2000], datetime.now(UTC)
        db.commit()
        raise
    return run


# --------------------------------------------------------------------------- covariates
def _learn_and_build(
    db: Session, org_id: uuid.UUID, series: list[Series], as_of: date, horizon: int
) -> dict[uuid.UUID, cov.Factors]:
    from app.forecast.router import HOLDOUT_DAYS

    hist_start = min(s.dates[0].date() for s in series)
    end = as_of + timedelta(days=horizon)
    events = cov.load_events(db, org_id, hist_start, end)
    promotions = cov.load_promotions(db, org_id, hist_start, end)
    shares = cov.load_region_shares(db, org_id, as_of)
    cat_names = cov.category_name_map(db, org_id)
    cutoff = as_of - timedelta(days=HOLDOUT_DAYS)  # nothing in the holdout is used to learn

    learned = cov.learn_holiday_uplifts(series, events, region_shares=shares, cutoff=cutoff)
    cov.persist_uplifts(
        db,
        org_id,
        learned,
        cat_ids={s.category_id for s in series if s.category_id},
        regions=cov.org_regions(db, org_id),
        event_names={e.name for e in events},
        category_names=cat_names,
    )
    uplifts = cov.load_uplifts(db, org_id)

    measured = cov.measure_promotions(series, promotions, cutoff=cutoff)
    for p in promotions:
        if p.id in measured:
            lift, dip, base = measured[p.id]
            p.observed_lift, p.observed_post_dip, p.baseline_units = (
                Decimal(f"{lift:.4f}"),
                Decimal(f"{dip:.4f}"),
                Decimal(f"{base:.4f}"),
            )
    fit = cov.fit_promo_model(promotions, cat_names)
    if fit:
        cov.save_promo_model(db, org_id, *fit)
    coef, post_dip = cov.load_promo_model(db, org_id)
    db.flush()

    return cov.build_factors(
        series,
        as_of=as_of,
        horizon=horizon,
        events=events,
        uplifts=uplifts,
        category_names=cat_names,
        region_shares=shares,
        promotions=promotions,
        promo_coef=coef,
        post_dip=post_dip,
        channel_region=cov.channel_region_map(db, org_id),
    )


def _divide(s: Series, factors: dict[uuid.UUID, cov.Factors]) -> Series:
    f = factors.get(s.product_id)
    if f is None:
        return s
    hist_f = f.factor[: len(s.y)]
    return replace(s, y=s.y / np.maximum(hist_f, 1e-6))


def _multiply(b: Bands, f: np.ndarray, from_prior: np.ndarray) -> Bands:
    f = f[: len(b.p50)]
    from_prior = from_prior[: len(b.p50)]
    p50 = b.p50 * f
    lo = (b.p50 - b.p10) * f
    hi = (b.p90 - b.p50) * f
    widen = np.where(from_prior & (np.abs(f - 1) > 1e-9), cov.PRIOR_BAND_WIDEN, 1.0)
    return Bands(p50 - lo * widen, p50, p50 + hi * widen).clip()


def _rescore_all(
    series: list[Series], adj_series: list[Series], scored: dict, factors: dict
) -> dict[uuid.UUID, tuple[float | None, float | None]]:
    """WAPE/MAPE of (base model on adjusted train) x factor vs RAW holdout, batched by model."""
    from app.forecast.models import CrostonModel, StatsModel, chronos_predict_batch
    from app.forecast.router import _split, mape

    jobs: dict[str, list[tuple[int, np.ndarray, int]]] = {
        "chronos": [],
        "croston": [],
        "autoets": [],
    }
    for i, (s_raw, s_adj) in enumerate(zip(series, adj_series, strict=True)):
        sc = scored[s_adj]
        if s_raw.product_id not in factors or not sc.holdout_days or sc.model not in jobs:
            continue
        split = _split(s_adj)
        if split:
            jobs[sc.model].append((i, split[0], sc.holdout_days))
    runners = {
        "chronos": chronos_predict_batch,
        "croston": CrostonModel.predict_batch,
        "autoets": StatsModel.predict_batch,
    }
    out: dict[uuid.UUID, tuple[float | None, float | None]] = {}
    for model, items in jobs.items():
        by_h: dict[int, list[int]] = {}
        for k, (_, _, h) in enumerate(items):
            by_h.setdefault(h, []).append(k)
        for h, ks in by_h.items():
            preds = runners[model]([items[k][1] for k in ks], h)
            for k, b in zip(ks, preds, strict=True):
                i = items[k][0]
                s_raw = series[i]
                f = factors[s_raw.product_id]
                hist_f = f.factor[: len(s_raw.y)]
                actual = np.nan_to_num(s_raw.y[-h:])
                pred = b.p50 * hist_f[-h:]
                out[s_raw.product_id] = (wape(actual, pred), mape(actual, pred))
    return out


# --------------------------------------------------------------------------- misc
def latest_successful_run(db: Session, org_id: uuid.UUID) -> ForecastRun | None:
    return db.scalar(
        select(ForecastRun)
        .where(ForecastRun.org_id == org_id, ForecastRun.status == "success")
        .order_by(ForecastRun.finished_at.desc())
        .limit(1)
    )


def _count(run: ForecastRun, model: str) -> None:
    if model == "chronos":
        run.skus_chronos += 1
    elif model == "croston":
        run.skus_croston += 1
    elif model == "fallback":
        run.skus_fallback += 1


def _category_priors(series: list[Series]) -> dict:
    by_cat: dict = {}
    for s in series:
        if s.history_days >= 60 and s.category_id is not None:
            by_cat.setdefault(s.category_id, []).append(float(np.nanmean(s.y[-90:])))
    return {c: float(np.median(v)) for c, v in by_cat.items()}


def _dec(x, places: int = 4) -> Decimal | None:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return Decimal(f"{float(x):.{places}f}")


__all__ = ["DEFAULT_HORIZON", "Product", "latest_successful_run", "run_forecast", "wape"]
