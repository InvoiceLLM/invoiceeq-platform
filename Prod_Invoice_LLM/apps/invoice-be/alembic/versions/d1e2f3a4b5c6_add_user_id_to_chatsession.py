"""Gap 572 (CH-5): Add user_id to ChatSession for user-level chat isolation.

Revision ID: d1e2f3a4b5c6
Revises: c553d559e0a1
Create Date: 2026-09-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c553d559e0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chatsession", sa.Column("user_id", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_chatsession_user_id"), "chatsession", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_chatsession_user_id"), table_name="chatsession")
    op.drop_column("chatsession", "user_id")
