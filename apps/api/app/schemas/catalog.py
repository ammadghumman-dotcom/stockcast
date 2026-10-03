import uuid
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import ProductType
from app.schemas.common import Timestamped


# ---- Products ----
class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    type: ProductType = ProductType.finished
    unit_cost: Decimal = Field(default=Decimal("0"), ge=0)
    unit: str = Field(default="unit", max_length=20)
    category_id: uuid.UUID | None = None
    is_active: bool = True


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    type: ProductType | None = None
    unit_cost: Decimal | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=20)
    category_id: uuid.UUID | None = None
    is_active: bool | None = None


class ProductRead(Timestamped):
    org_id: uuid.UUID
    sku: str
    name: str
    type: ProductType
    unit_cost: Decimal
    unit: str
    category_id: uuid.UUID | None
    is_active: bool
    service_level: Decimal | None = None
    target_cover_days: int | None = None
    lead_time_days: int | None = None
    preferred_supplier_id: uuid.UUID | None = None


# ---- Suppliers ----
class SupplierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    lead_time_days: int = Field(default=14, ge=0)
    moq: int = Field(default=1, ge=1)
    currency: str = Field(default="USD", min_length=3, max_length=3)


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    lead_time_days: int | None = Field(default=None, ge=0)
    moq: int | None = Field(default=None, ge=1)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class SupplierRead(Timestamped):
    org_id: uuid.UUID
    name: str
    email: str | None
    lead_time_days: int
    moq: int
    currency: str


# ---- BOM lines ----
class BomLineCreate(BaseModel):
    parent_product_id: uuid.UUID
    component_product_id: uuid.UUID
    qty_per_unit: Decimal = Field(gt=0)


class BomLineUpdate(BaseModel):
    qty_per_unit: Decimal = Field(gt=0)


class BomLineRead(Timestamped):
    org_id: uuid.UUID
    parent_product_id: uuid.UUID
    component_product_id: uuid.UUID
    qty_per_unit: Decimal


# ---- Locations ----
class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: str = Field(default="warehouse", max_length=20)
    address: str | None = None
    is_default: bool = False


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: str | None = Field(default=None, max_length=20)
    address: str | None = None
    is_default: bool | None = None


class LocationRead(Timestamped):
    org_id: uuid.UUID
    name: str
    kind: str
    address: str | None
    is_default: bool
