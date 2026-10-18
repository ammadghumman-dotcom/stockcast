"""forecast_runs / planning_runs .data_through (newest day with sales data)

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-10-18 14:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: str | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("forecast_runs", sa.Column("data_through", sa.Date(), nullable=True))
    op.add_column("planning_runs", sa.Column("data_through", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("planning_runs", "data_through")
    op.drop_column("forecast_runs", "data_through")
