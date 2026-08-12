"""merge Gap 192 soft-delete migration branch

Revision ID: c097b6848d7c
Revises: 6505088bd42d, a0b1c2d3e4f5
Create Date: 2026-08-12 16:48:39.015077

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'c097b6848d7c'
down_revision: Union[str, None] = ('6505088bd42d', 'a0b1c2d3e4f5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
