"""BE Gap 464: Add original_filename to invoice and documents tables.

The `file_path` column on both tables stores a UUID-named blob storage path,
e.g. `tenants/<id>/INBOUND/<batch>/<uuid>.pdf`. The Ingest History screen was
showing that UUID as the file name, not the original name the user gave the file.

This migration adds a nullable `original_filename VARCHAR(512)` to both tables
so the upload path can persist the real name before the file is renamed to a UUID
in blob storage.

Dev add-only rule compliant: all columns are strictly nullable with no
destructive backfills. Historical rows remain NULL and the `_file_name()` helper
in `routers/ingestion_history.py` falls back to the blob path last segment for
those rows, which is the same behaviour as before.

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c720
Create Date: 2026-09-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a4b5c6d7e8"
down_revision: Union[str, None] = "e2f3a4b5c720"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # BE Gap 464: Add original_filename to invoice table
    op.add_column(
        "invoice",
        sa.Column("original_filename", sa.String(length=512), nullable=True),
    )

    # BE Gap 464: Add original_filename to documents table
    op.add_column(
        "documents",
        sa.Column("original_filename", sa.String(length=512), nullable=True),
    )


def downgrade() -> None:
    # BE Gap 464: Drop original_filename from documents table
    op.drop_column("documents", "original_filename")

    # BE Gap 464: Drop original_filename from invoice table
    op.drop_column("invoice", "original_filename")
