import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, OrgScoped, TimestampMixin, uuid_pk
from app.models.enums import POStatus


class InventoryLevel(OrgScoped, Base):
    """Snapshot of stock per product per location."""

    __tablename__ = "inventory_levels"
    __table_args__ = (
        UniqueConstraint("product_id", "location_id", name="uq_inventory_levels_product_loc"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="CASCADE"), nullable=False
    )
    on_hand: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    inbound: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    as_of: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SalesDaily(OrgScoped, Base):
    """Daily units + revenue per product per channel. Timescale hypertable on `date`.

    Composite PK (Timescale requires the partition column in every unique index).
    """

    __tablename__ = "sales_daily"
    __table_args__ = (
        PrimaryKeyConstraint("date", "product_id", "channel_id"),
        Index("ix_sales_daily_org_product_date", "org_id", "product_id", "date"),
    )

    date: Mapped[date] = mapped_column(Date, nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    region_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("regions.id", ondelete="SET NULL")
    )
    units: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    revenue: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)


class PurchaseOrder(OrgScoped, TimestampMixin, Base):
    __tablename__ = "purchase_orders"

    id: Mapped[uuid.UUID] = uuid_pk()
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("locations.id", ondelete="SET NULL")
    )
    number: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[POStatus] = mapped_column(
        Enum(POStatus, name="po_status"), default=POStatus.draft, nullable=False
    )
    expected_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan"
    )


class PurchaseOrderLine(Base):
    __tablename__ = "po_lines"

    id: Mapped[uuid.UUID] = uuid_pk()
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    received_qty: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")
