import uuid

import pytest
from fastapi.testclient import TestClient

RESOURCES = [
    ("/products", {"sku": "SKU-1", "name": "Thing", "type": "finished", "unit_cost": "1.5"}),
    ("/suppliers", {"name": "Acme Supply", "lead_time_days": 10, "moq": 5}),
    ("/locations", {"name": "Main WH"}),
    ("/channels", {"name": "Uploads", "type": "csv"}),
    (
        "/promotions",
        {"name": "Promo", "type": "email", "start_date": "2026-01-01", "end_date": "2026-01-03"},
    ),
]


def test_missing_org_header_is_401(client: TestClient) -> None:
    assert client.get("/products").status_code == 401


def test_unknown_org_is_401(client: TestClient) -> None:
    r = client.get("/products", headers={"X-Org-Id": str(uuid.uuid4())})
    assert r.status_code == 401


def test_malformed_org_header_is_401(client: TestClient) -> None:
    assert client.get("/products", headers={"X-Org-Id": "nope"}).status_code == 401


@pytest.mark.parametrize(("path", "payload"), RESOURCES)
def test_rows_never_leak_across_orgs(
    client: TestClient, headers: dict, other_headers: dict, path: str, payload: dict
) -> None:
    created = client.post(path, json=payload, headers=headers)
    assert created.status_code == 201, created.text
    obj_id = created.json()["id"]

    # Owner sees it
    assert client.get(f"{path}/{obj_id}", headers=headers).status_code == 200
    assert [o["id"] for o in client.get(path, headers=headers).json()] == [obj_id]

    # Other org: not in list, 404 on get, 404 on update
    assert client.get(path, headers=other_headers).json() == []
    assert client.get(f"{path}/{obj_id}", headers=other_headers).status_code == 404
    assert (
        client.patch(f"{path}/{obj_id}", json={"name": "hijack"}, headers=other_headers).status_code
        == 404
    )
    # ...and the owner's row is untouched
    assert client.get(f"{path}/{obj_id}", headers=headers).json()["name"] == payload["name"]


def test_bom_cannot_reference_another_orgs_product(
    client: TestClient, headers: dict, other_headers: dict
) -> None:
    mine = client.post(
        "/products", json={"sku": "A", "name": "Mine", "type": "finished"}, headers=headers
    ).json()
    theirs = client.post(
        "/products",
        json={"sku": "B", "name": "Theirs", "type": "raw_material"},
        headers=other_headers,
    ).json()
    r = client.post(
        "/bom-lines",
        json={
            "parent_product_id": mine["id"],
            "component_product_id": theirs["id"],
            "qty_per_unit": "2",
        },
        headers=headers,
    )
    assert r.status_code == 422


def test_product_cannot_use_another_orgs_category(
    client: TestClient, db, headers: dict, other_org
) -> None:
    from app.models import ProductCategory

    cat = ProductCategory(org_id=other_org.id, name="Secret")
    db.add(cat)
    db.flush()
    r = client.post(
        "/products",
        json={"sku": "C", "name": "X", "type": "finished", "category_id": str(cat.id)},
        headers=headers,
    )
    assert r.status_code == 422
