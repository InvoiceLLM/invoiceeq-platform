"""Feature 35 (ATLAS Intelligence) task 35.6 — the briefing cache table.

Spec: `docs/feature_35_atlas_intelligence.md` §4.

One add-only table. Nothing is dropped, renamed or back-filled: there is no
prior state to migrate, because until now a briefing had nowhere to go, and the
dev-phase rule for a schema change is a migration file plus one
`alembic upgrade head` (no backfill, no down/up ceremony).

`down_revision` is `c5d6e7f8a9b0`, confirmed as the single head by
`alembic heads` immediately before writing this file.

The unique constraint is the one piece of this that is load-bearing rather than
descriptive: `services/atlas_briefing_cache.store()` upserts on
`(tenant_id, user_id, briefing_date)`, and two tabs opened at the same moment is
the ordinary case. Enforcing one-per-person-per-day in the database rather than
in a read-then-write is what makes the second tab replay the first one's
briefing instead of paying for a second run.

`paragraphs`, `question` and `tool_calls` are JSONB on PostgreSQL through
`models.JSON_VARIANT`; `sa.JSON` here resolves to the same variant because the
model owns the type.

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-09-20
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, None] = "c5d6e7f8a9b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: Same variant `models.JSON_VARIANT` uses, so the column the ORM writes and the
#: column this migration creates cannot disagree.
_JSON = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.create_table(
        "atlas_briefings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("briefing_date", sa.Date(), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("paragraphs", _JSON, nullable=True),
        sa.Column("question", _JSON, nullable=True),
        sa.Column("tool_calls", _JSON, nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("truncated", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("dropped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "briefing_date",
            name="uq_atlas_briefing_tenant_user_date",
        ),
    )
    op.create_index("ix_atlas_briefings_tenant_id", "atlas_briefings", ["tenant_id"])
    # The only read this table has: "this caller's briefing for today", once per
    # open of the work screen.
    op.create_index(
        "idx_atlas_briefing_tenant_user_date",
        "atlas_briefings",
        ["tenant_id", "user_id", "briefing_date"],
    )


def downgrade() -> None:
    op.drop_index("idx_atlas_briefing_tenant_user_date", table_name="atlas_briefings")
    op.drop_index("ix_atlas_briefings_tenant_id", table_name="atlas_briefings")
    op.drop_table("atlas_briefings")
