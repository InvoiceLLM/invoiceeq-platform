"""trainer global scope + rule versioning

Feature 10 (AI Trainer redesign) schema changes:
  - extraction_templates.vendor_name becomes nullable (NULL = the tenant's Global template)
  - a partial unique index enforces at most one Global (NULL-vendor) row per tenant
  - a composite unique keeps one row per (tenant, vendor)
  - extraction_templates.version column added
  - new extraction_template_versions history table (Task 10.10 rollback support)

Revision ID: f3a9c7b21d84
Revises: 7504f993dd7e
Create Date: 2026-07-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f3a9c7b21d84'
down_revision: Union[str, None] = '7504f993dd7e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. extraction_templates: nullable vendor_name, new version column, composite unique.
    #    batch_alter_table keeps this portable (Postgres = ALTER; SQLite = table rebuild).
    with op.batch_alter_table('extraction_templates', schema=None) as batch_op:
        batch_op.alter_column(
            'vendor_name',
            existing_type=sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        )
        # server_default='1' backfills the NOT NULL column for any existing rows.
        batch_op.add_column(sa.Column('version', sa.Integer(), nullable=False, server_default='1'))
        batch_op.create_unique_constraint(
            'uq_extraction_templates_tenant_vendor', ['tenant_id', 'vendor_name']
        )

    # 2. Partial unique index: at most one Global (vendor_name IS NULL) row per tenant.
    #    Both dialect-specific WHERE clauses are given so the index is partial on
    #    Postgres (prod) and SQLite (tests) alike.
    op.create_index(
        'uq_extraction_templates_tenant_global',
        'extraction_templates',
        ['tenant_id'],
        unique=True,
        postgresql_where=sa.text('vendor_name IS NULL'),
        sqlite_where=sa.text('vendor_name IS NULL'),
    )

    # 3. extraction_template_versions: append-only rule history for the drawer / rollback.
    op.create_table(
        'extraction_template_versions',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('template_id', sa.Uuid(), nullable=False),
        sa.Column('tenant_id', sa.Uuid(), nullable=False),
        sa.Column('vendor_name', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('rules', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=True),
        sa.Column('changed_by', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column('changed_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['template_id'], ['extraction_templates.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_extraction_template_versions_template_id'),
        'extraction_template_versions', ['template_id'], unique=False,
    )
    op.create_index(
        op.f('ix_extraction_template_versions_tenant_id'),
        'extraction_template_versions', ['tenant_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_extraction_template_versions_tenant_id'), table_name='extraction_template_versions')
    op.drop_index(op.f('ix_extraction_template_versions_template_id'), table_name='extraction_template_versions')
    op.drop_table('extraction_template_versions')

    op.drop_index('uq_extraction_templates_tenant_global', table_name='extraction_templates')

    with op.batch_alter_table('extraction_templates', schema=None) as batch_op:
        batch_op.drop_constraint('uq_extraction_templates_tenant_vendor', type_='unique')
        batch_op.drop_column('version')
        batch_op.alter_column(
            'vendor_name',
            existing_type=sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        )
