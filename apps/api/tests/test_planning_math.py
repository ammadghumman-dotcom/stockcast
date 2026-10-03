"""Pure math: projection, reorder sizing, health. No DB."""

import numpy as np
import pytest

from app.planning import math as pm
from app.planning.bom import explode_demand


def test_project_stock_finds_stockout_and_counts_inbound() -> None:
    demand = np.full(10, 10.0)
    p = pm.project_stock(35, demand)
    assert p.stockout_day == 3 and p.days_of_cover == 3  # 35-10-10-10 = 5, day 3 -> -5
    p2 = pm.project_stock(35, demand, inbound={2: 100})
    assert p2.stockout_day is None and p2.stock[-1] == pytest.approx(35 + 100 - 100)


def test_z_score_interpolates() -> None:
    assert pm.z_score(0.95) == pytest.approx(1.6449)
    assert 1.6449 < pm.z_score(0.96) < 1.96
    assert pm.z_score(0.5) == 0.0


def test_reorder_point_formula() -> None:
    p50 = np.full(60, 10.0)
    p90 = p50 + 1.2816 * 2.0  # sigma_daily = 2
    plan = pm.reorder(
        1000, p50, p90, inbound=None, lead_time_days=16, service_level=0.95, target_cover_days=30
    )
    assert plan.sigma_daily == pytest.approx(2.0)
    assert plan.safety_stock == pytest.approx(1.6449 * 2.0 * 4.0)  # z * sigma * sqrt(16)
    assert plan.reorder_point == pytest.approx(160 + plan.safety_stock)


def test_reorder_orders_on_rop_breach_and_sizes_to_cover() -> None:
    p50 = np.full(90, 10.0)
    p90 = p50.copy()  # no uncertainty -> no safety stock
    plan = pm.reorder(
        500,
        p50,
        p90,
        inbound=None,
        lead_time_days=30,
        service_level=0.95,
        target_cover_days=30,
        moq=1,
        pack_size=1000,
    )
    assert plan.safety_stock == 0 and plan.reorder_point == 300
    # position 500 breaches 300 after 20 days of demand -> order on day index 20
    assert plan.order_day == 20 and plan.arrival_day == 50
    # on-hand at arrival = 500 - 51*10 = -10 -> clamped to 0 -> need 300 -> pack 1000
    assert plan.qty == 1000


def test_reorder_respects_moq_and_overdue() -> None:
    p50 = np.full(60, 2000.0)
    plan = pm.reorder(
        1000,
        p50,
        p50,
        inbound=None,
        lead_time_days=21,
        service_level=0.9,
        target_cover_days=30,
        moq=25000,
        pack_size=25000,
    )
    assert plan.order_day == -1  # already below ROP (42,000)
    # stock is exhausted before arrival (lost sales -> 0 on hand), so need = 30 days cover =
    # 60,000 -> above MOQ 25,000 -> rounded up to 3 packs of 25,000
    assert plan.qty == 75000


def test_no_order_when_no_demand() -> None:
    plan = pm.reorder(
        10,
        np.zeros(30),
        np.zeros(30),
        inbound=None,
        lead_time_days=5,
        service_level=0.95,
        target_cover_days=30,
    )
    assert plan.qty == 0 and plan.order_day is None


def test_health_rules() -> None:
    kw = dict(lead_time_days=10, at_risk_buffer_days=7, overstock_days=120)
    assert (
        pm.health_status(on_hand=0, stockout_day=0, days_of_cover=0, daily_demand=5, **kw)
        == "stockout"
    )
    assert (
        pm.health_status(on_hand=50, stockout_day=12, days_of_cover=12, daily_demand=5, **kw)
        == "at_risk"
    )
    assert (
        pm.health_status(on_hand=50, stockout_day=40, days_of_cover=40, daily_demand=5, **kw)
        == "healthy"
    )
    assert (
        pm.health_status(on_hand=5000, stockout_day=None, days_of_cover=None, daily_demand=5, **kw)
        == "overstock"
    )
    assert (
        pm.health_status(on_hand=0, stockout_day=None, days_of_cover=None, daily_demand=0, **kw)
        == "healthy"
    )


def test_bom_explosion_multi_level() -> None:
    import uuid

    candle, wax, jar, lid, box = (uuid.uuid4() for _ in range(5))
    bom = {candle: [(wax, 200.0), (jar, 1.0)], jar: [(lid, 1.0)], box: [(candle, 3.0)]}
    demand = {candle: np.full(3, 10.0), box: np.full(3, 2.0)}
    out = explode_demand(bom, demand)
    # candle demand = 10 direct + 2*3 from boxes = 16/day
    assert np.allclose(out[candle], 6.0)  # derived only (boxes); direct demand stays independent
    assert np.allclose(out[wax], 16 * 200.0)
    assert np.allclose(out[jar], 16.0)
    assert np.allclose(out[lid], 16.0)


def test_derived_band_ratio_is_capped() -> None:
    import uuid

    from app.planning.engine import _rel_band

    parent, comp = uuid.uuid4(), uuid.uuid4()
    fc = {parent: (np.full(10, 0.001), np.full(10, 5.0), np.ones(10), [None] * 10)}
    assert _rel_band(fc, {parent: [(comp, 1.0)]}, comp) == 3.0
