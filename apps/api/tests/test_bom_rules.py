"""BOM loops are rejected on write and caught at planning time (staging bugs #17 and #24)."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.models import BomLine, PlanningRun
from app.planning.engine import PlanningError, run_planning
from app.services import bom as bom_rules
from app.services.errors import GENERIC, run_error


def _product(client: TestClient, headers: dict, sku: str, ptype: str = "finished") -> dict:
    r = client.post(
        "/products", json={"sku": sku, "name": f"Product {sku}", "type": ptype}, headers=headers
    )
    assert r.status_code == 201, r.text
    return r.json()


def _line(client: TestClient, headers: dict, parent: dict, comp: dict, qty: str = "1"):
    return client.post(
        "/bom-lines",
        json={
            "parent_product_id": parent["id"],
            "component_product_id": comp["id"],
            "qty_per_unit": qty,
        },
        headers=headers,
    )


def test_api_rejects_loops_and_self_reference(client: TestClient, headers: dict) -> None:
    candle = _product(client, headers, "CND")
    kit = _product(client, headers, "KIT")
    wax = _product(client, headers, "WAX", "raw_material")
    assert _line(client, headers, candle, wax, "0.2").status_code == 201
    assert _line(client, headers, kit, candle).status_code == 201

    direct = _line(client, headers, wax, candle)  # wax -> candle -> wax
    assert direct.status_code == 422 and "loop" in direct.json()["detail"]
    deep = _line(client, headers, wax, kit)  # wax -> kit -> candle -> wax
    assert deep.status_code == 422

    self_ref = _line(client, headers, candle, candle)
    assert self_ref.status_code == 422
    assert "Failing row" not in self_ref.text  # no database error text leaks out


def test_delete_bom_line_is_admin_only(client: TestClient, headers: dict) -> None:
    candle = _product(client, headers, "CND")
    jar = _product(client, headers, "JAR", "raw_material")
    line = _line(client, headers, candle, jar).json()

    viewer = {**headers, "X-Role": "viewer"}
    assert client.delete(f"/bom-lines/{line['id']}", headers=viewer).status_code == 403
    assert client.delete(f"/bom-lines/{line['id']}", headers=headers).status_code == 204
    assert client.get(f"/bom-lines/{line['id']}", headers=headers).status_code == 404


def test_csv_import_skips_loop_rows_with_a_row_error(client: TestClient, headers: dict) -> None:
    products = "sku,name,type\nCND,Candle,finished\nWAX,Wax,raw_material\nJAR,Jar,raw_material\n"
    bom = "parent_sku,component_sku,qty_per_unit\nCND,WAX,0.2\nCND,JAR,1\nWAX,CND,1\nCND,WAX,0.25\n"
    r = client.post(
        "/imports",
        files={
            "products": ("products.csv", products, "text/csv"),
            "bom": ("bom.csv", bom, "text/csv"),
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    res = next(x for x in r.json()["results"] if x["kind"] == "bom")
    assert res["inserted"] == 3  # the re-stated CND,WAX line is an update, not a loop
    assert [e["row"] for e in res["errors"]] == [3]
    assert "loop" in res["errors"][0]["message"]


def test_planning_names_an_existing_loop(db, org, candle_world) -> None:
    p = candle_world["products"]
    db.add(
        BomLine(
            org_id=org.id,
            parent_product_id=p["WAX"].id,
            component_product_id=p["CND"].id,
            qty_per_unit=Decimal(1),
        )
    )
    db.flush()
    run = PlanningRun(org_id=org.id)
    db.add(run)
    db.flush()
    with pytest.raises(PlanningError):
        run_planning(db, run)
    assert run.status == "failed"
    assert "loop" in run.error and "CND" in run.error and "WAX" in run.error


def test_find_cycle_and_creates_cycle() -> None:
    import uuid

    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    g = {a: {b}, b: {c}}
    assert bom_rules.find_cycle(g) is None
    assert bom_rules.creates_cycle(g, c, a) and not bom_rules.creates_cycle(g, a, c)
    g[c] = {a}
    loop = bom_rules.find_cycle(g)
    assert loop is not None and loop[0] == loop[-1] and set(loop) == {a, b, c}


def test_run_error_hides_database_details() -> None:
    exc = IntegrityError("INSERT INTO recommendations ...", {"qty": 1e20}, Exception("overflow"))
    assert run_error(exc) == GENERIC
    assert run_error(RuntimeError("no successful forecast run yet")).startswith("no successful")
