"""Unit tests: calendar, uplift learning, factor building, promo lift fit. No DB."""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from app.forecast import covariates as cov
from app.forecast.calendar import builtin_events
from app.forecast.features import Series
from app.models import Promotion
from app.models.enums import PromotionScope, PromotionType

US = uuid.uuid4()
CANDLES = uuid.uuid4()


def _series(y, start=date(2024, 1, 1), category=CANDLES) -> Series:
    y = np.asarray(y, dtype=float)
    return Series(uuid.uuid4(), "SKU", category, pd.date_range(start, periods=len(y)), y)


# ---- calendar ----
def test_builtin_events_have_lead_in_windows_and_regional_rules() -> None:
    us = {e.name: e for e in builtin_events("US", 2025)}
    assert (us["Christmas"].start, us["Christmas"].end) == (date(2025, 11, 20), date(2025, 12, 24))
    assert us["Black Friday"].end == date(2025, 11, 28)  # day after 4th Thursday
    assert us["Mother's Day"].end == date(2025, 5, 11)  # 2nd Sunday of May
    uk = {e.name: e for e in builtin_events("UK", 2025)}
    assert uk["Mother's Day"].end == date(2025, 3, 30)  # Mothering Sunday
    ae = {e.name: e for e in builtin_events("AE", 2025)}
    assert (
        ae["Ramadan/Eid"].end == date(2025, 3, 30)
        and (ae["Ramadan/Eid"].end - ae["Ramadan/Eid"].start).days == 30
    )
    assert "Diwali" in {e.name for e in builtin_events("IN", 2025)}


# ---- uplift learning ----
def test_learn_uplift_recovers_synthetic_peak() -> None:
    """Flat 10/day, except a 20-day event window at 25/day in 2024 -> learned ~2.5x."""
    rng = np.random.default_rng(0)
    days = 400
    y = rng.poisson(10, days).astype(float)
    ev_start = date(2024, 1, 1) + timedelta(days=200)
    y[200:220] = rng.poisson(25, 20)
    s = _series(y)
    events = [cov.EventOcc("Festival", US, ev_start, ev_start + timedelta(days=19))]
    learned = cov.learn_holiday_uplifts(
        [s], events, region_shares={s.product_id: {US: 1.0}}, cutoff=date(2025, 6, 1)
    )
    up = learned[(CANDLES, US, "Festival")]
    assert up.learned and up.sample_size == 1
    assert 2.0 < up.multiplier < 2.9  # shrinkage pulls 2.5 slightly toward 1


def test_learn_uplift_ignores_windows_in_or_after_cutoff() -> None:
    y = np.full(300, 10.0)
    s = _series(y)
    ev = cov.EventOcc("Late", US, date(2024, 9, 1), date(2024, 9, 10))
    learned = cov.learn_holiday_uplifts(
        [s], [ev], region_shares={s.product_id: {US: 1.0}}, cutoff=date(2024, 8, 1)
    )
    assert learned == {}


def test_learn_uplift_skips_products_not_sold_in_region() -> None:
    y = np.full(300, 10.0)
    s = _series(y)
    other_region = uuid.uuid4()
    ev = cov.EventOcc("Eid", other_region, date(2024, 5, 1), date(2024, 5, 10))
    learned = cov.learn_holiday_uplifts(
        [s], [ev], region_shares={s.product_id: {US: 1.0}}, cutoff=date(2025, 1, 1)
    )
    assert learned == {}


# ---- factors ----
def _factors(series, events, uplifts, promotions=(), horizon=30, as_of=date(2024, 12, 1)):
    return cov.build_factors(
        series,
        as_of=as_of,
        horizon=horizon,
        events=events,
        uplifts=uplifts,
        category_names={CANDLES: "Candles"},
        region_shares={s.product_id: {US: 1.0} for s in series},
        promotions=list(promotions),
        promo_coef=dict(cov.GLOBAL_COEF),
        post_dip=0.9,
        channel_region={},
    )[series[0].product_id]


def test_overlapping_events_take_max_not_product() -> None:
    s = _series(np.full(300, 10.0), start=date(2024, 3, 1))
    xmas = cov.EventOcc("Christmas", US, date(2024, 11, 20), date(2024, 12, 24))
    bf = cov.EventOcc("Black Friday", US, date(2024, 11, 22), date(2024, 11, 29))
    ups = {
        (CANDLES, US, "Christmas"): cov.Uplift(2.0, True, 1),
        (CANDLES, US, "Black Friday"): cov.Uplift(1.8, True, 1),
    }
    f = _factors([s], [xmas, bf], ups, horizon=40)
    i = f.dates.index(date(2024, 11, 25))
    assert f.factor[i] < 2.0 * 1.8 * 0.9  # never multiplied together
    assert f.factor[i] > 1.0 and f.event[i] in ("Christmas", "Black Friday")
    assert not f.from_prior[i]


