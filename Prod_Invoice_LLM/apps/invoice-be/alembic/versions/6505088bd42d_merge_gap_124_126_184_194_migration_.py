"""merge Gap 124/126/184/194 migration branches

Revision ID: 6505088bd42d
Revises: b8c1d4e7f209, c1d2e3f4a5b6, c9d0e1f2a3b4
Create Date: 2026-08-12 16:17:01.365493

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '6505088bd42d'
down_revision: Union[str, None] = ('b8c1d4e7f209', 'c1d2e3f4a5b6', 'c9d0e1f2a3b4')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
