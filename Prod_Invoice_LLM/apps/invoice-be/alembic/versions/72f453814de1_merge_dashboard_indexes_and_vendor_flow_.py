"""merge dashboard indexes and vendor flow settings heads

Revision ID: 72f453814de1
Revises: c7d8e9f0a1b2, e1f2a3b4c5d6
Create Date: 2026-07-28 09:35:35.200174

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = '72f453814de1'
down_revision: Union[str, None] = ('c7d8e9f0a1b2', 'e1f2a3b4c5d6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
