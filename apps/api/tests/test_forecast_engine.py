"""DB-backed: full run on the seed org, persistence, idempotent retry, API, scoping."""

from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.forecast.engine import run_forecast
from app.models import Forecast, ForecastAccuracy, ForecastRun
from scripts.seed import DEMO_ORG_ID, seed

AS_OF = date(2026, 9, 30)


# One seed + one run shared across the module: a full run with real Chronos in CI costs
# minutes, so tests that only read results reuse it. Base engine only (no covariates here;
# those have their own module).
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
def seeded_run(mdb):
    import app.forecast.router as router_mod

    orig = router_mod.chronos_available
    router_mod.chronos_available = lambda: False
    try:
        seed(mdb, days=200, today=AS_OF)
        run = ForecastRun(org_id=DEMO_ORG_ID, trigger="manual", horizon_days=90)
        mdb.add(run)
        mdb.flush()
        yield run_forecast(mdb, run, as_of=AS_OF, use_covariates=False)
    finally:
        router_mod.chronos_available = orig


@pytest.fixture
def mclient(mdb):
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: mdb
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_run_on_seed_reports_wape_and_persists(mdb, seeded_run) -> None:
    db, run = mdb, seeded_run
    assert run.status == "success", run.error
    assert run.skus_total == 20
    assert run.wape is not None and 0 < float(run.wape) < 1.0
    n_fc = db.scalar(select(func.count()).select_from(Forecast).where(Forecast.run_id == run.id))
    assert n_fc == 20 * 90
    first = db.scalar(select(func.min(Forecast.date)).where(Forecast.run_id == run.id))
    assert first == AS_OF + timedelta(days=1)
    n_acc = db.scalar(
        select(func.count()).select_from(ForecastAccuracy).where(ForecastAccuracy.run_id == run.id)
    )
    assert n_acc == 20
    # surfaced in CI logs as the acceptance number
    print(
        f"\n[backtest] seed org WAPE={run.wape} skus={run.skus_total} "
        f"(autoets={run.skus_total - run.skus_chronos - run.skus_croston - run.skus_fallback}, "
        f"chronos={run.skus_chronos}, croston={run.skus_croston}, fallback={run.skus_fallback})"
    )


def test_rerun_same_run_is_idempotent(mdb, seeded_run) -> None:
    db = mdb
    run = run_forecast(db, seeded_run, as_of=AS_OF, use_covariates=False)
    assert run.status == "success"
    assert (
        db.scalar(select(func.count()).select_from(Forecast).where(Forecast.run_id == run.id))
        == 1800
    )


def test_forecast_api(mclient, mdb, seeded_run) -> None:
    client, db = mclient, mdb
    headers = {"X-Org-Id": str(DEMO_ORG_ID)}
    pid = str(
        db.scalar(select(Forecast.product_id).where(Forecast.run_id == seeded_run.id).limit(1))
    )

    r = client.get("/forecasts", params={"product_id": pid, "days": 30}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["points"]) == 30 and body["run_id"] == str(seeded_run.id)
    assert body["points"][0]["date"] == (AS_OF + timedelta(days=1)).isoformat()
    assert float(body["total_p50_30d"]) > 0
    p = body["points"][0]
    assert float(p["p10"]) <= float(p["p50"]) <= float(p["p90"])

    r = client.get("/forecast-accuracy", headers=headers)
    assert r.status_code == 200
    acc = r.json()
    assert acc["skus"] == 20 and acc["wape"] is not None and acc["median_sku_wape"] is not None
    assert sum(acc["by_model"].values()) == 20
    assert len(acc["worst"]) == 10
    assert float(acc["worst"][0]["wape"]) >= float(acc["worst"][-1]["wape"])

    runs = client.get("/forecast-runs", headers=headers).json()
    assert runs[0]["status"] == "success" and runs[0]["skus_total"] == 20


def test_forecast_is_org_scoped(mclient, mdb, seeded_run) -> None:
    import uuid

    from app.models import Organization

    client, db = mclient, mdb
    other = Organization(id=uuid.uuid4(), name="Rival", slug="rival-fc")
    db.add(other)
    db.flush()
    other_headers = {"X-Org-Id": str(other.id)}
    pid = str(
        db.scalar(select(Forecast.product_id).where(Forecast.run_id == seeded_run.id).limit(1))
    )
    assert (
        client.get("/forecasts", params={"product_id": pid}, headers=other_headers).status_code
        == 422
    )
    acc = client.get("/forecast-accuracy", headers=other_headers).json()
    assert acc["skus"] == 0 and acc["run_id"] is None
    assert client.get("/forecast-runs", headers=other_headers).json() == []


def test_trigger_endpoint_runs_inline_in_eager_mode(client, db, headers, org, monkeypatch) -> None:
    monkeypatch.setattr("app.forecast.router.chronos_available", lambda: False)
    r = client.post("/forecast-runs", params={"horizon": 14}, headers=headers)
    assert r.status_code == 202, r.text
    run = r.json()
    assert run["status"] == "success" and run["skus_total"] == 0 and run["horizon_days"] == 14
