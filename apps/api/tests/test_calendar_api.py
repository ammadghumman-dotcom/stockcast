"""Calendar / promotion / simulate API tests (function-scoped fixtures, no forecast run)."""


def test_calendar_endpoints(client, db, headers, other_headers) -> None:
    r = client.post(
        "/regions",
        json={"code": "UK", "name": "United Kingdom", "currency": "GBP"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    region = r.json()
    events = client.get(
        "/holiday-events", params={"region_id": region["id"]}, headers=headers
    ).json()
    names = {e["name"] for e in events}
    assert {"Christmas", "Black Friday", "Mother's Day"} <= names
    assert all(e["source"] == "builtin" for e in events)
    assert client.get("/holiday-events", headers=other_headers).json() == []

    # custom event + validation
    r = client.post(
        "/holiday-events",
        json={
            "region_id": region["id"],
            "name": "Brand Day",
            "start_date": "2026-03-01",
            "end_date": "2026-03-07",
        },
        headers=headers,
    )
    assert r.status_code == 201 and r.json()["source"] == "custom"
    r = client.post(
        "/holiday-events",
        json={
            "region_id": region["id"],
            "name": "Bad",
            "start_date": "2026-03-09",
            "end_date": "2026-03-07",
        },
        headers=headers,
    )
    assert r.status_code == 422
    # cannot attach to another org's region
    r = client.post(
        "/holiday-events",
        json={
            "region_id": region["id"],
            "name": "X",
            "start_date": "2026-03-01",
            "end_date": "2026-03-02",
        },
        headers=other_headers,
    )
    assert r.status_code == 422

    # promotions CRUD + scope validation
    r = client.post(
        "/promotions",
        json={
            "name": "Spring",
            "type": "discount",
            "start_date": "2026-04-01",
            "end_date": "2026-04-05",
            "discount_pct": "15",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    r = client.post(
        "/promotions",
        json={
            "name": "Bad",
            "type": "discount",
            "scope": "category",
            "start_date": "2026-04-01",
            "end_date": "2026-04-05",
        },
        headers=headers,
    )
    assert r.status_code == 422
    assert client.get("/promotions", headers=other_headers).json() == []


def test_simulate_without_run_is_empty(client, headers) -> None:
    r = client.post(
        "/forecasts/simulate",
        json={"name": "x", "type": "email", "start_date": "2026-01-01", "end_date": "2026-01-02"},
        headers=headers,
    )
    assert r.status_code == 200 and r.json()["run_id"] is None and r.json()["products"] == []
