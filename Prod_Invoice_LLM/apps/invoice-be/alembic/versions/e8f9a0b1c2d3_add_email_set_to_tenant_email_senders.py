"""Add email_set + global unique email on tenant_email_senders.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-08-10

Feature 14: dual authorized sets; one global app mailbox; sender email uniquely
maps to one tenant + inbound|outbound set.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenant_email_senders",
        sa.Column(
            "email_set",
            sa.String(length=20),
            nullable=False,
            server_default="inbound",
        ),
    )
    op.create_index(
        op.f("ix_tenant_email_senders_email_set"),
        "tenant_email_senders",
        ["email_set"],
        unique=False,
    )
    # One authorized address → one tenant worldwide (global mailbox model).
    op.drop_constraint("uq_tenant_email_senders_tenant_email", "tenant_email_senders", type_="unique")
    op.create_unique_constraint("uq_tenant_email_senders_email", "tenant_email_senders", ["email"])


def downgrade() -> None:
    op.drop_constraint("uq_tenant_email_senders_email", "tenant_email_senders", type_="unique")
    op.create_unique_constraint(
        "uq_tenant_email_senders_tenant_email",
        "tenant_email_senders",
        ["tenant_id", "email"],
    )
    op.drop_index(op.f("ix_tenant_email_senders_email_set"), table_name="tenant_email_senders")
    op.drop_column("tenant_email_senders", "email_set")
