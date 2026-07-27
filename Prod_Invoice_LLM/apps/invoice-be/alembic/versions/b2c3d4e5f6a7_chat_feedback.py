"""chat feedback table

Gap 54: no way to signal that a chat answer was wrong. Adds a chat_feedback
table (message id, session id, tenant id, vote) so a per-answer thumbs
up/down can be recorded, tied to that turn's generated_sql/citations via
message_id. Deliberately signal-only -- no auto-fix from votes, mirrors the
"correction is a signal, Trainer commit is the action" pattern already used
by the Auditor loop (Gap 26/27).

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'chat_feedback',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tenant_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('message_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('vote', sa.String(length=10), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_id'),
    )
    op.create_index(op.f('ix_chat_feedback_tenant_id'), 'chat_feedback', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_chat_feedback_session_id'), 'chat_feedback', ['session_id'], unique=False)
    op.create_index(op.f('ix_chat_feedback_message_id'), 'chat_feedback', ['message_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_chat_feedback_message_id'), table_name='chat_feedback')
    op.drop_index(op.f('ix_chat_feedback_session_id'), table_name='chat_feedback')
    op.drop_index(op.f('ix_chat_feedback_tenant_id'), table_name='chat_feedback')
    op.drop_table('chat_feedback')
