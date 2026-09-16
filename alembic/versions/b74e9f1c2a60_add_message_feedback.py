"""add message feedback

Revision ID: b74e9f1c2a60
Revises: f93b2c14d8e7
"""

import sqlalchemy as sa

from alembic import op

revision = "b74e9f1c2a60"
down_revision = "f93b2c14d8e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("final_sql", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('correct', 'needs_revision')",
            name="ck_message_feedback_status",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["conversation_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id"),
    )
    op.create_index(
        "ix_message_feedback_message_id", "message_feedback", ["message_id"]
    )
    op.create_index("ix_message_feedback_user_id", "message_feedback", ["user_id"])
    op.create_index("ix_message_feedback_status", "message_feedback", ["status"])


def downgrade() -> None:
    op.drop_index("ix_message_feedback_status", table_name="message_feedback")
    op.drop_index("ix_message_feedback_user_id", table_name="message_feedback")
    op.drop_index("ix_message_feedback_message_id", table_name="message_feedback")
    op.drop_table("message_feedback")
