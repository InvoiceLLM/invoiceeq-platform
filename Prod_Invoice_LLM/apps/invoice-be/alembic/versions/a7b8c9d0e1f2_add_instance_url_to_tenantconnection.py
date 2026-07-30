"""add instance_url to tenantconnection

Revision ID: a7b8c9d0e1f2
Revises: d2e3f4a5b6c7
Create Date: 2026-07-30

Feature 9 (Connectors) Gap 98 follow-up: Salesforce's REST API base is
per-org (unlike Google Drive's fixed www.googleapis.com), returned as
`instance_url` in Salesforce's own token response. Storing it per-connection
is what lets a future real Salesforce Connected App actually call the API
once a tenant connects -- google_drive rows leave this column null.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tenantconnection',
        sa.Column('instance_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('tenantconnection', 'instance_url')
