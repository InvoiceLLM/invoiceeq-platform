"""invoice completed_at timestamp

Dashboard's average_processing_time metric had no real elapsed-time signal to
compute from (Invoice only had created_at) and was faking a value from
document complexity. This adds a completed_at column, set once in
handlers.py::handle_process_invoice when the pipeline finalizes a status, so
average_processing_time can be a real created_at -> completed_at duration.

Revision ID: a1b2c3d4e5f6
Revises: f3a9c7b21d84
Create Date: 2026-07-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'f3a9c7b21d84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('invoice', sa.Column('completed_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('invoice', 'completed_at')
