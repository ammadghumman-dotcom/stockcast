import uuid
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, OrgScoped, SampleFlag, TimestampMixin, uuid_pk
from app.models.enums import ProductType


class ProductCategory(OrgScoped, SampleFlag, TimestampMixin, Base):
    __tablename__ = "product_categories"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_product_categories_org_name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(100), nullable=False)


class Product(OrgScoped, SampleFlag, TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("org_id", "sku", name="uq_products_org_sku"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    type: Mapped[ProductType] = mapped_column(
        Enum(ProductType, name="product_type"), nullable=False
    )
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 4), default=0, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="unit", nullable=False)  # unit, g, ml
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_categories.id", ondelete="SET NULL")
    )
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    # planning overrides (None = org default from planning_settings)
    service_level: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    target_cover_days: Mapped[int | None] = mapped_column(Integer)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)  # production or purchase lead
    preferred_supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="SET NULL", use_alter=True)
    )

    category: Mapped[ProductCategory | None] = relationship()
    bom_lines: Mapped[list["BomLine"]] = relationship(
        back_populates="parent",
        foreign_keys="BomLine.parent_product_id",
        cascade="all, delete-orphan",
    )


class ChannelListing(OrgScoped, TimestampMixin, Base):
    """Maps a product to its id on a channel (Shopify variant id, ASIN, eBay item id ...)."""

    __tablename__ = "channel_listings"
    __table_args__ = (
        UniqueConstraint("channel_id", "external_id", name="uq_channel_listings_channel_ext"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    channel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("channels.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    external_sku: Mapped[str | None] = mapped_column(String(200))


class BomLine(OrgScoped, TimestampMixin, Base):
    """Bill of materials: `parent` needs `qty_per_unit` of `component` per unit made."""

    __tablename__ = "bom_lines"
    __table_args__ = (
        UniqueConstraint(
            "parent_product_id", "component_product_id", name="uq_bom_lines_parent_component"
        ),
        CheckConstraint("qty_per_unit > 0", name="ck_bom_lines_qty_positive"),
        CheckConstraint("parent_product_id <> component_product_id", name="ck_bom_lines_not_self"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    parent_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    component_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    qty_per_unit: Mapped[Decimal] = mapped_column(Numeric(14, 4), nullable=False)

    parent: Mapped[Product] = relationship(
        back_populates="bom_lines", foreign_keys=[parent_product_id]
    )
    component: Mapped[Product] = relationship(foreign_keys=[component_product_id])


class Supplier(OrgScoped, SampleFlag, TimestampMixin, Base):
    __tablename__ = "suppliers"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    lead_time_days: Mapped[int] = mapped_column(Integer, default=14, nullable=False)
    moq: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)


class SupplierProduct(OrgScoped, TimestampMixin, Base):
    """What a supplier charges for a product, with optional lead-time override."""

    __tablename__ = "supplier_products"
    __table_args__ = (
        UniqueConstraint("supplier_id", "product_id", name="uq_supplier_products_pair"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    pack_size: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
