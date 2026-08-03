"""add granular RBAC permission flags to users

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-08-01

Feature 1.1 (Granular RBAC), Task 1.1.1. Adds can_train / can_audit / can_load
to `users`. All three default to False -- least privilege, per the feature's
access model: a newly created user gets nothing beyond Dashboard/Chat/Help
until an Admin grants more.

Existing rows are backfilled to False for the same reason. Admins are NOT
backfilled to True here: Admin implies all three at context-resolution time
(dependencies.get_tenant_context), so storing it would duplicate the rule and
leave stale flags behind if someone is later demoted from Admin.

down_revision was taken from an actual `alembic heads` run (single head
e5f6a7b8c9d0), not assumed -- see be_features_tracker.md Gap 60 for the
multi-head incident this guards against.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for column in ("can_train", "can_audit", "can_load"):
        op.add_column(
            "users",
            sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    for column in ("can_load", "can_audit", "can_train"):
        op.drop_column("users", column)
