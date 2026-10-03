import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, uuid_pk


class StripeEvent(Base):
    """Processed Stripe webhook ids: replayed deliveries are acknowledged and ignored."""

    __tablename__ = "stripe_events"

    id: Mapped[uuid.UUID] = uuid_pk()
    event_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditLog(OrgScoped, Base):
    """Who changed what: purchase orders, planning settings, product planning, billing."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    actor: Mapped[str] = mapped_column(String(200), default="", nullable=False)  # email or "system"
    action: Mapped[str] = mapped_column(String(60), nullable=False)  # po.send, settings.update ...
    entity: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(100))
    before: Mapped[dict | None] = mapped_column(JSON)
    after: Mapped[dict | None] = mapped_column(JSON)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EmailLog(OrgScoped, Base):
    """One row per transactional email; (org, kind, dedupe_key) makes sends idempotent."""

    __tablename__ = "email_log"
    __table_args__ = (UniqueConstraint("org_id", "kind", "dedupe_key", name="uq_email_log_once"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(100), nullable=False)
    to: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    provider_id: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="sent", nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
