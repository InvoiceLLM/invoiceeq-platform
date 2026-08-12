"""add webhook_delivery_logs + webhook_subscriptions.event_failure_counts

Revision ID: b8c1d4e7f209
Revises: a2b3c4d5e6f7
Create Date: 2026-08-12

Gap 194 (Webhooks reliability):
  * `webhook_delivery_logs` -- one row per delivery attempt series, so "did
    this event actually fire?" is answerable from inside the product. Delivery
    errors are swallowed by design (a subscriber being down must never fail the
    invoice operation that triggered the event), so without this table a
    completely broken fan-out was indistinguishable from a clean one.
  * `webhook_subscriptions.event_failure_counts` -- consecutive failures are
    now tracked per event type rather than as one flat counter, so an endpoint
    that rejects one event type cannot auto-disable the event types it has been
    accepting. `consecutive_failures` is retained as the denormalised max of
    that map (existing UI + API shape unchanged); it is backfilled into the new
    map lazily by the delivery path, so no data migration is needed.

NOTE (pre-existing, not introduced here): three sibling revisions currently
branch off "f9a0b1c2d3e4" -- a2b3c4d5e6f7 (add_dropped_inbound_emails),
c1d2e3f4a5b6 (add_invoice_overdue_notified_at) and c9d0e1f2a3b4
(add_tenant_api_key_columns), each added by a different in-flight change. So
`alembic heads` reports multiple heads and `alembic upgrade head` needs a merge
revision before it will run. This revision extends one of those existing heads
(a2b3c4d5e6f7) rather than adding a fourth sibling; consolidating the branch
belongs to whoever merges those three, not to Gap 194.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "b8c1d4e7f209"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "webhook_subscriptions",
        sa.Column(
            "event_failure_counts",
            sa.JSON().with_variant(JSONB, "postgresql"),
            nullable=False,
            server_default="{}",
        ),
    )

    op.create_table(
        "webhook_delivery_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_webhook_delivery_logs_tenant_id"), "webhook_delivery_logs", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_webhook_delivery_logs_subscription_id"),
        "webhook_delivery_logs",
        ["subscription_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_webhook_delivery_logs_created_at"), "webhook_delivery_logs", ["created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_webhook_delivery_logs_created_at"), table_name="webhook_delivery_logs")
    op.drop_index(op.f("ix_webhook_delivery_logs_subscription_id"), table_name="webhook_delivery_logs")
    op.drop_index(op.f("ix_webhook_delivery_logs_tenant_id"), table_name="webhook_delivery_logs")
    op.drop_table("webhook_delivery_logs")
    op.drop_column("webhook_subscriptions", "event_failure_counts")
