"""Feature 18: chat-correction lane tables + chat message result snapshot

Adds, in one migration (the whole Feature 18 schema change is here -- the
structured rule object needed none, because `extraction_templates.rules` is
already a JSON column):

  - tenant_chat_settings  (Gap 230) — Chat response style moves off the Global
                          INBOUND ExtractionTemplate row into its own table
  - tenant_chat_rules     (Gap 232) — committed chat-behaviour rules, structurally
                          separate from extraction constraints
  - chat_feedback.reason / .note        (Gap 232) — thumbs-down triage input
  - chatmessage.result_invoice_ids      (Gap 231) — which invoices fed a reply

Data migration, deliberately NON-DESTRUCTIVE: existing
`extraction_templates.rules -> 'chat_style'` dicts on each tenant's Global
INBOUND row are copied into `tenant_chat_settings`. The source key is
**left in place** -- it is tenant data, and leaving it means downgrading this
revision loses nothing and `_get_chat_style_block()`'s previous behaviour is
recoverable by reverting code alone.

Revision ID: f18a0c4b7d21
Revises: fe6371baa50d
Create Date: 2026-08-13
"""
from typing import Sequence, Union
import json
import uuid
from datetime import datetime

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = "f18a0c4b7d21"
down_revision: Union[str, None] = "fe6371baa50d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mirrors models.JSON_VARIANT: JSONB on PostgreSQL, plain JSON elsewhere (SQLite).
JSON_VARIANT = sa.JSON().with_variant(
    sa.dialects.postgresql.JSONB(astext_type=sa.Text()), "postgresql"
)


def _migrate_chat_style() -> None:
    """Copy each tenant's Global INBOUND `rules['chat_style']` into the new table.

    Reads through plain SQL rather than the ORM so this migration keeps working
    if `models.py` changes shape later. Wrapped defensively: a tenant with a
    malformed `rules` blob must not be able to fail the whole deploy's migration.
    """
    connection = op.get_bind()
    try:
        rows = connection.execute(
            sa.text(
                "SELECT tenant_id, rules FROM extraction_templates "
                "WHERE vendor_name IS NULL AND flow_direction = 'INBOUND'"
            )
        ).fetchall()
    except Exception:
        # No extraction_templates table yet (fresh DB built from metadata) --
        # nothing to migrate.
        return

    now = datetime.utcnow()
    for tenant_id, rules in rows:
        if isinstance(rules, str):
            try:
                rules = json.loads(rules)
            except (TypeError, ValueError):
                continue
        if not isinstance(rules, dict):
            continue
        style = rules.get("chat_style")
        if not isinstance(style, dict):
            continue

        connection.execute(
            sa.text(
                "INSERT INTO tenant_chat_settings "
                "(id, tenant_id, response_length, tone, custom_instructions, created_at, updated_at) "
                "VALUES (:id, :tenant_id, :response_length, :tone, :custom_instructions, :created_at, :updated_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": str(tenant_id),
                "response_length": str(style.get("response_length") or "balanced")[:20],
                "tone": str(style.get("tone") or "conversational")[:20],
                "custom_instructions": str(style.get("custom_instructions") or "")[:2000],
                "created_at": now,
                "updated_at": now,
            },
        )
        # NOTE: rules['chat_style'] is deliberately NOT deleted here. See the
        # module docstring -- this is a copy, not a move.


def upgrade() -> None:
    op.create_table(
        "tenant_chat_settings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("response_length", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False, server_default="balanced"),
        sa.Column("tone", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False, server_default="conversational"),
        sa.Column("custom_instructions", sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_chat_settings_tenant"),
    )
    op.create_index("idx_tenant_chat_settings_tenant", "tenant_chat_settings", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_tenant_chat_settings_tenant_id"), "tenant_chat_settings", ["tenant_id"], unique=False)

    op.create_table(
        "tenant_chat_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("category", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column("pattern", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False, server_default=""),
        sa.Column("context_text", sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=False, server_default=""),
        sa.Column("created_by", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_tenant_chat_rules_tenant_enabled", "tenant_chat_rules", ["tenant_id", "enabled"], unique=False)
    op.create_index(op.f("ix_tenant_chat_rules_tenant_id"), "tenant_chat_rules", ["tenant_id"], unique=False)

    # chat_feedback: triage reason + optional secondary note. Both nullable --
    # every pre-existing vote (and every thumbs-up) legitimately has neither.
    with op.batch_alter_table("chat_feedback", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reason", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True))
        batch_op.add_column(sa.Column("note", sqlmodel.sql.sqltypes.AutoString(length=2000), nullable=True))

    # chatmessage: result-set snapshot. server_default '[]' so existing rows read
    # back as an empty list rather than NULL, matching what the model expects.
    with op.batch_alter_table("chatmessage", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("result_invoice_ids", JSON_VARIANT, nullable=True, server_default="[]")
        )

    _migrate_chat_style()


def downgrade() -> None:
    with op.batch_alter_table("chatmessage", schema=None) as batch_op:
        batch_op.drop_column("result_invoice_ids")

    with op.batch_alter_table("chat_feedback", schema=None) as batch_op:
        batch_op.drop_column("note")
        batch_op.drop_column("reason")

    op.drop_index(op.f("ix_tenant_chat_rules_tenant_id"), table_name="tenant_chat_rules")
    op.drop_index("idx_tenant_chat_rules_tenant_enabled", table_name="tenant_chat_rules")
    op.drop_table("tenant_chat_rules")

    op.drop_index(op.f("ix_tenant_chat_settings_tenant_id"), table_name="tenant_chat_settings")
    op.drop_index("idx_tenant_chat_settings_tenant", table_name="tenant_chat_settings")
    op.drop_table("tenant_chat_settings")
    # Nothing to restore in extraction_templates: upgrade() copied
    # rules['chat_style'] rather than moving it, so the source data was never
    # removed and is still exactly where it was.
