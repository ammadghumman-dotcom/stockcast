import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import HolidaySource, PromotionScope, PromotionType
from app.schemas.common import Timestamped


class RegionCreate(BaseModel):
    code: str = Field(min_length=2, max_length=8)
    name: str = Field(min_length=1, max_length=100)
    currency: str = Field(default="USD", min_length=3, max_length=3)


class RegionRead(Timestamped):
    org_id: uuid.UUID
    code: str
    name: str
    currency: str


class HolidayEventCreate(BaseModel):
    region_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date
    recurring: bool = True
    kind: str = Field(default="retail", max_length=20)

    @model_validator(mode="after")
    def _order(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        return self


class HolidayEventUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    start_date: date | None = None
    end_date: date | None = None
    recurring: bool | None = None


class HolidayEventRead(Timestamped):
    org_id: uuid.UUID
    region_id: uuid.UUID
    name: str
    start_date: date
    end_date: date
    recurring: bool
    source: HolidaySource
    kind: str


class UpliftRead(Timestamped):
    org_id: uuid.UUID
    category_id: uuid.UUID
    region_id: uuid.UUID
    event_name: str
    uplift_pct: Decimal
    learned: bool
    sample_size: int | None
    manual: bool = False


class UpliftUpdate(BaseModel):
    uplift_pct: Decimal = Field(ge=-100, le=2000)


class PromotionBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: PromotionType
    start_date: date
    end_date: date
    discount_pct: Decimal | None = Field(default=None, ge=0, le=100)
    spend_amount: Decimal | None = Field(default=None, ge=0)
    channel_id: uuid.UUID | None = None
    scope: PromotionScope = PromotionScope.all
    category_id: uuid.UUID | None = None
    product_ids: list[uuid.UUID] | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.scope == PromotionScope.category and not self.category_id:
            raise ValueError("category_id required when scope=category")
        if self.scope == PromotionScope.skus and not self.product_ids:
            raise ValueError("product_ids required when scope=skus")
        return self


class PromotionCreate(PromotionBase):
    pass


class PromotionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    discount_pct: Decimal | None = Field(default=None, ge=0, le=100)
    spend_amount: Decimal | None = Field(default=None, ge=0)


class PromotionRead(Timestamped):
    org_id: uuid.UUID
    name: str
    type: PromotionType
    start_date: date
    end_date: date
    discount_pct: Decimal | None
    spend_amount: Decimal | None
    channel_id: uuid.UUID | None
    scope: PromotionScope
    category_id: uuid.UUID | None
    product_ids: list[str] | None
    observed_lift: Decimal | None
    observed_post_dip: Decimal | None
    baseline_units: Decimal | None


class SimulateRequest(PromotionBase):
    pass


class ProductDeltaRead(BaseModel):
    product_id: uuid.UUID
    sku: str
    base_units: float
    promo_units: float
    delta_units: float
    post_dip_units: float


class MaterialDeltaRead(BaseModel):
    product_id: uuid.UUID
    sku: str
    unit: str
    delta_qty: float


class SimulateResponse(BaseModel):
    run_id: uuid.UUID | None
    lift: float
    post_dip: float
    total_delta_units: float
    products: list[ProductDeltaRead]
    materials: list[MaterialDeltaRead]
