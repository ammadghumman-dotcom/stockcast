"""Onboarding checklist + sample-data mode."""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.billing.plans import usage_for
from app.models import (
    BomLine,
    Channel,
    ForecastRun,
    Location,
    Product,
    ProductCategory,
    ProductType,
    Promotion,
    PurchaseOrder,
    PurchaseOrderLine,
    SalesDaily,
    Supplier,
)
from app.services import sample_data


def _count(db, model, org) -> int:
    return db.scalar(select(func.count()).select_from(model).where(model.org_id == org.id))


def test_new_workspace_has_open_checklist(client, headers) -> None:
    r = client.get("/onboarding", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert [s["key"] for s in body["steps"]] == ["connect", "bom", "suppliers", "forecast", "po"]
    assert body["done"] == 0 and body["total"] == 5 and not body["complete"]
    assert body["sample_data"] is False


def test_sample_data_loads_once_and_does_not_count(client, db, org, headers) -> None:
    r = client.post("/sample-data", headers=headers)
    assert r.status_code == 201 and r.json() == {"loaded": True}
    assert client.post("/sample-data", headers=headers).json() == {"loaded": False}

    assert _count(db, Product, org) == 23
    assert _count(db, Channel, org) == 3
    assert (
        db.scalar(select(func.count()).select_from(SalesDaily).where(SalesDaily.org_id == org.id))
        > 1000
    )
    skus = db.scalars(select(Product.sku).where(Product.org_id == org.id)).all()
    assert all(s.startswith("SAMPLE-") for s in skus)

    body = client.get("/onboarding", headers=headers).json()
    assert body["sample_data"] is True
    assert body["done"] == 0  # sample rows never tick the user's own steps
    assert usage_for(db, org.id) == {"channels": 0, "skus": 0}  # nor count toward plan limits


def test_sample_data_is_workspace_scoped(
    client, db, org, other_org, headers, other_headers
) -> None:
    client.post("/sample-data", headers=headers)
    assert client.get("/onboarding", headers=other_headers).json()["sample_data"] is False
    assert _count(db, Product, other_org) == 0


def test_remove_sample_data_keeps_real_data(client, db, org, headers) -> None:
    client.post("/sample-data", headers=headers)
    real = Product(org_id=org.id, sku="REAL-1", name="My candle", type=ProductType.finished)
    db.add(real)
    db.flush()
    sample_supplier = db.scalar(select(Supplier).where(Supplier.org_id == org.id))
    wax = db.scalar(select(Product).where(Product.sku == "SAMPLE-RM-WAX-SOY"))
    po = PurchaseOrder(org_id=org.id, supplier_id=sample_supplier.id, number="PO-1")
    db.add(po)
    db.flush()
    db.add(
        PurchaseOrderLine(
            purchase_order_id=po.id, product_id=wax.id, qty=Decimal(1), unit_price=Decimal(1)
        )
    )
    db.flush()

    r = client.delete("/sample-data", headers=headers)
    assert r.status_code == 200 and r.json() == {"removed_products": 23}
    db.expire_all()
    for model in (Channel, Supplier, Location, ProductCategory, Promotion, PurchaseOrder):
        assert _count(db, model, org) == 0, model.__name__
    assert [p.sku for p in db.scalars(select(Product).where(Product.org_id == org.id))] == [
        "REAL-1"
    ]
    assert client.get("/onboarding", headers=headers).json()["sample_data"] is False


def test_viewer_cannot_load_or_remove(client, headers) -> None:
    viewer = {**headers, "X-Role": "viewer"}
    assert client.post("/sample-data", headers=viewer).status_code == 403
    assert client.delete("/sample-data", headers=viewer).status_code == 403


def test_checklist_ticks_real_progress(client, db, org, headers) -> None:
    candle = Product(org_id=org.id, sku="C1", name="Candle", type=ProductType.finished)
    wax = Product(org_id=org.id, sku="W1", name="Wax", type=ProductType.raw_material, unit="g")
    supplier = Supplier(org_id=org.id, name="Wax Co")
    db.add_all([candle, wax, supplier])
    db.flush()
    db.add(
        BomLine(
            org_id=org.id,
            parent_product_id=candle.id,
            component_product_id=wax.id,
            qty_per_unit=Decimal(200),
        )
    )
    db.add(ForecastRun(org_id=org.id, status="success"))
    po = PurchaseOrder(org_id=org.id, supplier_id=supplier.id, number="PO-9")
    db.add(po)
    db.flush()
    db.add(
        PurchaseOrderLine(
            purchase_order_id=po.id,
            product_id=wax.id,
            qty=Decimal(1000),
            unit_price=Decimal("0.01"),
        )
    )
    db.flush()
    body = client.get("/onboarding", headers=headers).json()
    assert body["complete"] is True and body["done"] == 5


def test_build_matches_demo_sizes(db, org) -> None:
    from app.models import Region

    region = Region(org_id=org.id, code="US", name="US", currency="USD")
    db.add(region)
    db.flush()
    stats = sample_data.build(db, org.id, region=region, days=30, today=date(2026, 1, 31))
    assert stats["products"] == 23 and stats["bom_lines"] == 3
