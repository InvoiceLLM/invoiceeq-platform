"""Feature 34 / D49 — a dismissed ATLAS line stays dismissed.

D38 recomputes every line when the user opens the app, so a line the user has
already handled is regenerated and returns forever. D49 rules for a manual
dismiss that persists — not a snooze, not an automatic resolution.

One add-only table. Nothing is dropped, nothing is renamed and nothing is
back-filled: there is no prior state to migrate, because until now a dismissal
had nowhere to go.

Keyed on `recommendation_id`, the deterministic `Recommendation.id`
(`audit-approve-<invoice id>`, `train-arithmetic-<invoice id>`), which is what
lets a dismissal recorded today suppress the same line on tomorrow's recompute.

Scoped per tenant **and per user**: the Admin is the superset (§2.2), so one
Auditor marking their line done must not remove it from the Admin's screen.

`down_revision` is `a1b2c34d13e5`, confirmed as the single head by
`alembic heads` immediately before writing this file.

Revision ID: b2c3d45e14f6
Revises: a1b2c34d13e5
Create Date: 2026-09-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d45e14f6"
down_revision: Union[str, None] = "a1b2c34d13e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "atlas_dismissals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("recommendation_id", sa.String(length=255), nullable=False),
        sa.Column("dismissed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "recommendation_id",
            name="uq_atlas_dismissal_tenant_user_line",
        ),
    )
    op.create_index(
        "ix_atlas_dismissals_tenant_id", "atlas_dismissals", ["tenant_id"]
    )
    # The one read: every line this caller has dismissed, fetched once per open.
    op.create_index(
        "idx_atlas_dismissal_tenant_user",
        "atlas_dismissals",
        ["tenant_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_atlas_dismissal_tenant_user", table_name="atlas_dismissals")
    op.drop_index("ix_atlas_dismissals_tenant_id", table_name="atlas_dismissals")
    op.drop_table("atlas_dismissals")
