"""add tenant.api_key_scope (Feature 25 / Gap 335: two-tier API key action scope)

Revision ID: d8e9f0a1b2c3
Revises: a7c3d5e91f04
Create Date: 2026-08-29

Feature 25 Phase 0. Gap 184 gave each tenant one hashed API key; it did not give
anyone a way to say how much of the invoice lifecycle that key is allowed to
finish. This column is that decision, in the founder's own terms:

  "readonly"  Strict Review -- the key stays read/upload-only, a human finalizes
              in the web UI.
  "actions"   Full Automation -- the key gets to call
              approve/reject/verify/send/mark-paid.

NOT NULL with server_default 'readonly', deliberately, and this is the one
property of this migration that matters:

  * Postgres backfills every existing row with 'readonly' as part of the ALTER,
    so no separate backfill step is needed and there is never a NULL to reason
    about.
  * 'readonly' reproduces exactly what key-auth could already do before this
    change (dependencies.resolve_api_key_context resolved as role "Viewer" with
    no can_train/can_audit/can_load). So every existing tenant lands on
    precisely its current behaviour -- nobody silently gains the ability to have
    a machine approve their invoices because a migration ran.
  * Fail-closed is the whole point. If this column were nullable, or defaulted
    to 'actions', or were backfilled from some heuristic, the failure mode would
    be an integration finalizing invoices on a tenant that never asked for it.

This is a tenant-level column rather than a per-key one because
services/api_keys.py is one-key-per-tenant by design (see its module docstring);
there is no key table to attach a scope to.

down_revision is a7c3d5e91f04, confirmed as the single head by an actual
`alembic heads` run at the time of writing -- not by reading the files. This
repo has had a multi-head incident before (be_features_tracker.md Gap 60), and
other work was in flight in parallel when this was written, so the check was run
rather than assumed.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, None] = "a7c3d5e91f04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenant",
        sa.Column(
            "api_key_scope",
            sa.String(length=20),
            nullable=False,
            server_default="readonly",
        ),
    )


def downgrade() -> None:
    op.drop_column("tenant", "api_key_scope")
