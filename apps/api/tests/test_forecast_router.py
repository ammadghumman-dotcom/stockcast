"""Pure unit tests: routing rules, stockout masking, metrics, fallback bands. No DB."""

import uuid
from datetime import date

import numpy as np
import pandas as pd
import pytest

from app.forecast.features import Series, stockout_days
from app.forecast.models import FallbackModel, StatsModel
from app.forecast.router import (
    HOLDOUT_DAYS,
    INTERMITTENT_ZERO_SHARE,
    MIN_HISTORY,
    Route,
    forecast_batch,
    mape,
    route,
    wape,
)


def _series(y, mask=None) -> Series:
    y = np.asarray(y, dtype=float)
    if mask is not None:
        y = y.copy()
        y[np.asarray(mask, dtype=bool)] = np.nan
    return Series(uuid.uuid4(), "SKU", None, pd.date_range("2025-01-01", periods=len(y)), y)


# ---- routing ----
def test_route_short_history_is_fallback() -> None:
    assert route(_series(np.ones(MIN_HISTORY - 1))) == Route.fallback


def test_route_masked_days_do_not_count_as_history() -> None:
    y = np.ones(MIN_HISTORY + 10)
    mask = np.zeros_like(y, dtype=bool)
    mask[-20:] = True  # 20 stockout days masked -> only 50 observed
    assert route(_series(y, mask)) == Route.fallback


def test_route_intermittent_is_croston() -> None:
    y = np.zeros(100)
    y[::3] = 2  # ~33 % non-zero -> 67 % zeros
    s = _series(y)
    assert s.zero_share > INTERMITTENT_ZERO_SHARE
    assert route(s) == Route.croston


def test_route_regular_is_chronos() -> None:
    rng = np.random.default_rng(1)
    s = _series(rng.poisson(5, 120))
    assert route(s) == Route.chronos


# ---- stockout masking ----
def test_stockout_mask_trailing_zeros_when_out_of_stock() -> None:
    y = np.array([3, 4, 2, 0, 0, 0, 0], dtype=float)
    mask = stockout_days(y, on_hand_now=0)
    assert mask.tolist() == [False, False, False, True, True, True, True]


def test_stockout_mask_requires_min_run() -> None:
    y = np.array([3, 4, 2, 0], dtype=float)
    assert not stockout_days(y, on_hand_now=0, min_run=2).any()


def test_stockout_mask_off_when_in_stock() -> None:
    y = np.array([3, 0, 0, 0], dtype=float)
    assert not stockout_days(y, on_hand_now=12).any()


def test_masked_days_are_excluded_from_training() -> None:
    """A SKU selling 10/day that is out of stock the last 20 days should still forecast ~10,
    not get dragged toward 0 by the stockout zeros."""
    y = np.full(120, 10.0)
    y[-20:] = 0
    masked = _series(y, mask=[False] * 100 + [True] * 20)
    unmasked = _series(y)
    b_masked = StatsModel.predict(masked.y, 14)
    b_unmasked = StatsModel.predict(unmasked.y, 14)
    assert b_masked.p50.mean() > 8.0
    assert b_unmasked.p50.mean() < b_masked.p50.mean()


# ---- metrics ----
def test_wape_and_mape() -> None:
    a = np.array([10, 20, 0, 10], dtype=float)
    p = np.array([12, 18, 1, 10], dtype=float)
    assert wape(a, p) == pytest.approx(5 / 40)
    assert mape(a, p) == pytest.approx((0.2 + 0.1 + 0.0) / 3)  # zero actual excluded
    assert wape(np.zeros(3), np.ones(3)) is None
    assert mape(np.zeros(3), np.ones(3)) is None


# ---- fallback ----
def test_fallback_has_wide_bands_and_uses_prior_for_cold_start() -> None:
    b = FallbackModel.predict(np.array([np.nan, np.nan]), 5, prior=4.0)
    assert np.allclose(b.p50, 4.0) and (b.p10 < b.p50).all() and (b.p90 > b.p50).all()
    b2 = FallbackModel.predict(np.array([2.0, 2.0, 2.0]), 5, prior=6.0)
    assert np.allclose(b2.p50, 4.0)  # blended 50/50 with the category prior


# ---- batch orchestration ----
def test_forecast_batch_routes_and_backtests(monkeypatch) -> None:
    monkeypatch.setattr("app.forecast.router.chronos_available", lambda: False)
    rng = np.random.default_rng(2)
    regular = _series(rng.poisson(6, 150))
    sparse_y = np.zeros(150)
    sparse_y[rng.random(150) < 0.2] = 3
    sparse = _series(sparse_y)
    short = _series(rng.poisson(6, 20))
    out = forecast_batch([regular, sparse, short], 30)

    assert out[regular].model == "autoets" and out[regular].holdout_days == HOLDOUT_DAYS
    assert out[regular].wape is not None and out[regular].wape_stats == out[regular].wape
    assert out[regular].wape_chronos is None
    assert out[sparse].model == "croston" and out[sparse].holdout_days == HOLDOUT_DAYS
    assert out[short].model == "fallback" and out[short].wape is None
    for sc in out.values():
        assert len(sc.bands.p50) == 30
        assert (sc.bands.p10 <= sc.bands.p50).all() and (sc.bands.p50 <= sc.bands.p90).all()
        assert (sc.bands.p10 >= 0).all()


def test_chronos_selected_only_when_it_wins(monkeypatch) -> None:
    """Fake Chronos: once perfect (wins), once terrible (loses to AutoETS)."""
    from app.forecast.models import Bands

    rng = np.random.default_rng(3)
    s = _series(rng.poisson(6, 150))
    monkeypatch.setattr("app.forecast.router.chronos_available", lambda: True)

    def good(series_list, h):
        return [Bands(np.full(h, 5.0), np.full(h, 6.0), np.full(h, 7.0)) for _ in series_list]

    def bad(series_list, h):
        return [Bands(np.full(h, 90.0), np.full(h, 100.0), np.full(h, 110.0)) for _ in series_list]

    monkeypatch.setattr("app.forecast.router.chronos_predict_batch", good)
    r = forecast_batch([s], 10)[s]
    assert r.model == "chronos" and r.wape_chronos <= r.wape_stats

    monkeypatch.setattr("app.forecast.router.chronos_predict_batch", bad)
    r = forecast_batch([s], 10)[s]
    assert r.model == "autoets" and r.wape_chronos > r.wape_stats


_ = date  # keep import for readability of fixtures
