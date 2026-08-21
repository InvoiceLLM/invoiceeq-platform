"""merge chatmessage status columns branch and tenant cancel_requested_at branch

Revision ID: f3e8b2a1d6c9
Revises: a00f1b9f7924, d7f4a1c8e29b
Create Date: 2026-08-21

Live outage, 2026-08-21: `a00f1b9f7924` (BE Gap 264, tenant cancel_requested_at)
and `d7f4a1c8e29b` (chatmessage status columns) were two independent branches
off the migration history -- `a00f1b9f7924` parents on `6c60f6e907a0`,
`d7f4a1c8e29b` parents on `e1f2a3b4c5d6` (itself on a separate line back to
`f3a9c7b21d84`). Neither branch referenced the other, and no merge migration
was ever generated to reconcile them. This went unnoticed because no clean
`alembic upgrade head` had run end-to-end in a while -- the deployed DB was
stamped at `a00f1b9f7924` (one branch's tip), while `e1f2a3b4c5d6` and
everything chained after it on the other branch was never applied there.

The first deploy to actually run `alembic upgrade head` against this history
(2026-08-21, ~10:00 UTC) hit Alembic's "Multiple head revisions are present"
error at startup and crashed before the app could come up, taking the whole
backend down. This merge migration reconciles the two branches into one head,
same pattern already used three times before in this repo's history
(`82a8f00b564d`, `c097b6848d7c`, `6505088bd42d`). No-op -- both branches'
columns already exist independently on any DB that applies both chains.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'f3e8b2a1d6c9'
down_revision: Union[str, None] = ('a00f1b9f7924', 'd7f4a1c8e29b')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
