"""add clerk_org_id to tenant

Revision ID: b3c4d5e6f7a8
Revises: 71d18e2c3349
Create Date: 2026-07-28

Ported from the auth-feature-4 branch's clerk_org_id migration, rebased
onto the current head instead of that branch's stale 7504f993dd7e base.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = '71d18e2c3349'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tenant',
        sa.Column('clerk_org_id', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True)
    )
    op.create_index(op.f('ix_tenant_clerk_org_id'), 'tenant', ['clerk_org_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_tenant_clerk_org_id'), table_name='tenant')
    op.drop_column('tenant', 'clerk_org_id')
