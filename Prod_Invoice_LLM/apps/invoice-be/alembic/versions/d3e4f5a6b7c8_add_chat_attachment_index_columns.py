"""add chat_attachments index/TTL columns (Feature 26 Part 2 / task H4)

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-09-02

Three columns on the existing `chat_attachments` table (Feature 26 Part 2,
decision E-6): `chunk_count`, `indexed_at`, `expires_at`.

**No new table.** E-6 is explicit that this extends `chat_attachments` rather
than creating a `chat_documents` sibling: a second table would fork
`_require_owned_attachment()` and `_require_owned_session()` -- two
tenant-ownership check paths for the same class of object -- and a purchase
order holds another company's negotiated pricing, which is the last surface
where that should be duplicated.

Every column is nullable or defaulted, so **every existing row stays valid with
no backfill**. That matters for the two nulls in particular:
  * `indexed_at IS NULL` means "not embedded", which is the truthful state of
    every row written before this migration -- the embed step did not exist.
  * `expires_at IS NULL` means "no expiry". The task H8 sweeper must read a null
    as KEEP, never as "expired at the epoch"; a sweeper that read it the other
    way would delete every Part 1 attachment on its first run.
`chunk_count` gets a server_default of 0 rather than being nullable, because
"how many chunks" has a real zero and NULL would just be a second way to spell
it (the same choice `file_size_bytes` made in the parent migration).

`indexed_at`/`expires_at` are `sa.DateTime()` without timezone, matching
`created_at` on this table and the rest of this schema (values are naive UTC
from `datetime.utcnow()`); a timezone-aware column here would be the only one on
the table and would compare oddly against `created_at`.

down_revision `c2d3e4f5a6b7` confirmed as the single head by walking every
revision/down_revision pair in `alembic/versions/` at write time -- the spec's
own citation of that revision was re-verified rather than trusted
(be_features_tracker.md Gap 60 is the multi-head incident this check exists
for).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_attachments",
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "chat_attachments", sa.Column("indexed_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "chat_attachments", sa.Column("expires_at", sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("chat_attachments", "expires_at")
    op.drop_column("chat_attachments", "indexed_at")
    op.drop_column("chat_attachments", "chunk_count")
