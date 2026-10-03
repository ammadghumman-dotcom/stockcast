import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, TimestampMixin, uuid_pk


class PlanningSettings(OrgScoped, TimestampMixin, Base):
    """Org-wide planning defaults; products can override service level / cover / lead time."""

    __tablename__ = "planning_settings"
    __table_args__ = (UniqueConstraint("org_id", name="uq_planning_settings_org"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    service_level: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), default=Decimal("0.95"), nullable=False
    )
    target_cover_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    overstock_days: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    default_lead_time_days: Mapped[int] = mapped_column(Integer, default=14, nullable=False)
    production_lead_time_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    at_risk_buffer_days: Mapped[int] = mapped_column(Integer, default=7, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, default=90, nullable=False)


class PlanningRun(OrgScoped, TimestampMixin, Base):
    __tablename__ = "planning_runs"

    id: Mapped[uuid.UUID] = uuid_pk()
    forecast_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("forecast_runs.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    trigger: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    as_of: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    products_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    n_reorder: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    n_produce: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    health_counts: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    cash_by_health: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class Recommendation(OrgScoped, Base):
    """One row per product per planning run: health + what to do about it."""

    __tablename__ = "recommendations"
    __table_args__ = (
        UniqueConstraint("run_id", "product_id", name="uq_recommendations_run_product"),
        Index("ix_recommendations_org_run", "org_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("planning_runs.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(10), nullable=False)  # reorder|produce|none
    health: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # healthy|at_risk|stockout|overstock
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    order_by_date: Mapped[date | None] = mapped_column(Date)
    expected_date: Mapped[date | None] = mapped_column(Date)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    on_hand: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    inbound: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    daily_demand: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    safety_stock: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    reorder_point: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    stockout_date: Mapped[date | None] = mapped_column(Date)
    days_of_cover: Mapped[int | None] = mapped_column(Integer)
    cash_tied: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    event: Mapped[str | None] = mapped_column(String(120))
    uplift_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    po_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="SET NULL")
    )
