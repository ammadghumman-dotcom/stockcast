"""Worked example against the real engine (deterministic forecast inserted directly).

Setup (as_of = 2026-10-01, horizon 90):
  Candle CND = 200 g wax + 1 jar + 1 wick, made in house (production lead 7 d), 10/day flat.
  Stock: candle 50, wax 1,000 g, jar 30, wick 500.
  Suppliers: wax -> Pacific Wax (lead 21, MOQ 25,000, pack 25,000, 0.004/g)
             jar/wick -> ClearGlass (lead 30, MOQ 500; jar pack 100, wick pack 1,000)
  Org settings: service level 0.95, target cover 30 d; forecast p90 == p50 (no uncertainty).

Hand calculation
  Candle: 10/day, 50 on hand -> hits 0 on Oct 6, first unmet demand Oct 7 (days_of_cover 5).
          Production lead 7 -> ROP = 70 ->
          already below -> produce today: at arrival (day 6, Oct 8) stock = 50-70 -> 0 (lost
          sales) -> need 30 d cover = 300 -> PRODUCE 300 by Oct 1, expected Oct 8. Health at_risk.
  Wax:    derived 2,000 g/day. 1,000 g on hand -> stockout day 0 (Oct 2). Lead 21 -> ROP 42,000
          -> order today; cover 30 d = 60,000 -> MOQ 25,000 -> pack -> REORDER 75,000 g.
          Health at_risk (stockout within lead+buffer).
  Jar:    10/day, 30 on hand -> 0 on Oct 4, stockout Oct 5. Lead 30 -> ROP 300 -> order today;
          cover 300 -> MOQ 500 -> pack 100 -> REORDER 500. at_risk.
  Wick:   10/day, 500 on hand -> 0 on Nov 20, stockout Nov 21 (cover 50). Lead 30 -> ROP 300
          -> position
          breaches ROP after 20 days -> ORDER on day 20 (Oct 21), arrives Nov 20 (day 50):
          at arrival 500-510 -> 0 -> need 300 -> MOQ 500 -> pack 1,000 -> REORDER 1,000.
          Health healthy (stockout day 50 > lead 30 + buffer 7).
"""

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import (
    Forecast,
    PlanningRun,
    Product,
    Recommendation,
)
from app.planning.engine import run_planning

AS_OF = date(2026, 10, 1)


def _recs(db, run):
    rows = db.execute(
        select(Recommendation, Product.sku)
        .join(Product, Product.id == Recommendation.product_id)
        .where(Recommendation.run_id == run.id)
    ).all()
    return {sku: rec for rec, sku in rows}


def test_raw_material_plan_matches_hand_calculation(db, org, candle_world) -> None:
    run = PlanningRun(org_id=org.id)
    db.add(run)
    db.flush()
    run = run_planning(db, run, as_of=AS_OF)
    assert run.status == "success", run.error
    r = _recs(db, run)
    assert set(r) == {"CND", "WAX", "JAR", "WICK"}

    cnd = r["CND"]
    assert cnd.action == "produce" and cnd.qty == 300
    assert cnd.order_by_date == AS_OF and cnd.expected_date == AS_OF + timedelta(days=7)
    assert cnd.stockout_date == date(2026, 10, 7) and cnd.days_of_cover == 5
    assert cnd.health == "at_risk" and cnd.supplier_id is None
    assert cnd.daily_demand == 10 and cnd.reorder_point == 70

    wax = r["WAX"]
    assert wax.action == "reorder" and wax.qty == 75_000
    assert wax.daily_demand == 2000 and wax.reorder_point == 42_000 and wax.lead_time_days == 21
    assert wax.supplier_id == candle_world["suppliers"]["wax"].id
    assert wax.order_by_date == AS_OF and wax.expected_date == AS_OF + timedelta(days=21)
    assert wax.stockout_date == date(2026, 10, 2) and wax.health == "at_risk"
    assert "75,000 g" in wax.reason and "Pacific Wax" in wax.reason and "MOQ 25,000" in wax.reason

    jar = r["JAR"]
    assert jar.action == "reorder" and jar.qty == 500 and jar.lead_time_days == 30
    assert jar.stockout_date == date(2026, 10, 5) and jar.health == "at_risk"

    wick = r["WICK"]
    assert wick.action == "reorder" and wick.qty == 1000
    assert wick.order_by_date == AS_OF + timedelta(days=20)
    assert wick.expected_date == AS_OF + timedelta(days=50)
    assert wick.stockout_date == date(2026, 11, 21) and wick.days_of_cover == 50
    assert wick.health == "healthy"
    assert wick.reorder_point == 300 and wick.safety_stock == 0

    # cash tied up = on_hand x unit_cost, grouped by health
    assert run.health_counts == {"at_risk": 3, "healthy": 1}
    assert run.cash_by_health["healthy"] == pytest.approx(500 * 0.08)
    assert run.cash_by_health["at_risk"] == pytest.approx(50 * 4.20 + 1000 * 0.0045 + 30 * 0.65)
    assert run.n_reorder == 3 and run.n_produce == 1


