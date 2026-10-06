"""Shopify mandatory compliance (GDPR) webhooks + app/uninstalled.

Stockcast stores no customer personal data from Shopify: connectors read order *line items*
only and aggregate them into daily units per product (tests/test_privacy.py). So:

- customers/data_request -> nothing to export; the request is acknowledged and audited.
- customers/redact       -> nothing to erase; acknowledged and audited.
- shop/redact            -> (sent 48 h after uninstall) erase everything that came from the shop:
                            the channel (cascades listings, daily sales, sync runs, webhook dedupe
                            rows, forecast channel shares) and products that only existed because
                            of that shop (no other listing, no BOM line, no PO line).
- app/uninstalled        -> deactivate the channel and drop its access token immediately; data
                            stays until shop/redact so a quick re-install keeps history.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import CursorResult, delete, exists, select
from sqlalchemy.orm import Session

from app.models import BomLine, Channel, ChannelListing, ChannelType, Product
from app.models.inventory import PurchaseOrderLine
from app.services import audit


def shop_channels(db: Session, shop: str) -> list[Channel]:
    return list(
        db.scalars(
            select(Channel).where(
                Channel.type == ChannelType.shopify, Channel.external_shop_id == shop
            )
        )
    )


def _ack(db: Session, shop: str, action: str, payload: dict[str, Any]) -> int:
    """Audit a customer-level request against every org that installed the shop."""
    orders = payload.get("orders_requested") or payload.get("orders_to_redact") or []
    channels = shop_channels(db, shop)
    for ch in channels:
        audit.record(
            db,
            None,
            org_id=ch.org_id,
            action=action,
            entity="channel",
            entity_id=ch.id,
            after={
                "shop": shop,
                "orders": len(orders),
                "result": "no customer personal data stored",
            },
            actor="shopify",
        )
    return len(channels)


def customers_data_request(db: Session, shop: str, payload: dict[str, Any]) -> int:
    return _ack(db, shop, "shopify.customers_data_request", payload)


def customers_redact(db: Session, shop: str, payload: dict[str, Any]) -> int:
    return _ack(db, shop, "shopify.customers_redact", payload)


def app_uninstalled(db: Session, shop: str) -> int:
    channels = shop_channels(db, shop)
    for ch in channels:
        before = {"is_active": ch.is_active, "has_token": ch.credentials_encrypted is not None}
        ch.is_active = False
        ch.credentials_encrypted = None
        ch.webhooks_registered = False
        audit.record(
            db,
            None,
            org_id=ch.org_id,
            action="shopify.app_uninstalled",
            entity="channel",
            entity_id=ch.id,
            before=before,
            after={"is_active": False, "has_token": False},
            actor="shopify",
        )
    return len(channels)


def shop_redact(db: Session, shop: str) -> dict[str, int]:
    """Erase all data that came from `shop`. Idempotent: a second call finds nothing."""
    removed = {"channels": 0, "products": 0}
    for ch in shop_channels(db, shop):
        org_id, channel_id = ch.org_id, ch.id
        product_ids: list[uuid.UUID] = list(
            db.scalars(
                select(ChannelListing.product_id).where(ChannelListing.channel_id == channel_id)
            )
        )
        db.delete(ch)  # FK cascades: listings, sales_daily, sync_runs, processed_webhooks, ...
        db.flush()
        if product_ids:
            other_listing = exists().where(ChannelListing.product_id == Product.id)
            in_bom = exists().where(
                (BomLine.parent_product_id == Product.id)
                | (BomLine.component_product_id == Product.id)
            )
            on_po = exists().where(PurchaseOrderLine.product_id == Product.id)
            res: CursorResult[Any] = db.execute(  # type: ignore[assignment]
                delete(Product)
                .where(
                    Product.org_id == org_id,
                    Product.id.in_(product_ids),
                    ~other_listing,
                    ~in_bom,
                    ~on_po,
                )
                .execution_options(synchronize_session=False)
            )
            removed["products"] += res.rowcount or 0
        removed["channels"] += 1
        audit.record(
            db,
            None,
            org_id=org_id,
            action="shopify.shop_redact",
            entity="channel",
            entity_id=channel_id,
            after={"shop": shop, **removed},
            actor="shopify",
        )
    return removed
