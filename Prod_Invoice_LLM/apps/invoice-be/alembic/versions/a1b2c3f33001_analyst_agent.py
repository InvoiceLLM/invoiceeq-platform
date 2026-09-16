"""Feature 33 (ATLAS Analyst Agent) - Phase 0 schema.

Add-only migration with no backfill. All code gated behind ENABLE_* flags.

Critical FK rule: fact.source_id uses ON DELETE SET NULL (not CASCADE).
TTL sweeper deletes chat_attachments rows; CASCADE would destroy Facts.
User hard-delete API explicitly runs: DELETE FROM fact WHERE source_id=:id

Revision ID: a1b2c3f33001
Revises:     a1b2c3f30004
Create Date: 2026-09-15
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

revision: str = "a1b2c3f33001"
down_revision = "a1b2c3f30004"
branch_labels = None
depends_on = None

JSON_VARIANT = sa.JSON().with_variant(JSONB, "postgresql")
UUID_VARIANT = PG_UUID(as_uuid=True)


def upgrade():
    # 1. chatsession.clearance
    op.add_column("chatsession", sa.Column("clearance", sa.String(8), nullable=False, server_default="ops"))
    # 2. chat_attachments.clearance
    op.add_column("chat_attachments", sa.Column("clearance", sa.String(8), nullable=False, server_default="ops"))
    # 3. insight.scope + insight.clearance
    op.add_column("insight", sa.Column("scope", sa.String(16), nullable=False, server_default="attachment"))
    op.add_column("insight", sa.Column("clearance", sa.String(8), nullable=False, server_default="ops"))
    op.create_index("ix_insight_scope", "insight", ["scope"])
    op.create_index("ix_insight_clearance", "insight", ["clearance"])
    # 4. tenant_chat_rules.source
    op.add_column("tenant_chat_rules", sa.Column("source", sa.String(32), nullable=False, server_default="user"))
    # 5. users.ui_prefs
    op.add_column("users", sa.Column("ui_prefs", JSON_VARIANT, nullable=True))
    # 6. fact table - ON DELETE SET NULL on source_id
    op.create_table(
        "fact",
        sa.Column("id", UUID_VARIANT, primary_key=True),
        sa.Column("tenant_id", UUID_VARIANT, nullable=False),
        sa.Column("clearance", sa.String(8), nullable=False, server_default="ops"),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("subject_kind", sa.String(64), nullable=False),
        sa.Column("subject_id", sa.String(255), nullable=False),
        sa.Column("counterparty_id", sa.String(255), nullable=True),
        sa.Column("as_of", sa.Date(), nullable=True),
        sa.Column("figures", JSON_VARIANT, nullable=True),
        sa.Column("source_kind", sa.String(32), nullable=True),
        sa.Column("source_id", UUID_VARIANT, nullable=True),
        sa.Column("evidence", JSON_VARIANT, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["chat_attachments.id"],
            name="fk_fact_source_id_chat_attachments", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fact_tenant_id", "fact", ["tenant_id"])
    op.create_index("ix_fact_subject", "fact", ["subject_kind", "subject_id"])
    op.create_index("ix_fact_source_id", "fact", ["source_id"])
    op.create_index("ix_fact_kind", "fact", ["kind"])
    op.create_index("ix_fact_clearance", "fact", ["clearance"])
    op.create_index("ix_fact_as_of", "fact", ["as_of"])
    # 7. today_item
    op.create_table(
        "today_item",
        sa.Column("id", UUID_VARIANT, primary_key=True),
        sa.Column("tenant_id", UUID_VARIANT, nullable=False),
        sa.Column("section", sa.String(32), nullable=False),
        sa.Column("clearance", sa.String(8), nullable=False, server_default="ops"),
        sa.Column("text", sa.String(2000), nullable=False, server_default=""),
        sa.Column("seeded_question", sa.String(1000), nullable=True),
        sa.Column("insight_id", UUID_VARIANT, nullable=True),
        sa.Column("meta", JSON_VARIANT, nullable=True),
        sa.Column("severity", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("cleared_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_today_item_tenant_id", "today_item", ["tenant_id"])
    op.create_index("ix_today_item_section", "today_item", ["section"])
    op.create_index("ix_today_item_clearance", "today_item", ["clearance"])
    op.create_index("ix_today_item_severity", "today_item", ["severity"])
    op.create_index("ix_today_item_cleared_at", "today_item", ["cleared_at"])
    # 8. input_request
    op.create_table(
        "input_request",
        sa.Column("id", UUID_VARIANT, primary_key=True),
        sa.Column("tenant_id", UUID_VARIANT, nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("phrase", sa.String(1000), nullable=False, server_default=""),
        sa.Column("unlock_amount", sa.Float(), nullable=True),
        sa.Column("unlock_currency", sa.String(8), nullable=True),
        sa.Column("unlock_count", sa.Integer(), nullable=True),
        sa.Column("clearance", sa.String(8), nullable=False, server_default="ops"),
        sa.Column("fulfilled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_input_request_tenant_id", "input_request", ["tenant_id"])
    op.create_index("ix_input_request_kind", "input_request", ["kind"])
    op.create_index("ix_input_request_fulfilled_at", "input_request", ["fulfilled_at"])
    # 9. action_log
    op.create_table(
        "action_log",
        sa.Column("id", UUID_VARIANT, primary_key=True),
        sa.Column("tenant_id", UUID_VARIANT, nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("capability", sa.String(64), nullable=False),
        sa.Column("args", JSON_VARIANT, nullable=True),
        sa.Column("result", JSON_VARIANT, nullable=True),
        sa.Column("outcome", sa.String(16), nullable=False, server_default="success"),
        sa.Column("error_message", sa.String(2000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_action_log_tenant_id", "action_log", ["tenant_id"])
    op.create_index("ix_action_log_capability", "action_log", ["capability"])
    op.create_index("ix_action_log_user_id", "action_log", ["user_id"])
    # 10. tenant_profile_rule
    op.create_table(
        "tenant_profile_rule",
        sa.Column("id", UUID_VARIANT, primary_key=True),
        sa.Column("tenant_id", UUID_VARIANT, nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.String(2000), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="atlas_onboarding"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "key", name="uq_tenant_profile_rule_tenant_key"),
    )
    op.create_index("ix_tenant_profile_rule_tenant_id", "tenant_profile_rule", ["tenant_id"])
    op.create_index("ix_tenant_profile_rule_key", "tenant_profile_rule", ["key"])


def downgrade():
    op.drop_table("tenant_profile_rule")
    op.drop_table("action_log")
    op.drop_table("input_request")
    op.drop_table("today_item")
    for idx in ["ix_fact_as_of","ix_fact_clearance","ix_fact_kind","ix_fact_source_id","ix_fact_subject","ix_fact_tenant_id"]:
        op.drop_index(idx, table_name="fact")
    op.drop_table("fact")
    op.drop_column("users", "ui_prefs")
    op.drop_column("tenant_chat_rules", "source")
    op.drop_index("ix_insight_clearance", table_name="insight")
    op.drop_index("ix_insight_scope", table_name="insight")
    op.drop_column("insight", "clearance")
    op.drop_column("insight", "scope")
    op.drop_column("chat_attachments", "clearance")
    op.drop_column("chatsession", "clearance")
