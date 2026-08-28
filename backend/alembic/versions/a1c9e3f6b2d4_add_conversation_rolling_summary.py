"""add conversation rolling summary

Revision ID: a1c9e3f6b2d4
Revises: fbae54bca9a7
Create Date: 2026-08-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c9e3f6b2d4'
down_revision: Union[str, None] = 'fbae54bca9a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('summary', sa.Text(), nullable=True))
    op.add_column(
        'conversations',
        sa.Column('summary_covers_through_message_count', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('conversations', 'summary_covers_through_message_count')
    op.drop_column('conversations', 'summary')
