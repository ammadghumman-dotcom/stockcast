"""Forecasting models behind one interface: predict(y, horizon) -> (p10, p50, p90) arrays.

- ChronosModel: amazon/chronos-bolt-small, zero-shot, CPU, batched across SKUs.
- CrostonModel: StatsForecast CrostonOptimized for intermittent demand (point forecast +
  empirical bands from the demand-size distribution).
- StatsModel: StatsForecast AutoETS — the "statistical" contender that Chronos is compared
  against in the backtest, and the primary model when Chronos is not installed.
- FallbackModel: median of the (short) history, wide bands; category median when the SKU has
  almost nothing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

QUANTILES = (0.1, 0.5, 0.9)
CHRONOS_MODEL_ID = "amazon/chronos-bolt-small"


@dataclass
class Bands:
    p10: np.ndarray
    p50: np.ndarray
    p90: np.ndarray

    def clip(self) -> Bands:
        self.p10 = np.clip(self.p10, 0, None)
        self.p50 = np.clip(self.p50, self.p10, None)
        self.p90 = np.clip(self.p90, self.p50, None)
        return self


def _fill(y: np.ndarray) -> np.ndarray:
    """Models cannot take NaN (masked stockout days): interpolate linearly, edges nearest."""
    y = y.astype(float).copy()
    nans = np.isnan(y)
    if nans.all():
        return np.zeros_like(y)
    if nans.any():
        idx = np.arange(len(y))
        y[nans] = np.interp(idx[nans], idx[~nans], y[~nans])
    return y


# --------------------------------------------------------------------------- Chronos
_chronos_pipeline = None


def chronos_available() -> bool:
    try:
        import chronos  # noqa: F401
        import torch  # noqa: F401

        return True
    except Exception:  # ImportError or a broken torch install
        return False


def _pipeline():
    global _chronos_pipeline
    if _chronos_pipeline is None:
        import torch
        from chronos import BaseChronosPipeline

        torch.set_num_threads(max(1, torch.get_num_threads()))
        _chronos_pipeline = BaseChronosPipeline.from_pretrained(
            CHRONOS_MODEL_ID, device_map="cpu", torch_dtype=torch.float32
        )
        log.info("loaded %s", CHRONOS_MODEL_ID)
    return _chronos_pipeline


def chronos_predict_batch(
    series: list[np.ndarray], horizon: int, *, batch_size: int = 64
) -> list[Bands]:
    """Batched zero-shot inference. Chronos-Bolt handles variable-length contexts natively."""
    import torch

    pipe = _pipeline()
    out: list[Bands] = []
    for i in range(0, len(series), batch_size):
        ctx = [
            torch.tensor(_fill(y)[-512:], dtype=torch.float32) for y in series[i : i + batch_size]
        ]
        q, _ = pipe.predict_quantiles(
            context=ctx, prediction_length=horizon, quantile_levels=list(QUANTILES)
        )
        q = q.numpy()  # (batch, horizon, 3)
        for k in range(q.shape[0]):
            out.append(Bands(q[k, :, 0], q[k, :, 1], q[k, :, 2]).clip())
    return out


# --------------------------------------------------------------------------- StatsForecast
def _sf_predict_many(series: list[np.ndarray], horizon: int, make_model) -> list[Bands]:
    """Fit one StatsForecast model per series in a single parallel call (n_jobs=-1)."""
    import os

    import pandas as pd
    from statsforecast import StatsForecast

    if not series:
        return []
    frames = []
    for i, y in enumerate(series):
        yf = _fill(y)
        frames.append(
            pd.DataFrame(
                {
                    "unique_id": str(i),
                    "ds": pd.date_range("2000-01-01", periods=len(yf), freq="D"),
                    "y": yf,
                }
            )
        )
    df = pd.concat(frames, ignore_index=True)
    model = make_model()
    name = getattr(model, "alias", type(model).__name__)
    n_jobs = -1 if len(series) >= 8 and (os.cpu_count() or 1) > 1 else 1
    sf = StatsForecast(models=[model], freq="D", n_jobs=n_jobs, fallback_model=_naive())
    fc = sf.forecast(df=df, h=horizon, level=[80])
    fc = fc.reset_index() if "unique_id" not in fc.columns else fc
    out: list[Bands] = []
    for i, y in enumerate(series):
        part = fc[fc["unique_id"] == str(i)]
        p50 = part[name].to_numpy(dtype=float)
        lo, hi = f"{name}-lo-80", f"{name}-hi-80"
        if lo in part and not np.isnan(part[lo].to_numpy(dtype=float)).all():
            p10, p90 = part[lo].to_numpy(dtype=float), part[hi].to_numpy(dtype=float)
        else:
            p10, p90 = _empirical_bands(_fill(y), p50)
        out.append(Bands(p10, p50, p90).clip())
    return out


def _naive():
    from statsforecast.models import SeasonalNaive

    return SeasonalNaive(season_length=7)


def _empirical_bands(y: np.ndarray, p50: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Bands from the empirical day-to-day distribution around the level (for Croston)."""
    obs = y[-90:]
    if obs.size < 7 or np.all(obs == 0):
        return p50 * 0.5, p50 * 1.5 + 1
    lo_q, hi_q = np.quantile(obs, 0.1), np.quantile(obs, 0.9)
    lvl = max(float(np.mean(obs)), 1e-9)
    return p50 * (lo_q / lvl), np.maximum(p50 * (hi_q / lvl), p50 + 1)


class CrostonModel:
    name = "croston"

    @staticmethod
    def predict_batch(series: list[np.ndarray], horizon: int) -> list[Bands]:
        from statsforecast.models import CrostonOptimized

        return _sf_predict_many(series, horizon, CrostonOptimized)

    @classmethod
    def predict(cls, y: np.ndarray, horizon: int) -> Bands:
        return cls.predict_batch([y], horizon)[0]


class StatsModel:
    name = "autoets"

    @staticmethod
    def predict_batch(series: list[np.ndarray], horizon: int) -> list[Bands]:
        from statsforecast.models import AutoETS

        # weekly seasonality once there is enough history for three cycles
        long = [i for i, y in enumerate(series) if np.count_nonzero(~np.isnan(y)) >= 21]
        short = [i for i in range(len(series)) if i not in set(long)]
        out: list[Bands | None] = [None] * len(series)
        if long:
            for i, b in zip(
                long,
                _sf_predict_many(
                    [series[i] for i in long], horizon, lambda: AutoETS(season_length=7)
                ),
                strict=True,
            ):
                out[i] = b
        if short:
            for i, b in zip(
                short,
                _sf_predict_many(
                    [series[i] for i in short], horizon, lambda: AutoETS(season_length=1)
                ),
                strict=True,
            ):
                out[i] = b
        return out  # type: ignore[return-value]

    @classmethod
    def predict(cls, y: np.ndarray, horizon: int) -> Bands:
        return cls.predict_batch([y], horizon)[0]


# --------------------------------------------------------------------------- Fallback
class FallbackModel:
    name = "fallback"

    @staticmethod
    def predict(y: np.ndarray, horizon: int, prior: float | None = None) -> Bands:
        obs = y[~np.isnan(y)]
        if obs.size >= 7:
            level = float(np.median(obs[-28:]))
            if level == 0:
                level = float(np.mean(obs[-28:]))
        elif obs.size:
            level = float(np.mean(obs))
        else:
            level = prior or 0.0
        if prior is not None and obs.size < 7:
            level = 0.5 * level + 0.5 * prior
        p50 = np.full(horizon, level)
        return Bands(p50 * 0.3, p50, p50 * 2.0 + 1.0).clip()
