"""Feature 30 tasks 30.8 and 30.13 — `certified_sql_example` and `chat_correction`.

One file for both because they are two halves of one loop and land together
(§4's table list): a thumbs-down writes a `chat_correction`, an approved
correction is PROMOTED into a `certified_sql_example`, and the certified example
is what the next answer is built from. Splitting them would leave a flywheel with
one wheel.

Add-only. Nothing writes to either table while `ENABLE_ATTACHMENT_INSIGHTS` and
`ENABLE_CERTIFIED_EXAMPLES` are False, so their existence is inert.

`certified_sql_example.tenant_id` is NULLABLE on purpose — Feature 29's decision
5 ("global examples"): an example certified against the shared schema is useful
to every tenant, and NULL means exactly that. A tenant-specific example (one that
names a vendor, a rule, a column they added) carries their id.

down_revision `a1b2c3f30002` confirmed as the single head by `alembic heads`
immediately before writing this file.

Revision ID: a1b2c3f30003
Revises: a1b2c3f30002
Create Date: 2026-09-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

revision: str = "a1b2c3f30003"
down_revision: Union[str, None] = "a1b2c3f30002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_VARIANT = sa.JSON().with_variant(JSONB, "postgresql")
UUID_VARIANT = PG_UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "certified_sql_example",
        sa.Column("id", UUID_VARIANT, primary_key=True),
        # Nullable = global. See the module docstring.
        sa.Column("tenant_id", UUID_VARIANT, nullable=True),
        sa.Column("question", sa.String(length=2000), nullable=False),
        sa.Column("sql", sa.String(), nullable=False),
        # Which document type this example is a good question FOR, so the
        # suggested-questions card can offer three that fit the bubble the user
        # is looking at rather than three generic ones.
        sa.Column("doc_type", sa.String(length=32), nullable=True),
        sa.Column("metric", sa.String(length=64), nullable=True),
        # The gate: only a certified row is ever retrievable. A row written by
        # the flywheel starts uncertified and stays invisible until a human says
        # otherwise.
        sa.Column("certified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("certified_by", sa.String(length=255), nullable=True),
        sa.Column("certified_at", sa.DateTime(), nullable=True),
        sa.Column("source_correction_id", UUID_VARIANT, nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_certified_sql_example_tenant_id", "certified_sql_example", ["tenant_id"])
    op.create_index("ix_certified_sql_example_certified", "certified_sql_example", ["certified"])
    op.create_index("ix_certified_sql_example_doc_type", "certified_sql_example", ["doc_type"])

    op.create_table(
        "chat_correction",
        sa.Column("id", UUID_VARIANT, primary_key=True),
        sa.Column("tenant_id", UUID_VARIANT, nullable=False),
        sa.Column("message_id", UUID_VARIANT, nullable=True),
        sa.Column("insight_id", UUID_VARIANT, nullable=True),
        sa.Column("card", sa.String(length=64), nullable=True),
        sa.Column("finding_key", sa.String(length=255), nullable=True),
        sa.Column("vote", sa.String(length=10), nullable=False, server_default="down"),
        # What the user says is wrong, and what they say it should be. Both free
        # text and both optional: a thumbs-down with no explanation is still
        # signal, and demanding prose would suppress the cheapest feedback there
        # is.
        sa.Column("reason", sa.String(length=64), nullable=True),
        sa.Column("corrected_text", sa.String(length=4000), nullable=True),
        sa.Column("corrected_sql", sa.String(), nullable=True),
        sa.Column("evidence", JSON_VARIANT, nullable=True),
        # PENDING | PROMOTED | REJECTED -- a correction is a proposal until a
        # human acts on it, exactly like an unconfirmed vendor alias (30.0f).
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("promoted_example_id", UUID_VARIANT, nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_chat_correction_tenant_id", "chat_correction", ["tenant_id"])
    op.create_index("ix_chat_correction_message_id", "chat_correction", ["message_id"])
    op.create_index("ix_chat_correction_insight_id", "chat_correction", ["insight_id"])
    op.create_index("ix_chat_correction_status", "chat_correction", ["status"])


def downgrade() -> None:
    op.drop_table("chat_correction")
    op.drop_table("certified_sql_example")
