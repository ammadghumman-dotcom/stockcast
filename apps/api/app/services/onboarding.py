"""First-run checklist: what a new workspace has done with its *own* data (sample rows excluded)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.models import (
    BomLine,
    Channel,
    ForecastRun,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
)
from app.services import sample_data


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    hint: str
    href: str
    done: bool


def _any(db: Session, clause) -> bool:  # type: ignore[no-untyped-def]
    return bool(db.scalar(select(exists().where(clause))))


def status(db: Session, org_id: uuid.UUID) -> tuple[list[Step], bool]:
    real_product = (Product.org_id == org_id) & Product.is_sample.is_(False)
    connected = _any(db, (Channel.org_id == org_id) & Channel.is_sample.is_(False)) or _any(
        db, real_product
    )
    bom = bool(
        db.scalar(
            select(
                exists()
                .where(BomLine.org_id == org_id, BomLine.parent_product_id == Product.id)
                .where(Product.is_sample.is_(False))
            )
        )
    )
    suppliers = _any(db, (Supplier.org_id == org_id) & Supplier.is_sample.is_(False))
    forecast = connected and _any(
        db, (ForecastRun.org_id == org_id) & (ForecastRun.status == "success")
    )
    po = bool(
        db.scalar(
            select(
                exists()
                .where(PurchaseOrder.org_id == org_id)
                .where(PurchaseOrderLine.purchase_order_id == PurchaseOrder.id)
                .where(PurchaseOrderLine.product_id == Product.id, Product.is_sample.is_(False))
            )
        )
    )
    steps = [
        Step(
            "connect",
            "Connect a store or upload your data",
            "Shopify, Amazon, eBay, WooCommerce or CSV files",
            "/onboarding",
            connected,
        ),
        Step(
            "bom",
            "Add a bill of materials",
            "List the components that go into one unit of a product",
            "/products",
            bom,
        ),
        Step(
            "suppliers",
            "Add suppliers and lead times",
            "Lead times decide when each order has to go out",
            "/settings?tab=suppliers",
            suppliers,
        ),
        Step(
            "forecast",
            "Run your first forecast",
            "Forecasts refresh every night after that",
            "/onboarding",
            forecast,
        ),
        Step(
            "po",
            "Create your first purchase order",
            "Pick recommendations and turn them into a PO",
            "/recommendations",
            po,
        ),
    ]
    return steps, sample_data.has_sample(db, org_id)
