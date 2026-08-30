"""add tenant_workflow_configs (Feature 25 / Gap 336: Plug & Play workflow policy)

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-08-29

The tenant's answers to the Plug & Play workflow wizard: input channels, the
audit policy, output destinations and how chat is reached. One row per tenant,
enforced by UNIQUE(tenant_id) — same shape as tenant_autopilot_configs, which is
the closest existing analogue and which this table is deliberately modelled on.

Note what this table is NOT. `audit_policy` here mirrors `tenant.api_key_scope`
(added by Gap 335's migration d8e9f0a1b2c3) in user-facing wording:

    'full_automation' <-> tenant.api_key_scope = 'actions'
    'strict_review'   <-> tenant.api_key_scope = 'readonly'

`tenant.api_key_scope` remains the only column the auth layer reads, and
`GET /api/v1/settings/workflow` derives the policy back from it rather than from
this column, so the two cannot present a drifted answer. This column stores what
the wizard was told; it is never an authorisation input.

No backfill: a tenant with no row has simply never run the wizard, and the GET
endpoint reports defaults for that case **without writing a row** (a read must
not have a side effect). Since `api_key_scope` already defaulted every existing
tenant to 'readonly', an un-configured tenant reads back as 'strict_review',
which is the fail-closed answer and matches what is actually enforced.

down_revision e9f0a1b2c3d4 confirmed as the single head by an actual
`alembic heads` run, not by reading files (be_features_tracker.md Gap 60 is the
multi-head incident this check exists for).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, None] = "e9f0a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON_VARIANT = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=sa.Text()), "postgresql"
)


def upgrade() -> None:
    op.create_table(
        "tenant_workflow_configs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("input_channels", _JSON_VARIANT, nullable=True),
        sa.Column(
            "audit_policy",
            sqlmodel.sql.sqltypes.AutoString(length=32),
            nullable=False,
            server_default="strict_review",
        ),
        sa.Column("output_destinations", _JSON_VARIANT, nullable=True),
        sa.Column(
            "chat_access",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=False,
            server_default="dashboard",
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenant.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_workflow_config_tenant"),
    )
    op.create_index(
        "idx_workflow_config_tenant",
        "tenant_workflow_configs",
        ["tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_workflow_config_tenant", table_name="tenant_workflow_configs")
    op.drop_table("tenant_workflow_configs")
