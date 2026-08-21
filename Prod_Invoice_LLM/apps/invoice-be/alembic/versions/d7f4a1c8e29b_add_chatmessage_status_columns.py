"""add_chatmessage_status_columns

Revision ID: d7f4a1c8e29b
Revises: e1f2a3b4c5d6
Create Date: 2026-08-21

Gap 209/280: the ChatMessage model (models.py) added three columns for the
queue-based async chat lifecycle -- status, job_id, error_message -- but no
migration was ever generated for them. Every chat INSERT has been failing
against real Postgres since (SQLAlchemy: column "status" of relation
"chatmessage" does not exist), breaking all chat sends. This migration adds
the missing columns to match the live model:
  - status         (VARCHAR(32), NOT NULL, DEFAULT 'completed')
  - job_id         (VARCHAR(64), NULLABLE, indexed)
  - error_message  (VARCHAR(1000), NULLABLE)

Default 'completed' on status ensures every pre-existing row (all of which
were written by the old synchronous, always-complete path) is backfilled
correctly with no behaviour change.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd7f4a1c8e29b'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'chatmessage',
        sa.Column('status', sa.String(length=32), nullable=False, server_default='completed')
    )
    op.add_column(
        'chatmessage',
        sa.Column('job_id', sa.String(length=64), nullable=True)
    )
    op.add_column(
        'chatmessage',
        sa.Column('error_message', sa.String(length=1000), nullable=True)
    )
    op.create_index('ix_chatmessage_job_id', 'chatmessage', ['job_id'])


def downgrade() -> None:
    op.drop_index('ix_chatmessage_job_id', table_name='chatmessage')
    op.drop_column('chatmessage', 'error_message')
    op.drop_column('chatmessage', 'job_id')
    op.drop_column('chatmessage', 'status')
