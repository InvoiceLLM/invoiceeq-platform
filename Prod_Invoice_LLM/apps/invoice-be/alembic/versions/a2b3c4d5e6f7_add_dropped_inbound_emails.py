"""add dropped_inbound_emails table (Gap 124 item 6)

Revision ID: a2b3c4d5e6f7
Revises: f9a0b1c2d3e4
Create Date: 2026-08-12

Gap 124 hardening: every rejection path of the SendGrid Inbound Parse webhook
(bad/absent shared secret, oversized body, malformed multipart, unregistered
sender, exhausted free quota, ingest failure) now writes a row here so an Admin
can see mail that never became an invoice instead of it disappearing into the
container logs.

`tenant_id` is nullable because the platform mailbox is shared: a request
rejected before its From address has been matched against `tenant_email_senders`
belongs to no tenant. No FK to `tenant` for the same reason, and so a tenant
delete can never cascade away the evidence of why its mail was dropped.

BRANCHING NOTE (2026-08-12): this revision hangs off `f9a0b1c2d3e4`, which is
also the down_revision of two migrations added by concurrent in-flight work --
`c9d0e1f2a3b4_add_tenant_api_key_columns.py` and
`c1d2e3f4a5b6_add_invoice_overdue_notified_at.py`. Those are independent,
non-overlapping schema additions (different tables and columns entirely), so
the branch itself is safe, but `alembic upgrade head` will report multiple
heads until a merge revision is added once the concurrent changes land
together. This file deliberately does not invent that merge -- whichever change
lands last owns it.

All three of those migrations were briefly written with this same revision id
(a duplicate id is a hard alembic failure, not a branch); the other two have
since been renumbered, so `a2b3c4d5e6f7` now belongs to this file alone.
`b8c1d4e7f209_add_webhook_delivery_logs.py` declares `down_revision =
"a2b3c4d5e6f7"` and therefore chains off this revision -- do not renumber this
file without updating that one.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = "a2b3c4d5e6f7"
down_revision: Union[str, None] = "f9a0b1c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dropped_inbound_emails",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("detail", sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=False, server_default=""),
        sa.Column("from_email", sqlmodel.sql.sqltypes.AutoString(length=320), nullable=True),
        sa.Column("to_email", sqlmodel.sql.sqltypes.AutoString(length=320), nullable=True),
        sa.Column("sender_domain", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("filename", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True),
        sa.Column("content_length", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_dropped_inbound_emails_tenant_id"), "dropped_inbound_emails", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_dropped_inbound_emails_reason"), "dropped_inbound_emails", ["reason"], unique=False
    )
    op.create_index(
        op.f("ix_dropped_inbound_emails_from_email"), "dropped_inbound_emails", ["from_email"], unique=False
    )
    op.create_index(
        op.f("ix_dropped_inbound_emails_sender_domain"), "dropped_inbound_emails", ["sender_domain"], unique=False
    )
    # The Admin list is "newest first, capped" — this index is what keeps that
    # query off a full scan once the table has absorbed a spell of bad traffic.
    op.create_index(
        op.f("ix_dropped_inbound_emails_created_at"), "dropped_inbound_emails", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_dropped_inbound_emails_created_at"), table_name="dropped_inbound_emails")
    op.drop_index(op.f("ix_dropped_inbound_emails_sender_domain"), table_name="dropped_inbound_emails")
    op.drop_index(op.f("ix_dropped_inbound_emails_from_email"), table_name="dropped_inbound_emails")
    op.drop_index(op.f("ix_dropped_inbound_emails_reason"), table_name="dropped_inbound_emails")
    op.drop_index(op.f("ix_dropped_inbound_emails_tenant_id"), table_name="dropped_inbound_emails")
    op.drop_table("dropped_inbound_emails")
