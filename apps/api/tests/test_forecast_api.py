"""Forecast API edge cases that need no prior run (function-scoped fixtures)."""


def test_trigger_endpoint_runs_inline_in_eager_mode(client, db, headers, org, monkeypatch) -> None:
    monkeypatch.setattr("app.forecast.router.chronos_available", lambda: False)
    r = client.post("/forecast-runs", params={"horizon": 14}, headers=headers)
    assert r.status_code == 202, r.text
    run = r.json()
    assert run["status"] == "success" and run["skus_total"] == 0 and run["horizon_days"] == 14
