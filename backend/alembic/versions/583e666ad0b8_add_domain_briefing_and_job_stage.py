"""add domain briefing and job stage

Revision ID: 583e666ad0b8
Revises: 588577b0171d
Create Date: 2026-08-20 16:23:29.403401

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '583e666ad0b8'
down_revision: Union[str, None] = '588577b0171d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('repos', sa.Column('domain_briefing', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('jobs', sa.Column('stage', sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column('jobs', 'stage')
    op.drop_column('repos', 'domain_briefing')
