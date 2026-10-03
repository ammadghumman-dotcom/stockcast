import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.schemas.common import OrmModel, Timestamped


class ForecastRunRead(Timestamped):
    org_id: uuid.UUID
    status: str
    trigger: str
    horizon_days: int
    as_of: date | None
    started_at: datetime | None
    finished_at: datetime | None
    skus_total: int
    skus_chronos: int
    skus_croston: int
    skus_fallback: int
    wape: Decimal | None
    wape_base: Decimal | None
    error: str | None


class ForecastPoint(OrmModel):
    date: date
    p10: Decimal
    p50: Decimal
    p90: Decimal
    factor: Decimal
    event: str | None


class ChannelShare(BaseModel):
    channel_id: uuid.UUID
    channel_name: str
    channel_type: str
    share: Decimal  # 0..1 of the last 90 days' units
    units_90d: Decimal
    p50_30d: Decimal  # share x org-level p50 totals
    p50_90d: Decimal


class ProductForecast(BaseModel):
    product_id: uuid.UUID
    run_id: uuid.UUID
    as_of: date | None
    model: str
    points: list[ForecastPoint]
    total_p50_30d: Decimal
    total_p50_90d: Decimal
    channels: list[ChannelShare] = []  # empty for raw materials (derived demand has no channel)


class AccuracyRow(OrmModel):
    product_id: uuid.UUID
    model: str
    history_days: int
    zero_share: Decimal
    holdout_days: int
    mape: Decimal | None
    wape: Decimal | None
    wape_chronos: Decimal | None
    wape_stats: Decimal | None


class AccuracySummary(BaseModel):
    run_id: uuid.UUID | None
    as_of: date | None
    skus: int
    wape: Decimal | None
    median_sku_wape: Decimal | None
    by_model: dict[str, int]
    worst: list[AccuracyRow]
