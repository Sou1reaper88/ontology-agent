"""add shared saved prompts

Revision ID: f93b2c14d8e7
Revises: a31d8c7e5b42
"""
from alembic import op
import sqlalchemy as sa

revision = "f93b2c14d8e7"
down_revision = "a31d8c7e5b42"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("saved_prompts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))


def downgrade():
    op.drop_table("saved_prompts")
