"""Gap 304 half (2): production-turn rows on agent_eval_run

Until now `agent_eval_run` held exactly one population — golden-bank cases
written by `scripts/run_agent_eval.py`. `services/online_quality_judge.py` adds
a second: one row per real end-user chat turn, scored by the same reference-free
judge. This revision makes room for it.

Four changes, and the third is the one with a decision behind it:

  1. `run_source` — NOT NULL, server_default `'golden'`. Every existing row is a
     golden-bank row, so the default is a statement of fact rather than a
     placeholder, and no data migration is needed. This is the column every
     consumer must now filter on (`services/ops_digest_collect.py`,
     `services/online_eval_signals.py`), because the two populations are not
     comparable: a production row can never have `accuracy_score` or
     `context_score` (both need a reference answer) and its `pass` is decided on
     fewer dimensions.

  2. `message_id` — nullable UUID, indexed. The `chatmessage` row a production
     score belongs to. Deliberately **no** foreign key, matching this table's
     existing `tenant_id`: a quality measurement has to survive its subject
     being deleted, and a cascade from `chatmessage` would silently rewrite
     quality history the first time a user deletes a thread.

  3. `question`/`actual_answer` become NULLABLE, guarded by a new CHECK. The
     founder's decision was that a production row stores scores and a pointer,
     never a copy of the customer's question or the assistant's answer — a
     second copy of the same personal data in an analytics table has its own
     retention and export story that nobody signed up for. Those two columns
     were NOT NULL, so something had to give. Nullable *alone* would have
     quietly permitted a golden row with no text, which is a corrupt row, so the
     constraint carries the invariant instead:

         message_id IS NOT NULL OR (question IS NOT NULL AND actual_answer IS NOT NULL)

     i.e. a row either points at the message that holds its text, or carries the
     text itself. A separate lightweight table was the alternative and was
     rejected: every consumer (ops digest, online-eval signals, the workbook's
     quality tiles) already reads `agent_eval_run`, and the whole point of Gap
     304 is to compare live quality against the bank — two tables would mean two
     queries and a UNION at every one of those call sites to ask one question.

  4. `idx_agent_eval_run_source_time` on `(run_source, run_at)` — the shape the
     ops digest now issues twice per run (one population, one time window).

`op.batch_alter_table` is used for the nullability change and the CHECK because
SQLite cannot `ALTER COLUMN` at all (it recreates the table under batch mode)
and this revision is validated against a scratch SQLite database. On Postgres,
batch mode emits the same plain `ALTER TABLE` statements it would without it.

Downgrade **deletes production rows** before restoring NOT NULL. That is not
data loss by accident: those rows have no text to restore, so there is no
non-destructive way back, and pretending otherwise would leave a downgrade that
fails halfway. Golden rows are untouched.

Chained onto `c4a91e77b208`, confirmed as the single current head by walking
every `down_revision` in `alembic/versions/` before writing this file, not
inferred from filename ordering.

Revision ID: a7c3d5e91f04
Revises: c4a91e77b208
Create Date: 2026-08-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "a7c3d5e91f04"
down_revision: Union[str, None] = "c4a91e77b208"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CHECK_NAME = "ck_agent_eval_run_text_or_message"
_CHECK_SQL = "message_id IS NOT NULL OR (question IS NOT NULL AND actual_answer IS NOT NULL)"


def upgrade() -> None:
    op.add_column(
        "agent_eval_run",
        sa.Column("run_source", sa.String(length=20), nullable=False, server_default="golden"),
    )
    op.add_column("agent_eval_run", sa.Column("message_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_agent_eval_run_run_source"), "agent_eval_run", ["run_source"], unique=False
    )
    op.create_index(
        op.f("ix_agent_eval_run_message_id"), "agent_eval_run", ["message_id"], unique=False
    )
    op.create_index(
        "idx_agent_eval_run_source_time", "agent_eval_run", ["run_source", "run_at"], unique=False
    )
    with op.batch_alter_table("agent_eval_run") as batch_op:
        batch_op.alter_column("question", existing_type=sa.VARCHAR(), nullable=True)
        batch_op.alter_column("actual_answer", existing_type=sa.VARCHAR(), nullable=True)
        batch_op.create_check_constraint(_CHECK_NAME, _CHECK_SQL)


def downgrade() -> None:
    # See the module docstring: production rows have no text, so restoring NOT
    # NULL means removing them. Explicit and first, so the ALTERs below cannot
    # fail on a row this revision itself created.
    op.execute("DELETE FROM agent_eval_run WHERE run_source = 'production'")
    with op.batch_alter_table("agent_eval_run") as batch_op:
        batch_op.drop_constraint(_CHECK_NAME, type_="check")
        batch_op.alter_column("actual_answer", existing_type=sa.VARCHAR(), nullable=False)
        batch_op.alter_column("question", existing_type=sa.VARCHAR(), nullable=False)
    op.drop_index("idx_agent_eval_run_source_time", table_name="agent_eval_run")
    op.drop_index(op.f("ix_agent_eval_run_message_id"), table_name="agent_eval_run")
    op.drop_index(op.f("ix_agent_eval_run_run_source"), table_name="agent_eval_run")
    op.drop_column("agent_eval_run", "message_id")
    op.drop_column("agent_eval_run", "run_source")
