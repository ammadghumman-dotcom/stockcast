"""users.clerk_invitation_id

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-10-09 20:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: str | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("clerk_invitation_id", sa.String(100), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "clerk_invitation_id")
