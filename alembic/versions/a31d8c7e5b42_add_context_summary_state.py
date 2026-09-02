"""add context summary state

Revision ID: a31d8c7e5b42
Revises: e64b7a9c2f10
Create Date: 2026-09-02 16:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a31d8c7e5b42"
down_revision: str | Sequence[str] | None = "e64b7a9c2f10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("context_summary", sa.Text(), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("context_summary_through_message_id", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "context_summary_through_message_id")
    op.drop_column("conversations", "context_summary")
