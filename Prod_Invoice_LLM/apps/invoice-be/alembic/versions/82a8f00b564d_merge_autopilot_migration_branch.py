"""merge autopilot migration branch

Revision ID: 82a8f00b564d
Revises: 857ef0378718, c097b6848d7c
Create Date: 2026-08-12 18:58:11.552140

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '82a8f00b564d'
down_revision: Union[str, None] = ('857ef0378718', 'c097b6848d7c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
