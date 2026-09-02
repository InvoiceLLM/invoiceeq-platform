"""add can_send_invoices permission flag to users

Revision ID: dfcfbb60ef1c
Revises: c2d3e4f5a6b7
Create Date: 2026-09-02

Gap 369 (Granular Role-Based Feature Visibility). Adds a 4th per-user
permission flag, `can_send_invoices`, alongside the existing can_train /
can_audit / can_load added by f6a7b8c9d0e1 (Feature 1.1) -- same shape, same
least-privilege default, same reasoning: a newly created user gets nothing
until an Admin grants it via the Admin console.

Defaults False and existing rows are backfilled to False for the same reason
f6a7b8c9d0e1 did not backfill Admins to True: Admin implies all four
permissions at context-resolution time (dependencies.get_tenant_context /
models.RoleMapper.resolve_permissions), so storing it here would duplicate
the rule and leave a stale flag behind if someone is later demoted from Admin.

This does NOT replace Tenant.send_invoices_enabled (feature_16_settings.md) --
that tenant-wide switch (gated on billing plan + an outbound authorized email)
stays exactly as it is. This column is the per-user visibility layer on top of
it; both must be true for a given user to see/use Send Invoices.

down_revision taken from a real `alembic heads` run (single head c2d3e4f5a6b7)
immediately before writing this file, not assumed -- see be_features_tracker.md
Gap 60 for the multi-head incident this check guards against.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'dfcfbb60ef1c'
down_revision: Union[str, None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("can_send_invoices", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "can_send_invoices")
