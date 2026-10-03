"""Runs only where torch + chronos are installed (CI, Docker). Downloads the model once."""

import uuid

import numpy as np
import pandas as pd
import pytest

from app.forecast.features import Series
from app.forecast.models import chronos_available, chronos_predict_batch
from app.forecast.router import forecast_batch

pytestmark = pytest.mark.skipif(not chronos_available(), reason="chronos/torch not installed")


def test_chronos_batch_shapes_and_order() -> None:
    rng = np.random.default_rng(0)
    series = [rng.poisson(lam, 120).astype(float) for lam in (2, 20, 200)]
    out = chronos_predict_batch(series, 30)
    assert len(out) == 3
    for b in out:
        assert b.p10.shape == b.p50.shape == b.p90.shape == (30,)
        assert (b.p10 <= b.p50).all() and (b.p50 <= b.p90).all() and (b.p10 >= 0).all()
    # levels follow the input scale
    assert out[0].p50.mean() < out[1].p50.mean() < out[2].p50.mean()


def test_chronos_handles_masked_context() -> None:
    y = np.full(100, 10.0)
    y[-10:] = np.nan
    b = chronos_predict_batch([y], 7)[0]
    assert 6 < b.p50.mean() < 14


def test_router_uses_chronos_when_installed() -> None:
    rng = np.random.default_rng(5)
    s = Series(
        uuid.uuid4(),
        "X",
        None,
        pd.date_range("2025-01-01", periods=180),
        rng.poisson(8, 180).astype(float),
    )
    r = forecast_batch([s], 30)[s]
    assert r.wape_chronos is not None and r.wape_stats is not None
    assert r.model in ("chronos", "autoets")
