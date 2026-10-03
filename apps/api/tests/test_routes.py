import uuid
from decimal import Decimal

from fastapi.testclient import TestClient


def _product(client: TestClient, headers: dict, sku: str, ptype: str = "finished") -> dict:
    r = client.post(
        "/products", json={"sku": sku, "name": f"Product {sku}", "type": ptype}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()


# ---- products ----
def test_product_crud(client: TestClient, headers: dict) -> None:
    p = _product(client, headers, "CND-1")
    assert Decimal(p["unit_cost"]) == 0 and p["type"] == "finished"

    r = client.patch(f"/products/{p['id']}", json={"unit_cost": "4.25"}, headers=headers)
    assert r.status_code == 200 and Decimal(r.json()["unit_cost"]) == Decimal("4.25")

    r = client.get("/products", headers=headers)
    assert [x["sku"] for x in r.json()] == ["CND-1"]


def test_product_sku_unique_per_org(client: TestClient, headers: dict, other_headers: dict) -> None:
    _product(client, headers, "DUP")
    assert (
        client.post(
            "/products", json={"sku": "DUP", "name": "again", "type": "finished"}, headers=headers
        ).status_code
        == 409
    )
    # same SKU is fine in a different org
    assert (
        client.post(
            "/products",
            json={"sku": "DUP", "name": "ok", "type": "finished"},
            headers=other_headers,
        ).status_code
        == 201
    )


def test_product_validation(client: TestClient, headers: dict) -> None:
    r = client.post("/products", json={"sku": "", "name": "x", "type": "finished"}, headers=headers)
    assert r.status_code == 422
    r = client.post("/products", json={"sku": "N", "name": "x", "type": "widget"}, headers=headers)
    assert r.status_code == 422
    assert client.get(f"/products/{uuid.uuid4()}", headers=headers).status_code == 404


# ---- suppliers ----
def test_supplier_crud(client: TestClient, headers: dict) -> None:
    r = client.post("/suppliers", json={"name": "Wax Co", "lead_time_days": 21}, headers=headers)
    assert r.status_code == 201
    s = r.json()
    assert s["moq"] == 1 and s["currency"] == "USD"
    r = client.patch(f"/suppliers/{s['id']}", json={"moq": 500}, headers=headers)
    assert r.json()["moq"] == 500
    assert client.get(f"/suppliers/{s['id']}", headers=headers).json()["lead_time_days"] == 21


# ---- locations ----
def test_location_crud(client: TestClient, headers: dict) -> None:
    r = client.post("/locations", json={"name": "FBA", "kind": "3pl"}, headers=headers)
    assert r.status_code == 201
    loc = r.json()
    r = client.patch(f"/locations/{loc['id']}", json={"is_default": True}, headers=headers)
    assert r.json()["is_default"] is True
    assert len(client.get("/locations", headers=headers).json()) == 1


# ---- bom lines ----
def test_bom_line_crud_and_constraints(client: TestClient, headers: dict) -> None:
    candle = _product(client, headers, "CND-VAN")
    wax = _product(client, headers, "RM-WAX", "raw_material")
    jar = _product(client, headers, "RM-JAR", "raw_material")

    r = client.post(
        "/bom-lines",
        json={
            "parent_product_id": candle["id"],
            "component_product_id": wax["id"],
            "qty_per_unit": "200",
        },
        headers=headers,
    )
    assert r.status_code == 201, r.text
    line = r.json()
    assert Decimal(line["qty_per_unit"]) == 200

    client.post(
        "/bom-lines",
        json={
            "parent_product_id": candle["id"],
            "component_product_id": jar["id"],
            "qty_per_unit": "1",
        },
        headers=headers,
    )
    r = client.get("/bom-lines", params={"parent_product_id": candle["id"]}, headers=headers)
    assert len(r.json()) == 2

    r = client.patch(f"/bom-lines/{line['id']}", json={"qty_per_unit": "210"}, headers=headers)
    assert Decimal(r.json()["qty_per_unit"]) == 210

    # duplicate pair -> 409 (unique constraint)
    r = client.post(
        "/bom-lines",
        json={
            "parent_product_id": candle["id"],
            "component_product_id": wax["id"],
            "qty_per_unit": "5",
        },
        headers=headers,
    )
    assert r.status_code == 409

    # self-reference -> 409 (check constraint)
    r = client.post(
        "/bom-lines",
        json={
            "parent_product_id": candle["id"],
            "component_product_id": candle["id"],
            "qty_per_unit": "1",
        },
        headers=headers,
    )
    assert r.status_code == 409

    # zero qty -> 422 (pydantic)
    r = client.post(
        "/bom-lines",
        json={
            "parent_product_id": candle["id"],
            "component_product_id": jar["id"],
            "qty_per_unit": "0",
        },
        headers=headers,
    )
    assert r.status_code == 422
