"""Normalized records every connector emits. Upsert logic only ever sees these shapes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import ProductType


class ProductRecord(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    type: ProductType = ProductType.finished
    unit_cost: Decimal = Field(default=Decimal("0"), ge=0)
    unit: str = Field(default="unit", max_length=20)
    category: str | None = None
    # channel-side identifier (Shopify variant id, ASIN ...). None for CSV catalog rows.
    external_id: str | None = None
    external_sku: str | None = None


class SalesRecord(BaseModel):
    date: date
    sku: str | None = None  # either sku or external_id must resolve to a product
    external_id: str | None = None
    units: Decimal = Field(ge=0)
    revenue: Decimal = Field(default=Decimal("0"), ge=0)


class InventoryRecord(BaseModel):
    sku: str | None = None
    external_id: str | None = None
    location: str = Field(min_length=1, max_length=200)
    on_hand: Decimal = Field(default=Decimal("0"))
    inbound: Decimal = Field(default=Decimal("0"), ge=0)


class BomRecord(BaseModel):
    parent_sku: str = Field(min_length=1)
    component_sku: str = Field(min_length=1)
    qty_per_unit: Decimal = Field(gt=0)


class RowError(BaseModel):
    row: int  # 1-based data row number (header excluded)
    message: str


class IngestResult(BaseModel):
    kind: str
    received: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[RowError] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def merge(self, other: IngestResult) -> IngestResult:
        self.received += other.received
        self.inserted += other.inserted
        self.updated += other.updated
        self.skipped += other.skipped
        self.errors.extend(other.errors)
        return self
