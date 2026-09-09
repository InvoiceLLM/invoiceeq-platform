"""Gap 507: persist the attachment's background job ids.

`/chat/jobs/{job_id}/stream` resolves ownership through `ChatMessage.job_id`,
which only exists for a chat-message job. An attachment extraction job had its
id nowhere in the database, so the check 404'd a job that was running fine and
the browser never saw the extraction finish -- the chip kept the pre-extraction
row ("no matching invoice found yet") for a document that had extracted
perfectly. Two nullable columns, written before the enqueue; add-only, no
backfill (an attachment already in flight keeps today's behaviour).

Revision ID: a1b2c3f30004
Revises: a1b2c3f30003
Create Date: 2026-09-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3f30004"
down_revision: Union[str, None] = "a1b2c3f30003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chat_attachments", sa.Column("extraction_job_id", sa.String(length=64), nullable=True))
    op.add_column("chat_attachments", sa.Column("insight_job_id", sa.String(length=64), nullable=True))
    op.create_index("ix_chat_attachments_extraction_job_id", "chat_attachments", ["extraction_job_id"])
    op.create_index("ix_chat_attachments_insight_job_id", "chat_attachments", ["insight_job_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_attachments_insight_job_id", table_name="chat_attachments")
    op.drop_index("ix_chat_attachments_extraction_job_id", table_name="chat_attachments")
    op.drop_column("chat_attachments", "insight_job_id")
    op.drop_column("chat_attachments", "extraction_job_id")
