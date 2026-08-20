"""add trace column to conversation_messages

Revision ID: c2e8d4a61f03
Revises: b8137c0f8a99
Create Date: 2026-08-17 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2e8d4a61f03'
down_revision: Union[str, Sequence[str], None] = '9661f31edf87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add trace JSON column (生成链路步骤，供全链路可视化回放)."""
    op.add_column('conversation_messages', sa.Column('trace', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('conversation_messages', 'trace')
