"""Per-SKU model routing and backtest-driven selection.

Routing (spec):
  history >= 60 observed days and zero_share <= 0.5 -> Chronos (vs AutoETS in backtest)
  zero_share > 0.5 (intermittent)                    -> Croston
  history < 60                                       -> fallback (median / category prior)

Backtest: hold out the last 28 observed days, forecast them from the rest, score MAPE and
WAPE. For the Chronos route both Chronos and AutoETS are scored and the better WAPE wins
for the production forecast.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from app.forecast.features import Series
from app.forecast.models import (
    Bands,
    CrostonModel,
    FallbackModel,
    StatsModel,
    chronos_available,
    chronos_predict_batch,
)

MIN_HISTORY = 60
INTERMITTENT_ZERO_SHARE = 0.5
HOLDOUT_DAYS = 28


class Route(StrEnum):
    chronos = "chronos"
    croston = "croston"
    fallback = "fallback"


def route(series: Series) -> Route:
    if series.history_days < MIN_HISTORY:
        return Route.fallback
    if series.zero_share > INTERMITTENT_ZERO_SHARE:
        return Route.croston
    return Route.chronos


@dataclass
class Scored:
    model: str
    bands: Bands  # production forecast (full history -> horizon)
    mape: float | None
    wape: float | None
    wape_chronos: float | None = None
    wape_stats: float | None = None
    holdout_days: int = 0


def wape(actual: np.ndarray, pred: np.ndarray) -> float | None:
    denom = float(np.abs(actual).sum())
    return float(np.abs(actual - pred).sum() / denom) if denom > 0 else None


def mape(actual: np.ndarray, pred: np.ndarray) -> float | None:
    nz = actual != 0
    if not nz.any():
        return None
    return float(np.mean(np.abs((actual[nz] - pred[nz]) / actual[nz])))


def _split(series: Series) -> tuple[np.ndarray, np.ndarray] | None:
    """(train, holdout_actuals) on observed values; None when too short to hold out."""
    y = series.y
    obs_idx = np.flatnonzero(~np.isnan(y))
    if obs_idx.size < HOLDOUT_DAYS + 14:
        return None
    cut = obs_idx[-HOLDOUT_DAYS]
    return y[:cut], y[cut:]


def forecast_batch(
    all_series: list[Series], horizon: int, *, category_prior: dict | None = None
) -> dict[Series, Scored]:
    """Route, backtest and forecast every series. Model calls are batched across SKUs."""
    routes = {s: route(s) for s in all_series}
    splits = {s: _split(s) for s in all_series}
    use_chronos = chronos_available()

    # ---- gather (series, context, horizon) jobs per model, then run each model once
    jobs: dict[str, list[tuple[Series, str, np.ndarray, int]]] = {
        "chronos": [],
        "autoets": [],
        "croston": [],
    }
    for s, r in routes.items():
        split = splits[s]
        if r == Route.chronos:
            if split:
                jobs["autoets"].append((s, "bt", split[0], len(split[1])))
                if use_chronos:
                    jobs["chronos"].append((s, "bt", split[0], len(split[1])))
            jobs["autoets"].append((s, "prod", s.y, horizon))
            if use_chronos:
                jobs["chronos"].append((s, "prod", s.y, horizon))
        elif r == Route.croston:
            if split:
                jobs["croston"].append((s, "bt", split[0], len(split[1])))
            jobs["croston"].append((s, "prod", s.y, horizon))

    preds: dict[tuple[int, str, str], Bands] = {}  # (id(series), kind, model) -> bands
    runners = {
        "chronos": chronos_predict_batch,
        "autoets": StatsModel.predict_batch,
        "croston": CrostonModel.predict_batch,
    }
    for model, items in jobs.items():
        by_h: dict[int, list[int]] = {}
        for i, (_, _, _, h) in enumerate(items):
            by_h.setdefault(h, []).append(i)
        for h, idxs in by_h.items():
            bands = runners[model]([items[i][2] for i in idxs], h)
            for i, b in zip(idxs, bands, strict=True):
                s, kind, _, _ = items[i]
                preds[(id(s), kind, model)] = b

    results: dict[Series, Scored] = {}
    for s, r in routes.items():
        split = splits[s]
        actual = _fill(split[1]) if split else None
        hold = len(actual) if actual is not None else 0
        if r == Route.fallback:
            prior = (category_prior or {}).get(s.category_id)
            results[s] = Scored(
                FallbackModel.name, FallbackModel.predict(s.y, horizon, prior=prior), None, None
            )
            continue
        if r == Route.croston:
            bt = preds.get((id(s), "bt", "croston"))
            m = mape(actual, bt.p50) if bt is not None else None
            w = wape(actual, bt.p50) if bt is not None else None
            results[s] = Scored(
                "croston", preds[(id(s), "prod", "croston")], m, w, holdout_days=hold
            )
            continue
        # chronos route: compare against autoets on the holdout, best WAPE wins
        bt_c, bt_s = preds.get((id(s), "bt", "chronos")), preds.get((id(s), "bt", "autoets"))
        w_c = wape(actual, bt_c.p50) if bt_c is not None else None
        w_s = wape(actual, bt_s.p50) if bt_s is not None else None
        prod_c = preds.get((id(s), "prod", "chronos"))
        pick_chronos = prod_c is not None and (w_s is None or w_c is None or w_c <= w_s)
        name = "chronos" if pick_chronos else StatsModel.name
        bands = prod_c if pick_chronos else preds[(id(s), "prod", "autoets")]
        chosen_bt = bt_c if pick_chronos else bt_s
        m = mape(actual, chosen_bt.p50) if chosen_bt is not None else None
        results[s] = Scored(
            name,
            bands,
            m,
            w_c if pick_chronos else w_s,
            wape_chronos=w_c,
            wape_stats=w_s,
            holdout_days=hold,
        )
    return results


def _fill(a: np.ndarray) -> np.ndarray:
    a = a.astype(float).copy()
    a[np.isnan(a)] = 0.0
    return a
