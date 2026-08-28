"""add flow_map, tech_debt, compliance_scan repo caches

Revision ID: f4a7c2e9b3d6
Revises: d8e1b3c5f9a2
Create Date: 2026-08-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f4a7c2e9b3d6'
down_revision: Union[str, None] = 'd8e1b3c5f9a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('repos', sa.Column('flow_map', sa.Text(), nullable=True))
    op.add_column('repos', sa.Column('tech_debt', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('repos', sa.Column('compliance_scan', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('repos', 'compliance_scan')
    op.drop_column('repos', 'tech_debt')
    op.drop_column('repos', 'flow_map')
