"""Feature 17 (Invoice Builder): invoice.source_invoice_id + invoice.builder_intent.

Lineage pointer for a cloned invoice, and the values the builder intended to
print (`BuildRequest` + server-computed `Totals` + render mode) so
`verify_builder_readback()` can compare intent against what the extractor read
back off the generated PDF.

Both columns are nullable and additive: every existing row — all of them
uploads — stays valid with no backfill.

down_revision `f6a1b2c3d4e5` confirmed as the single head by a real
`ScriptDirectory.get_heads()` call immediately before writing this file
(`alembic.exe` is blocked on this machine; the Python API is used instead).

Revision ID: a1b2c3d4e5f8
Revises: f6a1b2c3d4e5
Create Date: 2026-09-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "a1b2c3d4e5f8"
down_revision: Union[str, None] = "f6a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_VARIANT = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.add_column("invoice", sa.Column("source_invoice_id", sa.Uuid(), nullable=True))
    op.add_column("invoice", sa.Column("builder_intent", JSON_VARIANT, nullable=True))
    op.create_foreign_key(
        "fk_invoice_source_invoice_id_invoice",
        "invoice", "invoice",
        ["source_invoice_id"], ["id"],
    )
    op.create_index(
        "ix_invoice_tenant_source_invoice_id",
        "invoice",
        ["tenant_id", "source_invoice_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_invoice_tenant_source_invoice_id", table_name="invoice")
    op.drop_constraint("fk_invoice_source_invoice_id_invoice", "invoice", type_="foreignkey")
    op.drop_column("invoice", "builder_intent")
    op.drop_column("invoice", "source_invoice_id")
