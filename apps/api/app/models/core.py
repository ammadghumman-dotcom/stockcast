import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, OrgScoped, TimestampMixin, uuid_pk
from app.models.enums import ChannelType


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    # auth + billing
    clerk_org_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    plan: Mapped[str] = mapped_column(String(20), default="trial", nullable=False)
    plan_status: Mapped[str] = mapped_column(String(20), default="trialing", nullable=False)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stripe_customer_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(100))
    billing_email: Mapped[str | None] = mapped_column(String(320))


class User(OrgScoped, TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("org_id", "email", name="uq_users_org_email"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="owner", nullable=False)
    external_auth_id: Mapped[str | None] = mapped_column(String(200))  # Clerk id, Step 7


class Region(OrgScoped, TimestampMixin, Base):
    """A sales region (US, UK, EU, PK, AE ...). Holidays and channels hang off it."""

    __tablename__ = "regions"
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_regions_org_code"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)


class Location(OrgScoped, TimestampMixin, Base):
    """Warehouse or 3PL that holds stock."""

    __tablename__ = "locations"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="warehouse", nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Channel(OrgScoped, TimestampMixin, Base):
    """A connected sales channel. `credentials_encrypted` is a Fernet token."""

    __tablename__ = "channels"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[ChannelType] = mapped_column(
        Enum(ChannelType, name="channel_type"), nullable=False
    )
    region_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("regions.id", ondelete="SET NULL")
    )
    external_shop_id: Mapped[str | None] = mapped_column(String(200))
    credentials_encrypted: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    webhooks_registered: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    region: Mapped[Region | None] = relationship()
