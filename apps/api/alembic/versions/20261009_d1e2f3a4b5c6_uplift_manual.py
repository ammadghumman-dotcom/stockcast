"""uplift manual flag

Revision ID: d1e2f3a4b5c6
Revises: c423b1150376
Create Date: 2026-10-09 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | None = "c423b1150376"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "category_holiday_uplift",
        sa.Column("manual", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("category_holiday_uplift", "manual")
