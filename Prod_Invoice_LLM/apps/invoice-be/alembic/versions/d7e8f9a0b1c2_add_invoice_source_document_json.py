"""add source_document_json to invoice (Gap 178)

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-08-09

Gap 178: persist Azure Document Intelligence prebuilt-invoice structured
fields (line items, totals, vendor, taxes, …) as JSONB so extraction can be
compared against what DI saw on the PDF. Polygons/layout are deliberately
omitted at write time to keep rows small — those already live in
`coordinates` / `field_confidence`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, None] = "c6d7e8f9a0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoice",
        sa.Column(
            "source_document_json",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("invoice", "source_document_json")
