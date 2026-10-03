import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, Enum, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, TimestampMixin, uuid_pk
from app.models.enums import HolidaySource, PromotionScope, PromotionType


class HolidayEvent(OrgScoped, TimestampMixin, Base):
    """A demand-shifting event in a region (Christmas, Eid, Black Friday ...), with lead-in."""

    __tablename__ = "holiday_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    region_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("regions.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    recurring: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source: Mapped[HolidaySource] = mapped_column(
        Enum(HolidaySource, name="holiday_source"), default=HolidaySource.custom, nullable=False
    )


class CategoryHolidayUplift(OrgScoped, TimestampMixin, Base):
    """Demand multiplier for a category during a holiday. `learned` = fitted from history."""

    __tablename__ = "category_holiday_uplift"
    __table_args__ = (
        UniqueConstraint("category_id", "holiday_event_id", name="uq_cat_holiday_uplift_pair"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_categories.id", ondelete="CASCADE"), nullable=False
    )
    holiday_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("holiday_events.id", ondelete="CASCADE"), nullable=False
    )
    uplift_pct: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)  # +150.00 = 2.5x
    learned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sample_size: Mapped[int | None] = mapped_column()


class Promotion(OrgScoped, TimestampMixin, Base):
    __tablename__ = "promotions"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="SET NULL")
    )
    type: Mapped[PromotionType] = mapped_column(
        Enum(PromotionType, name="promotion_type"), nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    spend_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    scope: Mapped[PromotionScope] = mapped_column(
        Enum(PromotionScope, name="promotion_scope"), default=PromotionScope.all, nullable=False
    )
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_categories.id", ondelete="SET NULL")
    )
    # SKU list when scope == skus (JSON array of product ids)
    product_ids: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
