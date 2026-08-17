"""dedup repos globally by url

Revision ID: 588577b0171d
Revises: 9141dfb7d94b
Create Date: 2026-08-17 20:01:54.647011

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '588577b0171d'
down_revision: Union[str, None] = '9141dfb7d94b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_repo_user_url", "repos", type_="unique")
    op.create_unique_constraint("uq_repo_url", "repos", ["url"])


def downgrade() -> None:
    op.drop_constraint("uq_repo_url", "repos", type_="unique")
    op.create_unique_constraint("uq_repo_user_url", "repos", ["user_id", "url"])
