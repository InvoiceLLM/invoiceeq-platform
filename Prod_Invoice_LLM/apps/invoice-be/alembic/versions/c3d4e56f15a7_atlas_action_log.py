"""Feature 34 / task 34.7c — what ATLAS did, as a real list.

§5.3 requires that ATLAS "never writes silently: every write is visible,
attributed and timestamped." D50/D51 make two action kinds performable
(`resolve_invoice`, `retry_ingestion_source`), so this is the table that turns
that requirement from a sentence in a spec into something a person can read.

One add-only table. Nothing dropped, nothing renamed, nothing back-filled --
there is no prior state, because until this slice ATLAS could not write at all.

Failures are rows too (`succeeded` is a column, not a filter applied before the
insert): a log that only recorded successes would answer "did ATLAS touch this
invoice?" with a confident no on exactly the occasions someone is asking.

`down_revision` is `b2c3d45e14f6` (D49's `atlas_dismissals`), confirmed as the
single head by `alembic heads` immediately before writing this file.

Revision ID: c3d4e56f15a7
Revises: b2c3d45e14f6
Create Date: 2026-09-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e56f15a7"
down_revision: Union[str, None] = "b2c3d45e14f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "atlas_action_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("recommendation_id", sa.String(length=255), nullable=False),
        sa.Column("action_kind", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("summary", sa.String(length=1000), nullable=False),
        sa.Column("performed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_atlas_action_log_tenant_id", "atlas_action_log", ["tenant_id"]
    )
    # The one read: this tenant's actions, newest first.
    op.create_index(
        "idx_atlas_action_tenant_time",
        "atlas_action_log",
        ["tenant_id", "performed_at"],
    )
    # No unique constraint anywhere on this table, deliberately. Two identical
    # resolves of the same invoice from the same line are two real events -- the
    # second one is the "already resolved, nothing changed" answer -- and
    # collapsing them would make the list less true, not tidier.


def downgrade() -> None:
    op.drop_index("idx_atlas_action_tenant_time", table_name="atlas_action_log")
    op.drop_index("ix_atlas_action_log_tenant_id", table_name="atlas_action_log")
    op.drop_table("atlas_action_log")
