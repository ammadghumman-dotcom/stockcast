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
    error: str | None


class ForecastPoint(OrmModel):
    date: date
    p10: Decimal
    p50: Decimal
    p90: Decimal


class ProductForecast(BaseModel):
    product_id: uuid.UUID
    run_id: uuid.UUID
    as_of: date | None
    model: str
    points: list[ForecastPoint]
    total_p50_30d: Decimal
    total_p50_90d: Decimal


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
