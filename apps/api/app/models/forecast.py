import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, TimestampMixin, uuid_pk


class ForecastRun(OrgScoped, TimestampMixin, Base):
    """One forecasting pass over an org. status: queued | running | success | failed."""

    __tablename__ = "forecast_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, default=90, nullable=False)
    as_of: Mapped[date | None] = mapped_column(Date)  # last day of history used
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    skus_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skus_chronos: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skus_croston: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skus_fallback: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    wape: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))  # org-level backtest WAPE
    wape_base: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))  # same, without covariates
    error: Mapped[str | None] = mapped_column(Text)


class Forecast(OrgScoped, Base):
    """Daily forecast per product for one run. Quantiles p10/p50/p90 in units."""

    __tablename__ = "forecasts"
    __table_args__ = (
        PrimaryKeyConstraint("run_id", "product_id", "date"),
        Index("ix_forecasts_org_product_date", "org_id", "product_id", "date"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    p10: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    p50: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    p90: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    model: Mapped[str] = mapped_column(String(30), nullable=False)
    # covariate multiplier applied to the base forecast on this date (1.0 = none)
    factor: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=1, nullable=False)
    # dominant event driving the factor, for explanations ("Black Friday US")
    event: Mapped[str | None] = mapped_column(String(120))


class ForecastAccuracy(OrgScoped, Base):
    """Backtest result per product per run: 28-day holdout, best model chosen per SKU."""

    __tablename__ = "forecast_accuracy"
    __table_args__ = (UniqueConstraint("run_id", "product_id", name="uq_forecast_accuracy"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    model: Mapped[str] = mapped_column(String(30), nullable=False)  # chosen model
    history_days: Mapped[int] = mapped_column(Integer, nullable=False)
    zero_share: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    holdout_days: Mapped[int] = mapped_column(Integer, nullable=False)
    mape: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))  # None when actuals are all 0
    wape: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    wape_chronos: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    wape_stats: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
