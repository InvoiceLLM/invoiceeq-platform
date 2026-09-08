"""Feature 30 phase 0 (30.0a, 30.0c, 30.0e, 30.0f, 30.0g) — insight lifecycle,
bank ledger, vendor master, threshold overrides, and five ChatAttachment columns.

ONE file for the whole phase-0 task group, not one per prerequisite. The dev rule
is add-only with a single `alembic upgrade head` and no backfill; five files that
must be applied in order to leave a working schema is five chances to apply four
of them. Nothing here drops, renames or rewrites anything: five nullable/defaulted
columns on `chat_attachments` and five new tables that no code path writes to
while `ENABLE_ATTACHMENT_INSIGHTS` is False.

Every new column has a default that reproduces today's behaviour on an existing
row, which is what makes "no backfill" correct rather than merely convenient:
`retained=false` means "the TTL sweep treats this row exactly as it did
yesterday", `insights=NULL` means "no bubble was ever computed", and
`insights_version=0` means "the FE has nothing to redraw".

down_revision `e7f8a9b0c1d2` confirmed as the single head by `alembic heads`
against `localhost:5433/invoice_db` immediately before writing this file.

Revision ID: a1b2c3f30001
Revises: e7f8a9b0c1d2
Create Date: 2026-09-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

revision: str = "a1b2c3f30001"
down_revision: Union[str, None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Same cross-platform JSON type `models.py` uses, restated here rather than
# imported: a migration must keep describing the schema it wrote even if the
# model module later changes its mind.
JSON_VARIANT = sa.JSON().with_variant(JSONB, "postgresql")
UUID_VARIANT = PG_UUID(as_uuid=True)


def upgrade() -> None:
    # --- 30.0a / 30.0c / 30.0d / 30.2: columns on the existing attachment row --
    op.add_column(
        "chat_attachments",
        sa.Column("retained", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("chat_attachments", sa.Column("region", sa.String(length=8), nullable=True))
    op.add_column("chat_attachments", sa.Column("statement_date", sa.Date(), nullable=True))
    op.add_column(
        "chat_attachments",
        sa.Column("insights_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("chat_attachments", sa.Column("insights", JSON_VARIANT, nullable=True))

    # --- 30.0e: the insight lifecycle ---------------------------------------
    op.create_table(
        "insight",
        sa.Column("id", UUID_VARIANT, primary_key=True),
        sa.Column("tenant_id", UUID_VARIANT, nullable=False),
        sa.Column("attachment_id", UUID_VARIANT, nullable=False),
        sa.Column("session_id", UUID_VARIANT, nullable=True),
        sa.Column("doc_type", sa.String(length=32), nullable=False, server_default="OTHER"),
        sa.Column("card", sa.String(length=64), nullable=False),
        sa.Column("finding_key", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("impact_amount", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("confidence", sa.String(length=8), nullable=False, server_default="med"),
        sa.Column("confidence_reason", sa.String(length=512), nullable=True),
        sa.Column("evidence", JSON_VARIANT, nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="OPEN"),
        sa.Column("outcome", sa.String(length=64), nullable=True),
        sa.Column("note", sa.String(length=2000), nullable=True),
        sa.Column("acted_by", sa.String(length=255), nullable=True),
        sa.Column("acted_at", sa.DateTime(), nullable=True),
        sa.Column("snoozed_until", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_insight_tenant_id", "insight", ["tenant_id"])
    op.create_index("ix_insight_attachment_id", "insight", ["attachment_id"])
    op.create_index("ix_insight_session_id", "insight", ["session_id"])
    op.create_index("ix_insight_status", "insight", ["status"])
    op.create_index("ix_insight_finding_key", "insight", ["finding_key"])
    # The idempotency guarantee the async stage relies on: recomputing the same
    # card on the same attachment must UPDATE the finding the user may already
    # have acted on, never open a second one. Enforced at the database because
    # two workers can run the same attachment's job concurrently, and a Python
    # "select then insert" cannot exclude that.
    op.create_unique_constraint(
        "uq_insight_attachment_finding", "insight", ["attachment_id", "finding_key"]
    )

    # --- 30.0c: the bank ledger ---------------------------------------------
    op.create_table(
        "bank_statement_line",
        sa.Column("id", UUID_VARIANT, primary_key=True),
        sa.Column("tenant_id", UUID_VARIANT, nullable=False),
        sa.Column("attachment_id", UUID_VARIANT, nullable=False),
        sa.Column("statement_date", sa.Date(), nullable=True),
        sa.Column("line_date", sa.Date(), nullable=True),
        sa.Column("narration", sa.String(length=1024), nullable=True),
        sa.Column("debit", sa.Float(), nullable=True),
        sa.Column("credit", sa.Float(), nullable=True),
        sa.Column("balance", sa.Float(), nullable=True),
        sa.Column("utr_ref", sa.String(length=128), nullable=True),
        sa.Column("matched_invoice_id", UUID_VARIANT, nullable=True),
        sa.Column("match_status", sa.String(length=32), nullable=False, server_default="UNMATCHED"),
        sa.Column("match_confidence", sa.String(length=8), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_bank_statement_line_tenant_id", "bank_statement_line", ["tenant_id"])
    op.create_index(
        "ix_bank_statement_line_attachment_id", "bank_statement_line", ["attachment_id"]
    )
    op.create_index(
        "ix_bank_statement_line_matched_invoice_id", "bank_statement_line", ["matched_invoice_id"]
    )

    # --- 30.0f: the vendor master -------------------------------------------
    op.create_table(
        "vendor",
        sa.Column("id", UUID_VARIANT, primary_key=True),
        sa.Column("tenant_id", UUID_VARIANT, nullable=False),
        sa.Column("canonical_name", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_vendor_tenant_id", "vendor", ["tenant_id"])
    op.create_index("ix_vendor_canonical_name", "vendor", ["canonical_name"])
    op.create_unique_constraint("uq_vendor_tenant_canonical", "vendor", ["tenant_id", "canonical_name"])

    op.create_table(
        "vendor_alias",
        sa.Column("id", UUID_VARIANT, primary_key=True),
        sa.Column("tenant_id", UUID_VARIANT, nullable=False),
        sa.Column("vendor_id", UUID_VARIANT, nullable=False),
        sa.Column("alias", sa.String(length=512), nullable=False),
        sa.Column("raw_alias", sa.String(length=512), nullable=True),
        sa.Column("confirmed_by", sa.String(length=255), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_vendor_alias_tenant_id", "vendor_alias", ["tenant_id"])
    op.create_index("ix_vendor_alias_vendor_id", "vendor_alias", ["vendor_id"])
    op.create_index("ix_vendor_alias_alias", "vendor_alias", ["alias"])
    # One normalised spelling means one vendor within a tenant. Without this, a
    # second confirmation of the same alias against a different vendor would
    # make `resolve_vendor()` non-deterministic.
    op.create_unique_constraint("uq_vendor_alias_tenant_alias", "vendor_alias", ["tenant_id", "alias"])

    # --- 30.0g: threshold overrides -----------------------------------------
    op.create_table(
        "tenant_insight_setting",
        sa.Column("id", UUID_VARIANT, primary_key=True),
        sa.Column("tenant_id", UUID_VARIANT, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_tenant_insight_setting_tenant_id", "tenant_insight_setting", ["tenant_id"])
    op.create_index("ix_tenant_insight_setting_name", "tenant_insight_setting", ["name"])
    op.create_unique_constraint(
        "uq_tenant_insight_setting", "tenant_insight_setting", ["tenant_id", "name"]
    )


def downgrade() -> None:
    op.drop_table("tenant_insight_setting")
    op.drop_table("vendor_alias")
    op.drop_table("vendor")
    op.drop_table("bank_statement_line")
    op.drop_table("insight")
    op.drop_column("chat_attachments", "insights")
    op.drop_column("chat_attachments", "insights_version")
    op.drop_column("chat_attachments", "statement_date")
    op.drop_column("chat_attachments", "region")
    op.drop_column("chat_attachments", "retained")