def test_prior_flagged_and_ramp_mean_matches_multiplier() -> None:
    s = _series(np.full(300, 10.0), start=date(2024, 3, 1))
    ev = cov.EventOcc("Christmas", US, date(2024, 11, 20), date(2024, 12, 24))
    f = _factors([s], [ev], {}, horizon=40)  # no stored uplift -> category prior 2.5x
    i0, i1 = f.dates.index(ev.start), f.dates.index(ev.end)
    seg = f.factor[i0 : i1 + 1]
    assert f.from_prior[i0 : i1 + 1].all()
    assert seg.mean() == pytest.approx(2.5, rel=0.02)
    assert seg[-1] > seg[0]  # ramps up toward the event


def test_promotion_factor_uses_observed_lift_and_post_dip() -> None:
    s = _series(np.full(300, 10.0), start=date(2024, 3, 1))
    p = Promotion(
        id=uuid.uuid4(),
        name="Sale",
        type=PromotionType.discount,
        start_date=date(2024, 12, 5),
        end_date=date(2024, 12, 9),
        discount_pct=Decimal("20"),
        scope=PromotionScope.all,
        observed_lift=Decimal("1.6"),
        observed_post_dip=Decimal("0.8"),
    )
    f = _factors([s], [], {}, promotions=[p], horizon=30)
    assert f.factor[f.dates.index(date(2024, 12, 7))] == pytest.approx(1.6)
    assert f.factor[f.dates.index(date(2024, 12, 12))] == pytest.approx(0.8)
    assert f.factor[f.dates.index(date(2024, 12, 20))] == pytest.approx(1.0)
    assert f.event[f.dates.index(date(2024, 12, 7))] == "promo: Sale"


def test_predicted_lift_grows_with_discount_and_spend() -> None:
    def promo(disc, spend):
        return Promotion(
            type=PromotionType.paid_ads,
            discount_pct=Decimal(disc),
            spend_amount=Decimal(spend),
            scope=PromotionScope.all,
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 2),
            name="x",
        )

    base = cov.predict_lift(promo(0, 0), cov.GLOBAL_COEF, None)
    assert cov.predict_lift(promo(30, 0), cov.GLOBAL_COEF, None) > base
    assert cov.predict_lift(promo(0, 5000), cov.GLOBAL_COEF, None) > base


# ---- promo model fit ----
def test_fit_promo_model_recovers_discount_effect() -> None:
    rng = np.random.default_rng(1)
    promos = []
    for i in range(12):
        disc = float(rng.choice([10, 20, 30, 40]))
        spend = float(rng.choice([0, 500, 2000]))
        lift = np.exp(0.03 * disc + 0.02 * np.log1p(spend) + rng.normal(0, 0.03))
        promos.append(
            Promotion(
                id=uuid.uuid4(),
                name=f"p{i}",
                type=PromotionType.discount,
                scope=PromotionScope.all,
                start_date=date(2025, 1, 1),
                end_date=date(2025, 1, 5),
                discount_pct=Decimal(disc),
                spend_amount=Decimal(spend),
                observed_lift=Decimal(f"{lift:.4f}"),
                observed_post_dip=Decimal("0.9"),
            )
        )
    fit = cov.fit_promo_model(promos, {}, alpha=0.1)
    assert fit is not None
    coef, post_dip, n, r2 = fit
    assert n == 12 and post_dip == pytest.approx(0.9)
    assert 0.02 < coef["discount_pct"] < 0.04
    assert r2 is not None and r2 > 0.8
    # prediction from the fitted model reproduces a known case
    p = Promotion(
        type=PromotionType.discount,
        discount_pct=Decimal(30),
        spend_amount=Decimal(0),
        scope=PromotionScope.all,
        start_date=date(2025, 2, 1),
        end_date=date(2025, 2, 2),
        name="q",
    )
    assert cov.predict_lift(p, coef, None) == pytest.approx(np.exp(0.9), rel=0.15)


def test_fit_promo_model_needs_min_samples() -> None:
    p = Promotion(
        type=PromotionType.email,
        scope=PromotionScope.all,
        name="a",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 1, 2),
        observed_lift=Decimal("1.2"),
    )
    assert cov.fit_promo_model([p, p], {}) is None


def test_measure_promotions_lift_and_dip() -> None:
    y = np.full(200, 10.0)
    y[100:110] = 16.0  # promo window
    y[110:117] = 8.5  # post-promo dip
    s = _series(y)
    p = Promotion(
        id=uuid.uuid4(),
        name="S",
        type=PromotionType.discount,
        scope=PromotionScope.all,
        start_date=date(2024, 1, 1) + timedelta(days=100),
        end_date=date(2024, 1, 1) + timedelta(days=109),
        discount_pct=Decimal(20),
    )
    out = cov.measure_promotions([s], [p], cutoff=date(2025, 1, 1))
    lift, dip, base = out[p.id]
    assert lift == pytest.approx(1.6, rel=0.05)
    assert dip == pytest.approx(0.85, rel=0.05)
    assert base == pytest.approx(100, rel=0.05)
