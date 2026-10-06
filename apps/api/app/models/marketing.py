"""Pre-signup leads from the public site (waitlist / beta applications). Not org-scoped."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, uuid_pk


class WaitlistSignup(Base):
    __tablename__ = "waitlist_signups"
    __table_args__ = (UniqueConstraint("email", name="uq_waitlist_signups_email"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(320), nullable=False)  # stored lower-cased
    name: Mapped[str | None] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(200))
    website: Mapped[str | None] = mapped_column(String(300))
    channels: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    makes_products: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(60), default="landing", nullable=False)
    beta_invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
