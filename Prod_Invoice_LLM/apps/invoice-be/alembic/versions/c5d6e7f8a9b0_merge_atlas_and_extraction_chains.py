"""Merge the ATLAS and extraction-production-readiness migration chains.

Both chains forked off `e6f7a8b9c0d1`:

  e6f7a8b9c0d1
    ├── a1b2c3d4e684 (BE Gap 684 provenance) → b2c3d4e5f674 (BE Gap 674 freight)
    └── a1b2c34d13e5 (ATLAS dismissals) → … → d4e5f67a16b8 (ATLAS memory/missed)

Merging `master` into `feature/atlas` brings both into one script directory, which
leaves Alembic with two heads and makes `upgrade head` ambiguous. This revision
joins them so there is exactly one head again.

It is a pure join: no schema change of its own, because the two chains touch
disjoint tables and columns. `upgrade()`/`downgrade()` are intentionally empty --
each side's own revisions still do all the work, in whichever order Alembic walks
them.

Why this is a merge revision rather than a rebase of one chain onto the other:
the development database is already stamped at `d4e5f67a16b8`. Re-pointing the
ATLAS chain's parent would put `a1b2c3d4e684`/`b2c3d4e5f674` *behind* that stamp,
so Alembic would consider the database up to date and silently skip them --
leaving `invoice`/`documents` without `model_deployment`, `prompt_version`,
`schema_version`, `llm_duration_ms` and `freight_amount`. With this merge
revision, a database at either head still walks the other chain and gets its
columns.

Revision ID: c5d6e7f8a9b0
Revises: b2c3d4e5f674, d4e5f67a16b8
Create Date: 2026-09-19
"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "c5d6e7f8a9b0"
down_revision: Union[str, Sequence[str], None] = ("b2c3d4e5f674", "d4e5f67a16b8")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op: a join point only. Both parent chains carry their own DDL."""
    pass


def downgrade() -> None:
    """No-op: splitting back into two heads needs no schema change."""
    pass
