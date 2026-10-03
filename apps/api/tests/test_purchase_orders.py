"""PO drafting from recommendations, CSV/PDF export, send via Resend (mocked), receive."""

from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.models import InventoryLevel, PlanningRun
from app.planning.engine import run_planning
from tests.conftest import PLANNING_AS_OF as AS_OF


@pytest.fixture
def planned(db, org, candle_world):
    run = PlanningRun(org_id=org.id)
    db.add(run)
    db.flush()
    run_planning(db, run, as_of=AS_OF)
    return run


def test_draft_groups_by_supplier_and_links_recommendations(client, db, headers, planned) -> None:
    r = client.post("/purchase-orders/from-recommendations", json={}, headers=headers)
    assert r.status_code == 201, r.text
    pos = r.json()
    assert len(pos) == 2  # Pacific Wax, ClearGlass
    by_name = {p["supplier_name"]: p for p in pos}
    wax = by_name["Pacific Wax"]
    assert len(wax["lines"]) == 1 and Decimal(wax["lines"][0]["qty"]) == 75_000
    assert Decimal(wax["lines"][0]["unit_price"]) == Decimal(
        "0.004"
    )  # supplier price, not unit_cost
    assert Decimal(wax["total"]) == Decimal("300.00")
    glass = by_name["ClearGlass"]
    assert {ln["sku"] for ln in glass["lines"]} == {"JAR", "WICK"}
    assert all(p["status"] == "draft" for p in pos)
    assert wax["number"].startswith("PO-")

    # recommendations now reference their PO; drafting again yields nothing new
    recs = client.get("/recommendations", params={"action": "reorder"}, headers=headers).json()
    assert all(x["po_id"] for x in recs)
    assert (
        client.post("/purchase-orders/from-recommendations", json={}, headers=headers).json() == []
    )


def test_draft_subset_and_missing_supplier(client, db, headers, planned, candle_world) -> None:
    recs = client.get("/recommendations", params={"action": "reorder"}, headers=headers).json()
    jar = next(x for x in recs if x["sku"] == "JAR")
    r = client.post(
        "/purchase-orders/from-recommendations",
        json={"recommendation_ids": [jar["id"]]},
        headers=headers,
    )
    assert r.status_code == 201 and len(r.json()) == 1 and len(r.json()[0]["lines"]) == 1

    # a reorder without any supplier is rejected with the SKU named
    from app.models import Recommendation

    wick = db.scalar(
        select(Recommendation).where(
            Recommendation.run_id == planned.id,
            Recommendation.product_id == candle_world["products"]["WICK"].id,
        )
    )
    wick.supplier_id = None
    db.flush()
    r = client.post(
        "/purchase-orders/from-recommendations",
        json={"recommendation_ids": [str(wick.id)]},
        headers=headers,
    )
    assert r.status_code == 422 and "WICK" in r.json()["detail"]


def test_csv_and_pdf_exports(client, db, headers, planned) -> None:
    pos = client.post("/purchase-orders/from-recommendations", json={}, headers=headers).json()
    po = next(p for p in pos if p["supplier_name"] == "ClearGlass")
    csv_text = client.get(f"/purchase-orders/{po['id']}/export.csv", headers=headers).text
    lines = csv_text.strip().splitlines()
    assert lines[0] == "line,sku,name,qty,unit,unit_price,line_total"
    assert any(",JAR,Glass Jar,500,unit,0.6000,300.00" in ln for ln in lines)
    pdf = client.get(f"/purchase-orders/{po['id']}/export.pdf", headers=headers)
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-" and len(pdf.content) > 800


