"""Gap 474 (Feature 29 task 29.9) -- provenance and the abstention card reach the browser.

Tasks 29.5 and 29.9 put `provenance` and `abstention` on the agent result, and
`MessageResponse` dropped both, so they reached the cache, the telemetry and any
in-process caller but never the FE. 29.9's own spec line says provenance is "attached to
the response for the FE's existing citation rendering", and that half was unreachable.

The founder approved widening the model on 2026-09-07 ("Yes, widen it now").

The assertion that matters is the FIRST one: **an ordinary turn must serialise byte-for-byte
as it did before.** Every key here is Optional and defaults to None, and the endpoint dumps
with `exclude_none=True`, so a non-attachment turn emits no new keys at all. A contract
widening that changed existing payloads would be a breaking change dressed as an additive one.

Only two keys were added, and that is deliberate. Checked against `agents/query_agent.py`
rather than taken from a list: `amount_owed` and `contract_terms` are nested inside the
comparison payloads and already reach the browser through `attachment_comparison`;
`line_arithmetic` and `abstain_reason` are not top-level result keys at all. Declaring keys
the agent never emits would hand the FE a contract the BE does not honour.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from routers.chat import (
    ATTACHMENT_CONTRACT_KEYS,
    MessageResponse,
    _with_attachment_payload,
    extract_attachment_payload,
)

_PROVENANCE = [
    {"claim": "grand total is USD 450.00", "invoice_id": "abc123",
     "column": "grand_total", "function": "fetch_full_records"},
]
_ABSTENTION = {
    "status": "insufficient_evidence",
    "missing": ["a payment status for TSD-620458"],
    "on_file": ["invoice TSD-620458, USD 18,450.00, due 2026-08-01"],
    "next_step": "check the vendor statement instead",
    "message": "I can't confirm a payment status for TSD-620458 -- what I do have on file: "
               "invoice TSD-620458, USD 18,450.00, due 2026-08-01. Want me to check the "
               "vendor statement instead?",
}


class _Row:
    """The ChatMessage fields `_with_attachment_payload` reads."""

    def __init__(self, payload=None):
        self.id = uuid.uuid4()
        self.session_id = uuid.uuid4()
        self.role = "assistant"
        self.content = "The grand total is USD 450.00."
        self.generated_sql = "SELECT 1"
        self.citations = []
        self.created_at = datetime.now(timezone.utc)
        self.feedback = None
        self.status = "completed"
        self.job_id = None
        self.error_message = None
        self.attachment_payload = payload


# --- the invariant: old turns are unchanged ---------------------------------

def test_an_ordinary_turn_serialises_byte_identically():
    dumped = MessageResponse(**_with_attachment_payload(_Row())).model_dump(exclude_none=True)
    for key in ("provenance", "abstention", *ATTACHMENT_CONTRACT_KEYS):
        assert key not in dumped, (
            f"{key} leaked into a non-attachment turn; exclude_none should have dropped it"
        )
    assert set(dumped) == {
        "id", "session_id", "role", "content", "generated_sql", "citations",
        "created_at", "status",
    }


def test_the_new_keys_default_to_none():
    model = MessageResponse(**_with_attachment_payload(_Row()))
    assert model.provenance is None
    assert model.abstention is None


# --- the new keys survive the round trip ------------------------------------

def test_provenance_and_abstention_reach_the_response():
    row = _Row({"provenance": _PROVENANCE, "abstention": _ABSTENTION})
    dumped = MessageResponse(**_with_attachment_payload(row)).model_dump(exclude_none=True)
    assert dumped["provenance"] == _PROVENANCE
    assert dumped["abstention"]["status"] == "insufficient_evidence"
    # decision 3's three parts must all survive, not just the prose
    assert dumped["abstention"]["missing"] and dumped["abstention"]["on_file"]
    assert dumped["abstention"]["next_step"]


def test_both_keys_are_persisted_by_the_same_tuple_that_serialises_them():
    """One tuple drives persist and serialise; a key in only one is how the
    contract silently lost a field before."""
    assert "provenance" in ATTACHMENT_CONTRACT_KEYS
    assert "abstention" in ATTACHMENT_CONTRACT_KEYS
    agent_output = {
        "content": "x", "provenance": _PROVENANCE, "abstention": _ABSTENTION,
        "not_a_contract_key": "dropped",
    }
    payload = extract_attachment_payload(agent_output)
    assert payload == {"provenance": _PROVENANCE, "abstention": _ABSTENTION}


def test_every_contract_key_is_a_field_on_the_response_model():
    """The drift guard: a key added to the tuple but not the model would be
    persisted and then silently dropped on the way out -- Gap 474's exact shape."""
    for key in ATTACHMENT_CONTRACT_KEYS:
        assert key in MessageResponse.model_fields, f"{key} is persisted but has no field"
        assert MessageResponse.model_fields[key].default is None, f"{key} must default to None"


def test_a_turn_with_only_provenance_does_not_gain_an_abstention():
    row = _Row({"provenance": _PROVENANCE})
    dumped = MessageResponse(**_with_attachment_payload(row)).model_dump(exclude_none=True)
    assert "provenance" in dumped
    assert "abstention" not in dumped


# --- the real Postgres round trip -------------------------------------------
#
# The unit tests above pin the model and the tuple. The risk they cannot see is the
# storage hop: `attachment_payload` is a JSON column, and these two values are the
# first NESTED structures to go through it (a list of dicts, and a dict holding two
# lists). SQLite would round-trip almost anything; Postgres is the one that counts
# (CONVENTIONS hard rule 2), and it is where the previous fidelity incidents were.


def _pg_session():
    """Mirrors the repo's existing `*_on_postgres` pattern."""
    import os

    from sqlmodel import Session, create_engine

    url = os.environ.get("DATABASE_URL") or ""
    if not url:
        from config import get_settings

        url = get_settings().DATABASE_URL or ""
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        engine = create_engine(url)
        with engine.connect():
            pass
    except Exception as exc:  # pragma: no cover - environment
        pytest.skip(f"local Postgres not reachable: {exc}")
    return Session(engine)


def test_the_payload_survives_a_real_postgres_round_trip_on_postgres():
    from sqlmodel import select

    from models import ChatMessage, ChatSession

    tenant = str(uuid.uuid4())
    with _pg_session() as session:
        chat = ChatSession(tenant_id=tenant, title="gap474-roundtrip")
        session.add(chat)
        session.commit()
        session.refresh(chat)
        try:
            session.add(
                ChatMessage(
                    session_id=chat.id,
                    role="assistant",
                    content="I can't confirm a payment status for TSD-620458.",
                    attachment_payload={
                        "provenance": _PROVENANCE,
                        "abstention": _ABSTENTION,
                    },
                )
            )
            session.commit()

            row = session.exec(
                select(ChatMessage).where(ChatMessage.session_id == chat.id)
            ).first()
            dumped = MessageResponse(**_with_attachment_payload(row)).model_dump(
                exclude_none=True
            )
            # the nested shapes, not just the keys
            assert dumped["provenance"] == _PROVENANCE
            assert dumped["provenance"][0]["column"] == "grand_total"
            assert dumped["abstention"]["missing"] == _ABSTENTION["missing"]
            assert dumped["abstention"]["on_file"] == _ABSTENTION["on_file"]
            assert dumped["abstention"]["next_step"] == "check the vendor statement instead"
        finally:
            for obj in session.exec(
                select(ChatMessage).where(ChatMessage.session_id == chat.id)
            ).all():
                session.delete(obj)
            session.delete(chat)
            session.commit()
