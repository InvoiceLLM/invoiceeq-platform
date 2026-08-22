"""Feature 23: component-level scores on agent_eval_run

Three nullable score columns — `context_score`, `orchestration_score`,
`persona_score` — implementing the feature doc's "component-level scoring, not
one blended number" decision. The existing faithfulness/relevance/accuracy
columns say *that* an answer was bad; these say *which stage* of the pipeline to
look at:

  context_score       the context builder (identify/get_full_record/aggregate/
                      search) — did retrieval fetch the right rows at all
  orchestration_score the system prompt / tool orchestration — did the answer
                      stay inside what was actually fetched
  persona_score       the skilled persona — was the domain (tax/category/status)
                      reasoning right

Additive only. Every column is nullable with no server default, so this is a
metadata-only `ALTER TABLE ... ADD COLUMN` on Postgres and every existing row
keeps a NULL — which the model and the scorer both read as "not scored", never
as 0.0. Nothing in any request path reads these columns.

Chained onto `b5d2c8a41f30`, confirmed as the real single head by running
`alembic heads` in this repo immediately before writing this file (output:
`b5d2c8a41f30 (head)`), not inferred from filename ordering — this history has
four merge points in it already.

Revision ID: c4a91e77b208
Revises: b5d2c8a41f30
Create Date: 2026-08-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c4a91e77b208"
down_revision: Union[str, None] = "b5d2c8a41f30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_COLUMNS = ("context_score", "orchestration_score", "persona_score")


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column("agent_eval_run", sa.Column(name, sa.Float(), nullable=True))


def downgrade() -> None:
    for name in reversed(_COLUMNS):
        op.drop_column("agent_eval_run", name)
