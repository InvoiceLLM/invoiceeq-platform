"""add invoice.doc_attributes and documents.doc_attributes (Feature 27 A6 / task R8)

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-09-03

One nullable JSON column on each of the two document-bearing tables, holding the
classification attributes `services/doc_attributes.py` derives from the document's
own text: `direction`, `invoice_subtype`, `correction_method`, `fiscal_markers`,
`regional_ids`, `cumulative`, each with the evidence phrase it was decided from.

WHY A COLUMN AND NOT SCHEMA FIELDS. Amendment A2 guarantees that the INVOICE
family keeps `InvoiceExtractionSchema` byte-for-byte in both flag states -- that
guarantee is what stops a flag flip from silently dropping the India e-invoicing
block, the GST HSN codes and the round-off handling that Tasks 2.21-2.31 and the
Gap 31/33/36/43/44/46 faithfulness checks depend on. Putting A6's attributes on
the extraction schema would break exactly that. They are classification output,
not extraction output, so they belong on the row.

WHY ONE JSON COLUMN AND NOT SIX TYPED ONES. The attribute set grows by design --
A8 adds `rule_era`, and the taxonomy research names several more as v2
candidates. Every attribute is optional and none is ever filtered on, so a typed
column each would be a migration per amendment for fields nothing queries.

NULLABLE, NO SERVER DEFAULT, NO BACKFILL. NULL means "never classified", which is
true of every row written before this revision and of every row written while
`ENABLE_GENERIC_EXTRACTION` is False. It does NOT mean "classified and nothing
found" -- that state is an empty dict, written only by a run that actually looked.
Keys are likewise OMITTED when undetermined rather than stored as null, so a
reader never has to distinguish "absent" from "present but null".

JSON_VARIANT -- `sa.JSON().with_variant(JSONB, "postgresql")` -- is what
`invoice.items`, `invoice.taxes`, `documents.items` and `chatmessage.citations`
already use, so Postgres gets JSONB and SQLite gets JSON with no second code path.

down_revision `f5a6b7c8d9e0` (Feature 26's H16 `attachment_payload`) resolved from
`ScriptDirectory.get_heads()` against the live tree at write time rather than
copied from a spec -- the check Gap 60's multi-head incident exists for.
`alembic.exe` is blocked by this machine's Application Control policy; the Python
API is the substitute.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "a6b7c8d9e0f1"
down_revision: Union[str, None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_VARIANT = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.add_column(
        "invoice",
        sa.Column("doc_attributes", JSON_VARIANT, nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("doc_attributes", JSON_VARIANT, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("documents", "doc_attributes")
    op.drop_column("invoice", "doc_attributes")
