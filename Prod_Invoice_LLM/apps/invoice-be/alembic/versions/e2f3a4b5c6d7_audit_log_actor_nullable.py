"""BE Gap 595 (CH-28): allow an AuditLog row with no user (API key / widget reads).

Chat read-access rows are written for every caller, including an API key and an
anonymous widget visitor, neither of which has a `users` row. Refusing to log
precisely the least accountable callers would defeat the purpose, so the column
becomes nullable and `actor_role` carries `api_key` / `widget` instead.

Add-only and reversible: no data is written or moved, and every existing row keeps
its actor. The downgrade can only run if no NULL actors have been written yet --
that is inherent to restoring a NOT NULL constraint, not something this migration
can avoid.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-09-16
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "audit_logs",
        "actor_user_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "audit_logs",
        "actor_user_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
