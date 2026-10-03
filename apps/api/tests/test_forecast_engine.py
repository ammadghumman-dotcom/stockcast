"""DB-backed: full run on the seed org, persistence, idempotent retry, API, scoping."""

from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.forecast.engine import run_forecast
from app.models import Forecast, ForecastAccuracy, ForecastRun
from scripts.seed import DEMO_ORG_ID, seed

AS_OF = date(2026, 9, 30)


@pytest.fixture
def seeded_run(db, monkeypatch):
    monkeypatch.setattr("app.forecast.router.chronos_available", lambda: False)
    seed(db, days=200, today=AS_OF)
    run = ForecastRun(org_id=DEMO_ORG_ID, trigger="manual", horizon_days=90)
    db.add(run)
    db.flush()
    return run_forecast(db, run, as_of=AS_OF)


def test_run_on_seed_reports_wape_and_persists(db, seeded_run, capsys) -> None:
    run = seeded_run
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


def test_rerun_same_run_is_idempotent(db, seeded_run) -> None:
    run = run_forecast(db, seeded_run, as_of=AS_OF)
    assert run.status == "success"
    assert (
        db.scalar(select(func.count()).select_from(Forecast).where(Forecast.run_id == run.id))
        == 1800
    )


def test_forecast_api(client, db, seeded_run) -> None:
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


def test_forecast_is_org_scoped(client, db, seeded_run, other_headers) -> None:
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