def test_safety_stock_from_forecast_band_and_overrides(db, org, candle_world) -> None:
    """Widen the wick band -> safety stock appears; per-product override changes lead/cover."""
    p = candle_world["products"]
    db.execute(
        Forecast.__table__.update()
        .where(Forecast.product_id == p["CND"].id)
        .values(p90=Decimal("12.5632"))  # sigma = 2.0 candles/day -> wick sigma 2/day
    )
    p["WICK"].target_cover_days = 60
    p["WICK"].service_level = Decimal("0.99")
    db.flush()
    run = PlanningRun(org_id=org.id)
    db.add(run)
    db.flush()
    run_planning(db, run, as_of=AS_OF)
    wick = _recs(db, run)["WICK"]
    # safety = z(0.99)=2.3263 * sigma 2 * sqrt(30) = 25.5
    assert float(wick.safety_stock) == pytest.approx(2.3263 * 2 * 30**0.5, rel=0.02)
    assert float(wick.reorder_point) == pytest.approx(300 + float(wick.safety_stock), rel=1e-3)
    assert wick.qty == 1000  # 60d cover 600 + 25 safety -> 625 -> pack 1000


def test_open_po_counts_as_inbound_and_removes_reorder(db, org, candle_world) -> None:
    from app.models import POStatus, PurchaseOrder, PurchaseOrderLine

    p = candle_world["products"]
    po = PurchaseOrder(
        org_id=org.id,
        supplier_id=candle_world["suppliers"]["glass"].id,
        number="PO-1",
        status=POStatus.sent,
        expected_date=AS_OF + timedelta(days=2),
    )
    db.add(po)
    db.flush()
    db.add(
        PurchaseOrderLine(
            purchase_order_id=po.id,
            product_id=p["JAR"].id,
            qty=Decimal(1000),
            unit_price=Decimal("0.6"),
        )
    )
    db.flush()
    run = PlanningRun(org_id=org.id)
    db.add(run)
    db.flush()
    run_planning(db, run, as_of=AS_OF)
    jar = _recs(db, run)["JAR"]
    assert jar.inbound == 1000
    # 1,030 on the way; 10/day -> 103 days cover > 90-day horizon -> no stockout; position
    # (1,030) breaches ROP 300 after 73 days -> order then, not now
    assert jar.stockout_date is None and jar.action == "reorder"
    assert jar.order_by_date == AS_OF + timedelta(days=73)
    assert jar.health == "healthy"


def test_reason_mentions_event_in_window(db, org, candle_world) -> None:
    """Black Friday is flagged on days 50-57 with factor 2.4 -> wick order (day 20, lead 30 +
    cover 30 window) should cite it."""
    p = candle_world["products"]
    db.execute(
        Forecast.__table__.update()
        .where(Forecast.product_id == p["CND"].id, Forecast.event == "Black Friday")
        .values(factor=Decimal("2.4"), p50=Decimal(24), p90=Decimal(24))
    )
    db.flush()
    run = PlanningRun(org_id=org.id)
    db.add(run)
    db.flush()
    run_planning(db, run, as_of=AS_OF)
    wick = _recs(db, run)["WICK"]
    assert wick.event == "Black Friday" and float(wick.uplift_pct) == pytest.approx(140.0)
    assert "Black Friday +140%" in wick.reason


def test_planning_requires_forecast(db, org) -> None:
    run = PlanningRun(org_id=org.id)
    db.add(run)
    db.flush()
    with pytest.raises(RuntimeError, match="forecast"):
        run_planning(db, run, as_of=AS_OF)
    assert run.status == "failed"


_ = uuid
