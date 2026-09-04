"""Feature 26 Phase 2 (Gaps 436/437): ChatSession.focus + ChatSession.history_summary.

`focus` is the per-session subject snapshot (vendor / invoice_ids / date_range /
attachment_ids) rewritten from each turn's result; `history_summary` is the
condensed oldest half of a long conversation. Both nullable with no default, so
every existing session row keeps working unchanged and the first turn after
deploy simply writes them.

Revision ID: c3d4e5f6a9b0
Revises: b2c3d4e5f6a8
Create Date: 2026-09-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "c3d4e5f6a9b0"
down_revision: Union[str, None] = "b2c3d4e5f6a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chatsession",
        sa.Column(
            "focus",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
    )
    op.add_column("chatsession", sa.Column("history_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("chatsession", "history_summary")
    op.drop_column("chatsession", "focus")
