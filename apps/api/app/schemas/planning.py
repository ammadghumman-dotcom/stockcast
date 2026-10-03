import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import POStatus
from app.schemas.common import OrmModel, Timestamped


class PlanningSettingsRead(Timestamped):
    org_id: uuid.UUID
    service_level: Decimal
    target_cover_days: int
    overstock_days: int
    default_lead_time_days: int
    production_lead_time_days: int
    at_risk_buffer_days: int
    horizon_days: int


class PlanningSettingsUpdate(BaseModel):
    service_level: Decimal | None = Field(default=None, ge=Decimal("0.5"), le=Decimal("0.999"))
    target_cover_days: int | None = Field(default=None, ge=1, le=365)
    overstock_days: int | None = Field(default=None, ge=7, le=730)
    default_lead_time_days: int | None = Field(default=None, ge=0, le=365)
    production_lead_time_days: int | None = Field(default=None, ge=0, le=365)
    at_risk_buffer_days: int | None = Field(default=None, ge=0, le=90)
    horizon_days: int | None = Field(default=None, ge=14, le=365)


class ProductPlanningUpdate(BaseModel):
    service_level: Decimal | None = Field(default=None, ge=Decimal("0.5"), le=Decimal("0.999"))
    target_cover_days: int | None = Field(default=None, ge=1, le=365)
    lead_time_days: int | None = Field(default=None, ge=0, le=365)
    preferred_supplier_id: uuid.UUID | None = None


class PlanningRunRead(Timestamped):
    org_id: uuid.UUID
    forecast_run_id: uuid.UUID | None
    status: str
    trigger: str
    as_of: date | None
    started_at: datetime | None
    finished_at: datetime | None
    products_total: int
    n_reorder: int
    n_produce: int
    health_counts: dict[str, int]
    cash_by_health: dict[str, float]
    error: str | None


class ChannelMix(BaseModel):
    channel_id: uuid.UUID
    channel_name: str
    channel_type: str
    share: Decimal


class RecommendationRead(OrmModel):
    id: uuid.UUID
    run_id: uuid.UUID
    product_id: uuid.UUID
    sku: str | None = None
    product_name: str | None = None
    action: str
    health: str
    qty: Decimal
    order_by_date: date | None
    expected_date: date | None
    supplier_id: uuid.UUID | None
    supplier_name: str | None = None
    reason: str
    on_hand: Decimal
    inbound: Decimal
    daily_demand: Decimal
    lead_time_days: int
    safety_stock: Decimal
    reorder_point: Decimal
    stockout_date: date | None
    days_of_cover: int | None
    cash_tied: Decimal
    event: str | None
    uplift_pct: Decimal | None
    po_id: uuid.UUID | None
    channel_mix: list[ChannelMix] = []


class DraftPORequest(BaseModel):
    recommendation_ids: list[uuid.UUID] | None = Field(
        default=None, description="omit = all open reorders"
    )
    run_id: uuid.UUID | None = Field(default=None, description="omit = latest planning run")


class POLineRead(OrmModel):
    id: uuid.UUID
    product_id: uuid.UUID
    sku: str | None = None
    qty: Decimal
    unit_price: Decimal
    received_qty: Decimal
    line_no: int


class PurchaseOrderRead(Timestamped):
    org_id: uuid.UUID
    supplier_id: uuid.UUID
    supplier_name: str | None = None
    location_id: uuid.UUID | None
    number: str
    status: POStatus
    expected_date: date | None
    notes: str | None
    currency: str
    sent_at: datetime | None
    received_at: datetime | None
    total: Decimal
    lines: list[POLineRead]


class ReceiveRequest(BaseModel):
    lines: dict[uuid.UUID, Decimal] | None = Field(
        default=None, description="line id -> qty received; omit = all in full"
    )
