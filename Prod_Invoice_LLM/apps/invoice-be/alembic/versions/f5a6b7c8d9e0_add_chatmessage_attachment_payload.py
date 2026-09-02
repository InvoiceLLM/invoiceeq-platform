"""add chatmessage.attachment_payload (Feature 26 task H16 / amendment B12, Gap 386)

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-09-02

One nullable JSON column carrying the attached-document answer contract for the
turn that produced it.

WHY A COLUMN AND NOT A RESPONSE FIELD. `agents/query_agent.py` already computes
`attachment_confirmation` (L3281), `attachment_comparison` + `suggested_actions`
(L3351-2), `evidence` + `needs_confirmation` (L3460-1, L3542-50) and
`attachment_clarification` (L3220). Every one of them was discarded twice:
`routers/chat.py::MessageResponse` declared none of them so FastAPI stripped them
at serialisation, and `ChatMessage` had no column so a session reload restored
nothing. Feature 26's whole FE surface -- the confirmation card, the diff table,
the evidence blocks, the clarification buttons -- renders off keys that could not
reach a browser. That is Gap 386.

Transient response fields were rejected for three reasons (spec amendment B12):
the reload path in `hooks/useChatSession.ts` re-reads the session and must restore
the confirmation card; the async worker (`queue_worker/handlers.py`) computes the
answer in a different process from the request, so there is no response object to
attach a transient field to; and the D4 confirmation gate is a two-turn
interaction in which turn 2 must know what turn 1 offered.

NULLABLE WITH NO SERVER DEFAULT, deliberately. Every existing row is valid
unchanged and no backfill runs -- NULL means "not an attachment turn", which is
true of every row written before this revision and of the overwhelming majority
written after. It does not mean "an attachment turn that produced nothing":
P2.8's contract rule makes an answer carrying neither evidence nor a comparison a
bug, so an attachment turn always writes a dict. A reader must not infer failure
from NULL.

JSON_VARIANT -- `sa.JSON().with_variant(JSONB, "postgresql")` -- is the type
`citations` and `result_invoice_ids` already use on this table, so Postgres gets
JSONB and SQLite gets JSON, and no consumer needs a second code path.

down_revision `e4f5a6b7c8d9` confirmed as the single head by resolving
`ScriptDirectory.get_heads()` against the live tree at write time rather than
trusting the spec (`alembic.exe` is blocked by this machine's Application Control
policy; the Python API is the substitute). Gap 60's multi-head incident is why
this is re-walked every time rather than copied from a document.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_VARIANT = sa.JSON().with_variant(JSONB, "postgresql")


def upgrade() -> None:
    op.add_column(
        "chatmessage",
        sa.Column("attachment_payload", JSON_VARIANT, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("chatmessage", "attachment_payload")
