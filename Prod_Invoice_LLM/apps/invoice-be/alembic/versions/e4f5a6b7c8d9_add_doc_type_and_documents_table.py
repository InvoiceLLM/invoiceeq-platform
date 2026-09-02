"""add invoice.doc_type/doc_type_evidence + the documents table (Feature 27 G9 / E10)

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-09-02

**One migration for both changes, deliberately.** The two `invoice` columns and
the new `documents` table are not two independent facts: it is the existence of
`documents` that makes `invoice.doc_type` mean *"which sub-type of invoice is
this"* rather than *"which of ten kinds of paper is this"*. Split across two
revisions, a database could sit at a state where `invoice.doc_type` exists and
`documents` does not -- and in that state `queue_worker/handlers.py` would have
nowhere to route a classified delivery note, so the honest options would be to
write it into `invoice` (the exact thing E10 exists to prevent) or to fail the
extraction. One revision, no such state.

`invoice.doc_type` / `invoice.doc_type_evidence` are **nullable with no server
default**, so every existing row stays valid with no backfill and a flag-OFF run
writes NULL exactly as it writes nothing today. NULL means "never classified" --
never "not an invoice". With `ENABLE_GENERIC_EXTRACTION` false the classifier
node is not in the compiled graph at all, so NULL is what every row gets.

`documents` starts empty and there is **no data migration**. Nothing is moved out
of `invoice`: rows that predate this migration were ingested when the pipeline
was implicitly invoice-only, and re-typing them retroactively would mean deciding
after the fact that historical spend aggregates were wrong. Going forward,
`handlers.py` writes the `documents` row and deletes the upload-time placeholder
`invoice` row in one transaction.

Column choices worth stating, since they differ from `invoice` on purpose:
  * Every money column is nullable. A delivery note prints quantities and no
    prices by design; a framework contract has no grand total. NULL means "the
    document did not state it" and is never zero (Gap 283's distinction, from
    the other side).
  * `status` defaults to "EXTRACTED" -- the `EXTRACTED`/`EXTRACT_FAILED` pair the
    REFERENCE direction profile already uses, not the invoice vocabulary. A
    delivery note is never approved, sent or paid.
  * No `coordinates` column exists on this table at all. `_run_ocr` calls
    `prebuilt-invoice` for every document (§2A/A1 -- there is no OCR-model
    selector in this feature), so every box it returns is labelled with a DI
    *invoice* field name. An auditor overlay drawn over a purchase order from
    those boxes would put a "grand_total" label around whatever DI guessed. An
    empty overlay is honest; a mislabelled one is not, and the cleanest way to
    guarantee that is to have no column to put them in.
  * `deleted_at` mirrors Gap 192's soft delete and `last_enqueued_at` /
    `processing_attempts` mirror FE Gap 81/84's re-enqueue bookkeeping, so the
    existing sweep and audit-trail patterns transfer unchanged.

Index names are the ones SQLModel itself generates from `Field(index=True)`
(`ix_documents_<column>`) plus the two composites declared in
`Document.__table_args__`. That is not cosmetic: `SQLModel.metadata.create_all()`
is what the test suite uses, so a migration that named them differently would
produce a schema that disagrees with the model on any database built either way.

down_revision `d3e4f5a6b7c8` confirmed as the single head by walking every
revision/down_revision pair in `alembic/versions/` at write time -- the spec's
own citation (`c2d3e4f5a6b7`) was already stale, because Feature 26 Part 2's H4
migration landed on top of it during this same session (be_features_tracker.md
Gap 60 is the multi-head incident this check exists for).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON_VARIANT = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=sa.Text()), "postgresql"
)


def upgrade() -> None:
    # --- 1. The invoice sub-type columns (E10) ------------------------------
    op.add_column(
        "invoice",
        sa.Column("doc_type", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
    )
    op.add_column(
        "invoice",
        sa.Column("doc_type_evidence", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )

    # --- 2. The non-invoice document table (E10) ----------------------------
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("file_path", sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=False),
        sa.Column("file_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True),
        sa.Column("doc_type", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
        sa.Column("doc_type_evidence", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("doc_type_confidence", sa.Float(), nullable=True),
        sa.Column("party_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("counterparty_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("doc_number", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("po_number", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("reference_numbers", _JSON_VARIANT, nullable=True),
        sa.Column("doc_date", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("currency", sqlmodel.sql.sqltypes.AutoString(length=8), nullable=True),
        sa.Column("subtotal", sa.Float(), nullable=True),
        sa.Column("tax_amount", sa.Float(), nullable=True),
        sa.Column("discount_amount", sa.Float(), nullable=True),
        sa.Column("grand_total", sa.Float(), nullable=True),
        sa.Column("items", _JSON_VARIANT, nullable=True),
        sa.Column("taxes", _JSON_VARIANT, nullable=True),
        sa.Column("payment_terms", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("delivery_terms", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("incoterms", sqlmodel.sql.sqltypes.AutoString(length=32), nullable=True),
        sa.Column("notes", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column(
            "status",
            sqlmodel.sql.sqltypes.AutoString(length=32),
            nullable=False,
            server_default="EXTRACTED",
        ),
        sa.Column("sa_alerts", _JSON_VARIANT, nullable=True),
        sa.Column("source_document_json", _JSON_VARIANT, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("last_enqueued_at", sa.DateTime(), nullable=True),
        sa.Column("processing_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("submitted_by_email", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_tenant_id", "documents", ["tenant_id"])
    op.create_index("ix_documents_batch_id", "documents", ["batch_id"])
    op.create_index("ix_documents_file_hash", "documents", ["file_hash"])
    op.create_index("ix_documents_doc_type", "documents", ["doc_type"])
    op.create_index("ix_documents_deleted_at", "documents", ["deleted_at"])
    op.create_index("ix_documents_tenant_doc_type", "documents", ["tenant_id", "doc_type"])
    op.create_index("ix_documents_tenant_created_at", "documents", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_documents_tenant_created_at", table_name="documents")
    op.drop_index("ix_documents_tenant_doc_type", table_name="documents")
    op.drop_index("ix_documents_deleted_at", table_name="documents")
    op.drop_index("ix_documents_doc_type", table_name="documents")
    op.drop_index("ix_documents_file_hash", table_name="documents")
    op.drop_index("ix_documents_batch_id", table_name="documents")
    op.drop_index("ix_documents_tenant_id", table_name="documents")
    op.drop_table("documents")
    op.drop_column("invoice", "doc_type_evidence")
    op.drop_column("invoice", "doc_type")