def test_send_via_resend_and_receive_into_inventory(
    client, db, headers, planned, monkeypatch, candle_world
) -> None:
    pos = client.post("/purchase-orders/from-recommendations", json={}, headers=headers).json()
    po = next(p for p in pos if p["supplier_name"] == "ClearGlass")

    # not configured -> clear error, nothing sent
    r = client.post(f"/purchase-orders/{po['id']}/send", headers=headers)
    assert r.status_code == 422 and "RESEND_API_KEY" in r.json()["detail"]

    sent = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        sent["url"] = str(request.url)
        sent["payload"] = _json.loads(request.content)
        sent["headers"] = dict(request.headers)
        return httpx.Response(200, json={"id": "email_123"})

    monkeypatch.setattr("app.config.settings.resend_api_key", "re_test")
    monkeypatch.setattr(
        "app.planning.po._http_client", lambda: httpx.Client(transport=httpx.MockTransport(handler))
    )
    r = client.post(f"/purchase-orders/{po['id']}/send", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "sent" and r.json()["sent_at"]
    assert sent["url"] == "https://api.resend.com/emails"
    assert sent["headers"]["authorization"] == "Bearer re_test"
    assert sent["payload"]["to"] == ["po@clearglass.test"]
    assert {a["filename"].rsplit(".", 1)[1] for a in sent["payload"]["attachments"]} == {
        "pdf",
        "csv",
    }
    assert "500 unit x JAR" in sent["payload"]["text"]

    # sending twice is refused
    assert client.post(f"/purchase-orders/{po['id']}/send", headers=headers).status_code == 422

    # receive: inventory goes up, PO becomes received
    jar = candle_world["products"]["JAR"]
    before = db.scalar(select(InventoryLevel.on_hand).where(InventoryLevel.product_id == jar.id))
    r = client.post(f"/purchase-orders/{po['id']}/receive", headers=headers)
    assert r.status_code == 200 and r.json()["status"] == "received"
    db.expire_all()
    after = db.scalar(select(InventoryLevel.on_hand).where(InventoryLevel.product_id == jar.id))
    assert after - before == 500


def test_partial_receive_keeps_po_open(client, db, headers, planned) -> None:
    pos = client.post("/purchase-orders/from-recommendations", json={}, headers=headers).json()
    po = next(p for p in pos if p["supplier_name"] == "ClearGlass")
    client.post(f"/purchase-orders/{po['id']}/mark-sent", headers=headers)
    jar_line = next(ln for ln in po["lines"] if ln["sku"] == "JAR")
    r = client.post(
        f"/purchase-orders/{po['id']}/receive",
        json={"lines": {jar_line["id"]: "200"}},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "sent"  # still open
    assert Decimal(next(ln for ln in body["lines"] if ln["sku"] == "JAR")["received_qty"]) == 200
    # draft cannot be received
    assert client.post(f"/purchase-orders/{po['id']}/receive", headers=headers).status_code == 200


def test_po_scoping(client, db, headers, other_headers, planned) -> None:
    pos = client.post("/purchase-orders/from-recommendations", json={}, headers=headers).json()
    pid = pos[0]["id"]
    assert client.get(f"/purchase-orders/{pid}", headers=other_headers).status_code == 404
    assert client.get("/purchase-orders", headers=other_headers).json() == []
    assert client.get("/recommendations", headers=other_headers).json() == []
    assert (
        client.post(
            "/purchase-orders/from-recommendations", json={}, headers=other_headers
        ).status_code
        == 404
    )


def test_planning_settings_and_product_overrides(client, headers, other_headers, db, org) -> None:
    s = client.get("/planning-settings", headers=headers).json()
    assert float(s["service_level"]) == 0.95 and s["target_cover_days"] == 30
    r = client.patch(
        "/planning-settings",
        json={"target_cover_days": 45, "service_level": "0.98"},
        headers=headers,
    )
    assert r.status_code == 200 and r.json()["target_cover_days"] == 45
    assert client.get("/planning-settings", headers=other_headers).json()["target_cover_days"] == 30

    p = client.post(
        "/products", json={"sku": "X", "name": "X", "type": "finished"}, headers=headers
    ).json()
    r = client.patch(
        f"/products/{p['id']}/planning",
        json={"lead_time_days": 12, "target_cover_days": 10},
        headers=headers,
    )
    assert r.status_code == 200 and r.json()["lead_time_days"] == 12
    assert (
        client.patch(
            f"/products/{p['id']}/planning", json={"lead_time_days": 1}, headers=other_headers
        ).status_code
        == 404
    )


def test_planning_run_endpoint_and_recommendation_filters(
    client, headers, db, org, candle_world
) -> None:
    r = client.post("/planning-runs", headers=headers)
    assert r.status_code == 202, r.text
    run = r.json()
    assert run["status"] == "success" and run["products_total"] == 4
    assert run["n_reorder"] == 3 and run["n_produce"] == 1
    at_risk = client.get("/recommendations", params={"health": "at_risk"}, headers=headers).json()
    assert {x["sku"] for x in at_risk} == {"CND", "WAX", "JAR"}
    produce = client.get("/recommendations", params={"action": "produce"}, headers=headers).json()
    assert (
        len(produce) == 1 and produce[0]["sku"] == "CND" and "Produce 300" in produce[0]["reason"]
    )
    one = client.get(f"/recommendations/{produce[0]['id']}", headers=headers).json()
    assert one["product_name"] == "Vanilla Candle"
    assert client.get("/planning-runs", headers=headers).json()[0]["id"] == run["id"]
