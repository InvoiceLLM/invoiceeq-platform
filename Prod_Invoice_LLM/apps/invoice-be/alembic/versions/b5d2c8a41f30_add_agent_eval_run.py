"""Feature 23 Phase 3: agent_eval_run — golden-set quality results over time

One row per graded golden-set question, per agent/path, per run. Phase 1's
`llm_agent_call` custom events answer "what did that call cost"; this table
answers "was the answer any good", with a timestamp on every row so the answer
to "is it getting worse" is a query rather than a memory.

Chained onto `f3e8b2a1d6c9`, confirmed as the real single head by running
`alembic heads` against this repo before writing this file (not assumed from
the filename ordering — this history has had four merge points already, most
recently `f3e8b2a1d6c9` itself after two unreconciled branches took the backend
down on 2026-08-21).

The `pass` column is spelled exactly that: it is not a reserved word in either
Postgres or SQLite, and the model maps it to the attribute `passed` because
`pass` is a Python keyword.

Revision ID: b5d2c8a41f30
Revises: f3e8b2a1d6c9
Create Date: 2026-08-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = "b5d2c8a41f30"
down_revision: Union[str, None] = "f3e8b2a1d6c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_eval_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_name", sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
        sa.Column("run_at", sa.DateTime(), nullable=False),
        # AutoString() (unbounded), matching what every other free-text column in
        # this schema was created as (`chatmessage.content`, `generated_sql`) —
        # a `sa.Text()` here would show up as a spurious diff on the next
        # `alembic revision --autogenerate`.
        sa.Column("question", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("expected_answer", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("actual_answer", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("pass", sa.Boolean(), nullable=False, server_default=sa.false()),
        # Nullable by design: an unreachable judge, or a case with no reference
        # answer, leaves the score absent rather than recording a 0.0 that would
        # read as "scored, and terrible" in every trend chart afterwards.
        sa.Column("faithfulness_score", sa.Float(), nullable=True),
        sa.Column("relevance_score", sa.Float(), nullable=True),
        sa.Column("accuracy_score", sa.Float(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("llm_call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("notes", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_agent_eval_run_agent_time", "agent_eval_run", ["agent_name", "run_at"], unique=False)
    op.create_index("idx_agent_eval_run_tenant_time", "agent_eval_run", ["tenant_id", "run_at"], unique=False)
    op.create_index(op.f("ix_agent_eval_run_agent_name"), "agent_eval_run", ["agent_name"], unique=False)
    op.create_index(op.f("ix_agent_eval_run_run_at"), "agent_eval_run", ["run_at"], unique=False)
    op.create_index(op.f("ix_agent_eval_run_tenant_id"), "agent_eval_run", ["tenant_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_eval_run_tenant_id"), table_name="agent_eval_run")
    op.drop_index(op.f("ix_agent_eval_run_run_at"), table_name="agent_eval_run")
    op.drop_index(op.f("ix_agent_eval_run_agent_name"), table_name="agent_eval_run")
    op.drop_index("idx_agent_eval_run_tenant_time", table_name="agent_eval_run")
    op.drop_index("idx_agent_eval_run_agent_time", table_name="agent_eval_run")
    op.drop_table("agent_eval_run")
