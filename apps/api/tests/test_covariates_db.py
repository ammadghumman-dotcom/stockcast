"""DB-backed, one shared 2-year seed + forecast run per module.

Every test here MUST use the module-scoped `mdb`/`mclient` fixtures, never the function-scoped
`db`/`client`/`org`: two open transactions on TimescaleDB hypertables deadlock on chunk
catalog locks (seen in CI). Function-scoped API tests live in test_calendar_api.py.
"""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.forecast.engine import run_forecast
from app.models import CategoryHolidayUplift, ForecastRun, Product, ProductCategory, Promotion
from scripts.seed import DEMO_ORG_ID, seed

XMAS_AS_OF = date(2025, 12, 20)  # holdout Nov 23 - Dec 20 sits inside the Christmas window
H = {"X-Org-Id": str(DEMO_ORG_ID)}


# One 2-year seed + one forecast run shared by the whole module (each costs ~30 s).
@pytest.fixture(scope="module")
def mdb(engine):
    from sqlalchemy.orm import sessionmaker

    conn = engine.connect()
    tx = conn.begin()
    session = sessionmaker(bind=conn, join_transaction_mode="create_savepoint")()
    try:
        yield session
    finally:
        session.close()
        tx.rollback()
        conn.close()


@pytest.fixture(scope="module")
def xmas_run(mdb):
    import app.forecast.covariates as cov_mod
    import app.forecast.router as router_mod

    orig, orig_cov = router_mod.chronos_available, cov_mod.chronos_available
    router_mod.chronos_available = cov_mod.chronos_available = lambda: False
    try:
        seed(mdb, days=730, today=XMAS_AS_OF)
        run = ForecastRun(org_id=DEMO_ORG_ID, horizon_days=30)
        mdb.add(run)
        mdb.flush()
        yield run_forecast(mdb, run, as_of=XMAS_AS_OF)
    finally:
        router_mod.chronos_available, cov_mod.chronos_available = orig, orig_cov


@pytest.fixture
def mclient(mdb):
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: mdb
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_wape_improves_on_christmas_holdout(mdb, xmas_run) -> None:
    db, run = mdb, xmas_run
    assert run.status == "success", run.error
    assert run.wape is not None and run.wape_base is not None
    print(
        f"\n[backtest-covariates] Christmas holdout WAPE adjusted={run.wape} base={run.wape_base}"
    )
    assert float(run.wape) < float(run.wape_base) * 0.85  # at least 15 % better

    # learned uplifts persisted with sample sizes; priors present for the rest
    learned = db.scalars(
        select(CategoryHolidayUplift).where(
            CategoryHolidayUplift.org_id == DEMO_ORG_ID, CategoryHolidayUplift.learned.is_(True)
        )
    ).all()
    assert any(
        u.event_name == "Christmas" and u.sample_size >= 1 and u.uplift_pct > 50 for u in learned
    )
    assert (
        db.scalar(
            select(CategoryHolidayUplift).where(
                CategoryHolidayUplift.org_id == DEMO_ORG_ID,
                CategoryHolidayUplift.learned.is_(False),
            )
        )
        is not None
    )

    # promotion in the seed got measured and the org model fitted or global fallback used
    promo = db.scalar(select(Promotion).where(Promotion.org_id == DEMO_ORG_ID))
    assert promo.observed_lift is not None and 1.2 < float(promo.observed_lift) < 2.2
    assert promo.observed_post_dip is not None and float(promo.observed_post_dip) < 1.0


def test_forecast_points_carry_factor_and_event(mclient, mdb, xmas_run) -> None:
    client, db, run = mclient, mdb, xmas_run
    cat = db.scalar(select(ProductCategory).where(ProductCategory.name == "Gift Sets"))
    pid = db.scalar(select(Product.id).where(Product.category_id == cat.id).limit(1))
    r = client.get("/forecasts", params={"product_id": str(pid), "days": 4}, headers=H)
    assert r.status_code == 200, r.text
    pts = r.json()["points"]
    assert pts[0]["event"] == "Christmas" and float(pts[0]["factor"]) > 1.3
    assert r.json()["run_id"] == str(run.id)


def test_uplift_edit_turns_learned_into_manual(mclient, xmas_run) -> None:
    client = mclient
    rows = client.get("/category-uplifts", params={"learned": "true"}, headers=H).json()
    assert rows
    r = client.patch(f"/category-uplifts/{rows[0]['id']}", json={"uplift_pct": "99.5"}, headers=H)
    assert r.status_code == 200
    assert r.json()["learned"] is False and float(r.json()["uplift_pct"]) == 99.5


def test_simulate_endpoint_returns_delta_and_raw_material_impact(mclient, mdb, xmas_run) -> None:
    client, db, run = mclient, mdb, xmas_run
    candle = db.scalar(select(Product).where(Product.sku == "CND-VAN-200"))
    body = {
        "name": "Vanilla push",
        "type": "discount",
        "discount_pct": "25",
        "spend_amount": "1000",
        "scope": "skus",
        "product_ids": [str(candle.id)],
        "start_date": (XMAS_AS_OF + timedelta(days=3)).isoformat(),
        "end_date": (XMAS_AS_OF + timedelta(days=9)).isoformat(),
    }
    r = client.post("/forecasts/simulate", json=body, headers=H)
    assert r.status_code == 200, r.text
    sim = r.json()
    assert sim["run_id"] == str(run.id) and sim["lift"] > 1.0 and 0 < sim["post_dip"] <= 1.0
    assert len(sim["products"]) == 1
    p = sim["products"][0]
    assert p["sku"] == "CND-VAN-200" and p["delta_units"] > 0 and p["post_dip_units"] <= 0
    assert p["promo_units"] == pytest.approx(p["base_units"] * sim["lift"], rel=1e-6)
    # BOM: 1 candle = 200 g wax + 1 jar + 1 wick
    mats = {m["sku"]: m for m in sim["materials"]}
    net = p["delta_units"] + p["post_dip_units"]
    assert mats["RM-WAX-SOY"]["delta_qty"] == pytest.approx(net * 200, rel=1e-6)
    assert mats["RM-JAR-200"]["delta_qty"] == pytest.approx(net, rel=1e-6)
    assert mats["RM-WAX-SOY"]["unit"] == "g"

    # scope=all touches every finished SKU but no raw materials as products
    body.update({"scope": "all", "product_ids": None})
    sim = client.post("/forecasts/simulate", json=body, headers=H).json()
    assert len(sim["products"]) == 20 and "RM-WAX-SOY" not in {x["sku"] for x in sim["products"]}
