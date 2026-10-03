"""CSV connector: parsing, column mapping, row errors, and exact round-trip of the seed."""

import io
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.ingest.csv_connector import parse_csv
from app.models import BomLine, InventoryLevel, Product, SalesDaily
from scripts.seed import DEMO_ORG_ID, seed


def _files(**kw: str) -> dict:
    return {k: (f"{k}.csv", io.BytesIO(v.encode()), "text/csv") for k, v in kw.items()}


# ---- parser ----
def test_parse_with_mapping_and_row_errors() -> None:
    csv_text = "Item Code,Qty,Sold On\nA,2,2026-01-05\nB,x,2026-01-06\n,,\nC,1,not-a-date\n"
    recs, errs = parse_csv(
        "sales", csv_text.encode(), {"sku": "Item Code", "units": "Qty", "date": "Sold On"}
    )
    assert [(r.sku, r.units, r.date) for r in recs] == [("A", 2, date(2026, 1, 5))]
    assert [e.row for e in errs] == [2, 4]
    assert "units" in errs[0].message and "date" in errs[1].message


def test_parse_missing_required_column() -> None:
    import pytest

    from app.ingest.csv_connector import CsvParseError

    with pytest.raises(CsvParseError, match="missing required"):
        parse_csv("products", b"name,price\nA,1\n")


def test_parse_is_case_insensitive_and_handles_bom() -> None:
    recs, errs = parse_csv("products", "﻿SKU,Name,Type\nA,Thing,raw_material\n".encode())
    assert not errs and recs[0].sku == "A" and recs[0].type == "raw_material"


# ---- endpoint ----
def test_import_products_then_bom_then_sales(client: TestClient, headers: dict) -> None:
    r = client.post(
        "/imports",
        files=_files(
            products="sku,name,type,unit_cost,unit,category\n"
            "CND,Candle,finished,4.2,unit,Candles\nWAX,Soy Wax,raw_material,0.004,g,\n",
            bom="parent_sku,component_sku,qty_per_unit\nCND,WAX,200\n",
            sales="date,sku,units,revenue\n2026-03-01,CND,3,42\n2026-03-01,CND,1,14\n2026-03-02,NOPE,1,1\n",
        ),
        headers=headers,
    )
    assert r.status_code == 200, r.text
    results = {x["kind"]: x for x in r.json()["results"]}
    assert results["products"]["inserted"] == 2
    assert results["bom"]["inserted"] == 1
    # sales: 3 rows received, 2 aggregated into one day, 1 unknown sku reported
    assert results["sales"]["received"] == 3 and results["sales"]["inserted"] == 1
    assert results["sales"]["errors"][0]["row"] == 3
    assert "NOPE" in results["sales"]["errors"][0]["message"]

    # re-import updates instead of duplicating
    r = client.post(
        "/imports",
        files=_files(products="sku,name,type\nCND,Candle v2,finished\n"),
        headers=headers,
    )
    res = r.json()["results"][0]
    assert res["updated"] == 1 and res["inserted"] == 0
    assert client.get("/products", headers=headers).json()[0]["name"] in ("Candle v2", "Soy Wax")


def test_import_strict_rolls_back_on_row_error(client: TestClient, headers: dict) -> None:
    r = client.post(
        "/imports",
        data={"strict": "true"},
        files=_files(products="sku,name,type\nOK,Fine,finished\n,Missing sku,finished\n"),
        headers=headers,
    )
    assert r.status_code == 422
    assert client.get("/products", headers=headers).json() == []


def test_import_no_files_422(client: TestClient, headers: dict) -> None:
    assert client.post("/imports", headers=headers).status_code == 422


# ---- round trip ----
def test_seed_round_trips_through_csv_exactly(client: TestClient, db, other_headers: dict) -> None:
    """Export the seeded demo org, import into another org, compare row-for-row."""
    seed(db, days=90, today=date(2026, 9, 30))
    src = {"X-Org-Id": str(DEMO_ORG_ID)}

    exported = {
        k: client.get(f"/exports/{k}.csv", headers=src).text
        for k in ("products", "bom", "inventory", "sales")
    }
    assert exported["products"].splitlines()[0] == "sku,name,type,unit_cost,unit,category"

    r = client.post("/imports", files=_files(**exported), headers=other_headers)
    assert r.status_code == 200, r.text
    for res in r.json()["results"]:
        assert res["errors"] == [], res

    dst_id = other_headers["X-Org-Id"]

    def count(model, org_id):
        return db.scalar(select(func.count()).select_from(model).where(model.org_id == org_id))

    assert count(Product, DEMO_ORG_ID) == count(Product, dst_id) == 23
    assert count(BomLine, DEMO_ORG_ID) == count(BomLine, dst_id) == 3
    assert count(InventoryLevel, DEMO_ORG_ID) == count(InventoryLevel, dst_id)

    # sales: the seed has 2 channels; the CSV import lands on one csv channel, so compare the
    # per-(date, sku) totals, which must match exactly.
    def totals(org_id):
        q = (
            select(
                SalesDaily.date,
                Product.sku,
                func.sum(SalesDaily.units),
                func.sum(SalesDaily.revenue),
            )
            .join(Product, Product.id == SalesDaily.product_id)
            .where(SalesDaily.org_id == org_id)
            .group_by(SalesDaily.date, Product.sku)
        )
        return {(d, s): (Decimal(u), Decimal(rv)) for d, s, u, rv in db.execute(q)}

    assert totals(DEMO_ORG_ID) == totals(dst_id)

    # and exporting the copy yields byte-identical products/bom/inventory CSVs
    for k in ("products", "bom", "inventory"):
        assert client.get(f"/exports/{k}.csv", headers=other_headers).text == exported[k]
