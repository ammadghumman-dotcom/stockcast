"""Provider-neutral billing: organizations.billing_* + billing_events (Lemon Squeezy / Paddle)

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-10-19 12:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a4b5c6d7e8f9"
down_revision: str | None = "f3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("billing_provider", sa.String(20), nullable=True))
    op.add_column("organizations", sa.Column("billing_customer_id", sa.String(100), nullable=True))
    op.add_column(
        "organizations", sa.Column("billing_subscription_id", sa.String(100), nullable=True)
    )
    op.create_table(
        "billing_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("event_id", sa.String(200), nullable=False),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider", "event_id", name="uq_billing_events_provider_event"),
    )


def downgrade() -> None:
    op.drop_table("billing_events")
    op.drop_column("organizations", "billing_subscription_id")
    op.drop_column("organizations", "billing_customer_id")
    op.drop_column("organizations", "billing_provider")
