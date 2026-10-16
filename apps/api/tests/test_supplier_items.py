"""Supplier items screen (staging CAT-04): price, pack size and lead time per product."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.models import AuditLog


def _setup(client: TestClient, headers: dict) -> tuple[dict, dict]:
    sup = client.post(
        "/suppliers", json={"name": "Wax Co", "lead_time_days": 21}, headers=headers
    ).json()
    prod = client.post(
        "/products",
        json={"sku": "WAX-SOY", "name": "Soy wax", "type": "raw_material", "unit": "kg"},
        headers=headers,
    ).json()
    return sup, prod


def test_supplier_items_crud_and_effective_lead_time(client: TestClient, db, org, headers) -> None:
    sup, prod = _setup(client, headers)
    url = f"/suppliers/{sup['id']}/items"
    r = client.post(
        url, json={"product_id": prod["id"], "price": "3.25", "pack_size": 20}, headers=headers
    )
    assert r.status_code == 201, r.text
    item = r.json()
    assert item["sku"] == "WAX-SOY" and item["unit"] == "kg"
    assert item["lead_time_days"] is None and item["effective_lead_time_days"] == 21

    # same product twice for one supplier -> readable 409
    dup = client.post(url, json={"product_id": prod["id"], "price": "1"}, headers=headers)
    assert dup.status_code == 409 and "WAX-SOY" in dup.json()["detail"]

    r = client.patch(
        f"{url}/{item['id']}", json={"lead_time_days": 7, "price": "3.10"}, headers=headers
    )
    assert r.status_code == 200
    assert r.json()["effective_lead_time_days"] == 7 and r.json()["price"] == "3.1000"
    # explicit null clears the override
    r = client.patch(f"{url}/{item['id']}", json={"lead_time_days": None}, headers=headers)
    assert r.json()["lead_time_days"] is None and r.json()["effective_lead_time_days"] == 21
    assert (
        client.patch(f"{url}/{item['id']}", json={"price": None}, headers=headers).status_code
        == 422
    )
    assert (
        client.patch(f"{url}/{item['id']}", json={"pack_size": 0}, headers=headers).status_code
        == 422
    )

    assert [i["id"] for i in client.get(url, headers=headers).json()] == [item["id"]]
    assert client.delete(f"{url}/{item['id']}", headers=headers).status_code == 204
    assert client.get(url, headers=headers).json() == []

    actions = {a.action for a in db.query(AuditLog).filter_by(org_id=org.id)}
    assert {"supplier_item.create", "supplier_item.update", "supplier_item.delete"} <= actions


def test_supplier_items_are_org_scoped_and_admin_only(
    client: TestClient, headers: dict, other_headers: dict
) -> None:
    sup, prod = _setup(client, headers)
    url = f"/suppliers/{sup['id']}/items"
    item = client.post(url, json={"product_id": prod["id"], "price": "2"}, headers=headers).json()

    # another org can neither see nor touch the supplier's items
    assert client.get(url, headers=other_headers).status_code == 404
    assert (
        client.patch(f"{url}/{item['id']}", json={"price": "0"}, headers=other_headers).status_code
        == 404
    )
    # and cannot point its own supplier at our product
    theirs = client.post("/suppliers", json={"name": "Rival"}, headers=other_headers).json()
    r = client.post(
        f"/suppliers/{theirs['id']}/items",
        json={"product_id": prod["id"], "price": "1"},
        headers=other_headers,
    )
    assert r.status_code == 422

    viewer = {**headers, "X-Role": "viewer"}
    assert client.get(url, headers=viewer).status_code == 200
    assert client.delete(f"{url}/{item['id']}", headers=viewer).status_code == 403
