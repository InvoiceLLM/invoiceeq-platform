"""Feature 34 / tasks 34.10 and 34.14 — memory as editable rules, and "you missed this".

§7.2 (D31): everything ATLAS learns becomes a visible, editable rule in plain
language, because a wrong lesson that cannot be found haunts the system forever.
**Bounded by D40**: derived observations (vendor baselines, claims) are computed
at check time and are NOT rows here — the line shows its working instead.

§5.2 / D34: a false negative is invisible and permanent, and the only detector is
the user reporting it. A report feeds §7.2's memory, which is why the two tables
land together rather than the report becoming a support email.

Two add-only tables. Nothing dropped, nothing renamed, nothing back-filled —
there is no prior state, because until now ATLAS remembered nothing at all.

**No `deleted_at` on either.** The founder's rule is that delete means the row
goes; `atlas_memory_rules.active` is a user switching a rule off and keeping it,
which is a different thing and is why both exist.

`down_revision` is `c3d4e56f15a7` (34.7c's action log), confirmed as the single
head by `alembic heads` immediately before writing this file.

Revision ID: d4e5f67a16b8
Revises: c3d4e56f15a7
Create Date: 2026-09-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f67a16b8"
down_revision: Union[str, None] = "c3d4e56f15a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "atlas_memory_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("text", sa.String(length=2000), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("origin_ref", sa.String(length=255), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_atlas_memory_rules_tenant_id", "atlas_memory_rules", ["tenant_id"]
    )
    op.create_index(
        "idx_atlas_memory_tenant", "atlas_memory_rules", ["tenant_id", "created_at"]
    )

    op.create_table(
        "atlas_missed_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("entity_kind", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column("rule_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_atlas_missed_reports_tenant_id", "atlas_missed_reports", ["tenant_id"]
    )
    op.create_index(
        "idx_atlas_missed_tenant", "atlas_missed_reports", ["tenant_id", "created_at"]
    )
    # `rule_id` is deliberately NOT a foreign key. A user may delete a wrong
    # lesson (§7.2 says they can), and deleting the rule must not take the
    # evidence that ATLAS missed something with it -- nor must the report keep
    # the rule alive. The two are read together when both exist and stand alone
    # when they do not.


def downgrade() -> None:
    op.drop_index("idx_atlas_missed_tenant", table_name="atlas_missed_reports")
    op.drop_index("ix_atlas_missed_reports_tenant_id", table_name="atlas_missed_reports")
    op.drop_table("atlas_missed_reports")
    op.drop_index("idx_atlas_memory_tenant", table_name="atlas_memory_rules")
    op.drop_index("ix_atlas_memory_rules_tenant_id", table_name="atlas_memory_rules")
    op.drop_table("atlas_memory_rules")
