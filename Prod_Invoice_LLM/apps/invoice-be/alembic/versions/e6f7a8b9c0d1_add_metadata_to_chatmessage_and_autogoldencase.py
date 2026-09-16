"""add turn_metadata to chatmessage and SQL/citations/metadata to auto_golden_cases (Gaps 596 and 598)

Revision ID: e6f7a8b9c0d1
Revises: c553d559e0a1
Create Date: 2026-09-16

Gap 596: Persist turn_metadata on ChatMessage (route, model, token usage, status).
Gap 598: Persist generated_sql, citations, result_invoice_ids, and turn_metadata on AutoGoldenCase.

Dev add-only rule compliant: all columns are strictly nullable with no destructive backfills.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "e6f7a8b9c0d1"
# Merge of `fix/chat-backend-21-gaps` into the local chat-gaps branch, 2026-09-16:
# re-pointed from `c553d559e0a1` onto this branch's chain. Both branches added a
# migration off the same parent, which left `alembic heads` reporting two heads and
# `alembic upgrade head` refusing to run. Neither migration has been applied to any
# shared database yet, so re-pointing is safe and keeps the chain linear rather than
# adding a merge revision. Chain is now
# c553d559e0a1 -> d1e2f3a4b5c6 (user_id) -> e2f3a4b5c6d7 (nullable actor) -> this.
down_revision: Union[str, None] = "e2f3a4b5c6d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_VARIANT = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    # Gap 596: ChatMessage.turn_metadata
    op.add_column(
        "chatmessage",
        sa.Column("turn_metadata", JSON_VARIANT, nullable=True),
    )

    # Gap 598: AutoGoldenCase columns
    op.add_column(
        "auto_golden_cases",
        sa.Column("generated_sql", sa.Text(), nullable=True),
    )
    op.add_column(
        "auto_golden_cases",
        sa.Column("citations", JSON_VARIANT, nullable=True),
    )
    op.add_column(
        "auto_golden_cases",
        sa.Column("result_invoice_ids", JSON_VARIANT, nullable=True),
    )
    op.add_column(
        "auto_golden_cases",
        sa.Column("turn_metadata", JSON_VARIANT, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("auto_golden_cases", "turn_metadata")
    op.drop_column("auto_golden_cases", "result_invoice_ids")
    op.drop_column("auto_golden_cases", "citations")
    op.drop_column("auto_golden_cases", "generated_sql")
    op.drop_column("chatmessage", "turn_metadata")
