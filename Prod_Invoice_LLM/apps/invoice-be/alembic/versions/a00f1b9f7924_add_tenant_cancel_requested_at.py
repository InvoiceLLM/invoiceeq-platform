"""add tenant cancel_requested_at (BE Gap 264)

Revision ID: a00f1b9f7924
Revises: 6c60f6e907a0
Create Date: 2026-08-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a00f1b9f7924'
down_revision: Union[str, None] = '6c60f6e907a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tenant', sa.Column('cancel_requested_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('tenant', 'cancel_requested_at')
