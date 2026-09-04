"""Feature 26 Phase 4 (Gap 444): ChatAttachment.match_tier + match_summary.

The matcher now runs at upload rather than on the first turn, so the proposal it
makes has to be persisted somewhere the chip can read after a reload. Both
nullable: every existing attachment predates the matcher call and correctly has
no proposal recorded.

Revision ID: d4e5f6a0b1c2
Revises: c3d4e5f6a9b0
Create Date: 2026-09-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4e5f6a0b1c2"
down_revision: Union[str, None] = "c3d4e5f6a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chat_attachments", sa.Column("match_tier", sa.Integer(), nullable=True))
    op.add_column(
        "chat_attachments", sa.Column("match_summary", sa.String(length=512), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("chat_attachments", "match_summary")
    op.drop_column("chat_attachments", "match_tier")
