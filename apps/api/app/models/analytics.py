"""First-time product milestones per workspace (activation funnel + weekly cohort report)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, uuid_pk


class OrgMilestone(OrgScoped, Base):
    __tablename__ = "org_milestones"
    __table_args__ = (UniqueConstraint("org_id", "key", name="uq_org_milestones_org_key"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(60), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    props: Mapped[dict | None] = mapped_column(JSON)
