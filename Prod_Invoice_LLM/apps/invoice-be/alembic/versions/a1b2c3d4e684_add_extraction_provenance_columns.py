"""BE Gap 684: Add extraction provenance columns to invoice and documents tables.

Adds model_deployment, prompt_version, schema_version, and llm_duration_ms to:
  - invoice
  - documents

Dev add-only rule compliant: all columns are strictly nullable with no destructive backfills.
Historical rows remain NULL, representing records extracted before provenance tracking.

Revision ID: a1b2c3d4e684
Revises: e6f7a8b9c0d1
Create Date: 2026-09-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e684"
down_revision: Union[str, None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # BE Gap 684: Add provenance columns to invoice table
    op.add_column("invoice", sa.Column("model_deployment", sa.String(length=128), nullable=True))
    op.add_column("invoice", sa.Column("prompt_version", sa.String(length=64), nullable=True))
    op.add_column("invoice", sa.Column("schema_version", sa.String(length=64), nullable=True))
    op.add_column("invoice", sa.Column("llm_duration_ms", sa.Integer(), nullable=True))

    # BE Gap 684: Add provenance columns to documents table
    op.add_column("documents", sa.Column("model_deployment", sa.String(length=128), nullable=True))
    op.add_column("documents", sa.Column("prompt_version", sa.String(length=64), nullable=True))
    op.add_column("documents", sa.Column("schema_version", sa.String(length=64), nullable=True))
    op.add_column("documents", sa.Column("llm_duration_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    # BE Gap 684: Drop provenance columns from documents table
    op.drop_column("documents", "llm_duration_ms")
    op.drop_column("documents", "schema_version")
    op.drop_column("documents", "prompt_version")
    op.drop_column("documents", "model_deployment")

    # BE Gap 684: Drop provenance columns from invoice table
    op.drop_column("invoice", "llm_duration_ms")
    op.drop_column("invoice", "schema_version")
    op.drop_column("invoice", "prompt_version")
    op.drop_column("invoice", "model_deployment")
