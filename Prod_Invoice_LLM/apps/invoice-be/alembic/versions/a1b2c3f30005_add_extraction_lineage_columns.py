"""BE Gap 523: Add extraction lineage columns to invoice and documents.

Persists extraction lineage (model_id, prompt_version, schema_version,
prompt_hash) on both tables so accuracy degradation, model swaps, and prompt
revisions are auditable after the fact.

Add-only migration, all columns nullable.

Revision ID: a1b2c3f30005
Revises: a1b2c3f30004
Create Date: 2026-09-14
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3f30005"
down_revision: Union[str, None] = "a1b2c3f30004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. invoice table lineage columns
    op.add_column("invoice", sa.Column("extraction_model_id", sa.String(length=128), nullable=True))
    op.add_column("invoice", sa.Column("prompt_version", sa.String(length=64), nullable=True))
    op.add_column("invoice", sa.Column("schema_version", sa.String(length=32), nullable=True))
    op.add_column("invoice", sa.Column("prompt_hash", sa.String(length=64), nullable=True))

    # 2. documents table lineage columns
    op.add_column("documents", sa.Column("extraction_model_id", sa.String(length=128), nullable=True))
    op.add_column("documents", sa.Column("prompt_version", sa.String(length=64), nullable=True))
    op.add_column("documents", sa.Column("schema_version", sa.String(length=32), nullable=True))
    op.add_column("documents", sa.Column("prompt_hash", sa.String(length=64), nullable=True))


def downgrade() -> None:
    # 1. invoice table
    op.drop_column("invoice", "prompt_hash")
    op.drop_column("invoice", "schema_version")
    op.drop_column("invoice", "prompt_version")
    op.drop_column("invoice", "extraction_model_id")

    # 2. documents table
    op.drop_column("documents", "prompt_hash")
    op.drop_column("documents", "schema_version")
    op.drop_column("documents", "prompt_version")
    op.drop_column("documents", "extraction_model_id")
