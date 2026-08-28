"""add flagship tools cache

Revision ID: c7f2a9d4e6b1
Revises: a1c9e3f6b2d4
Create Date: 2026-08-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'c7f2a9d4e6b1'
down_revision: Union[str, None] = 'a1c9e3f6b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('repos', sa.Column('readme_doc', sa.Text(), nullable=True))
    op.add_column('repos', sa.Column('security_scan', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('repos', sa.Column('health_score', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('repos', 'health_score')
    op.drop_column('repos', 'security_scan')
    op.drop_column('repos', 'readme_doc')
