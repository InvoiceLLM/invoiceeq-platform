"""add chat_attachments (Feature 26 / Gap 366)

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-09-01

One new table holding a reference document (purchase order or quotation) a user
attached to a chat session, so chat can compare it against the invoices it was
supposed to produce.

Deliberately a NEW table rather than rows in `invoice` (Feature 26, decision
D2). A quotation is not a payable; putting one in `invoice` would silently move
spend aggregates, /dashboard/insights, the AUDIT_REQUIRED count, billing quota
and the RAG index. Nothing about this table feeds any of those five.

`session_id` carries a real FK to `chatsession.id` so an attachment cannot
outlive the session it belongs to as an orphan. `tenant_id` is indexed but
deliberately NOT an FK-only check -- every read path filters on it explicitly
(the same belt-and-braces the rest of this schema uses), because tenant
isolation on a document holding another company's pricing is not something to
leave to a join.

The three D3 caps (PDF-only, 10 MB, 5 per session) are enforced in the request
path in `routers/chat_attachments.py`, not here: two of the three are inherently
request-shaped (a content-type and a byte count), and a CHECK constraint that
only covered the third would read as though all three were enforced at the DB.
`file_size_bytes` is persisted so the size cap is auditable after the fact.

**No backfill and no data migration.** The table starts empty; every predicate
in the feature reads "no row" as "no attachment on this turn", which is the
fail-closed answer and is exactly how chat behaved before this feature.

down_revision b1c2d3e4f5a6 confirmed as the single head by walking every
revision/down_revision pair in `alembic/versions/` (be_features_tracker.md Gap
60 is the multi-head incident this check exists for).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_JSON_VARIANT = sa.JSON().with_variant(
    postgresql.JSONB(astext_type=sa.Text()), "postgresql"
)


def upgrade() -> None:
    op.create_table(
        "chat_attachments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column(
            "filename", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False
        ),
        sa.Column(
            "blob_path", sqlmodel.sql.sqltypes.AutoString(length=1024), nullable=False
        ),
        sa.Column(
            "doc_type",
            sqlmodel.sql.sqltypes.AutoString(length=32),
            nullable=False,
            server_default="OTHER",
        ),
        sa.Column(
            "file_size_bytes", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "extraction_status",
            sqlmodel.sql.sqltypes.AutoString(length=32),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("extracted_json", _JSON_VARIANT, nullable=True),
        sa.Column(
            "doc_number", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True
        ),
        sa.Column(
            "party_name", sqlmodel.sql.sqltypes.AutoString(length=512), nullable=True
        ),
        sa.Column("doc_date", sa.Date(), nullable=True),
        sa.Column(
            "currency", sqlmodel.sql.sqltypes.AutoString(length=8), nullable=True
        ),
        sa.Column("grand_total", sa.Float(), nullable=True),
        sa.Column("candidate_invoice_ids", _JSON_VARIANT, nullable=True),
        sa.Column("confirmed_invoice_ids", _JSON_VARIANT, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["chatsession.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_chat_attachment_tenant", "chat_attachments", ["tenant_id"]
    )
    op.create_index(
        "idx_chat_attachment_session", "chat_attachments", ["session_id"]
    )


def downgrade() -> None:
    op.drop_index("idx_chat_attachment_session", table_name="chat_attachments")
    op.drop_index("idx_chat_attachment_tenant", table_name="chat_attachments")
    op.drop_table("chat_attachments")
