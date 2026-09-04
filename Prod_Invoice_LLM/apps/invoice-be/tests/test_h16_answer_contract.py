"""V-27 — Feature 26 task H16 / amendment B12 (BE Gap 386).

The defect these cover is invisible to every other test in the suite, and that is
the whole point of the file.

`agents/query_agent.py` has always returned `attachment_confirmation` (L3281),
`attachment_comparison` + `suggested_actions` (L3351-2), `evidence` +
`needs_confirmation` (L3460-1, L3542-50) and `attachment_clarification` (L3220).
Every existing test on that path asserts on the AGENT, so all of them were green
throughout. But `routers/chat.py::MessageResponse` declared none of those keys, so
FastAPI stripped each one at serialisation, and `ChatMessage` had no column to hold
them, so a session reload restored nothing. Feature 26's entire FE surface — the
confirmation card, the diff table, the evidence blocks, the clarification buttons
(FE Gaps 376/380/383) — was rendering off a contract that could not reach a browser.

So every assertion here is on the **HTTP response body** or on the **reloaded
session**, never on a mock's return value. A test that mocks the agent and then
checks what the agent returned cannot see this class of bug at all — which is
precisely how it survived three FE tasks and a full status audit.

Separate file rather than more tests in `test_chat_attachments.py`: that file's
remit is the attachment feature's behaviour, and this one's is the transport
contract between the agent, the ORM row and the wire. They fail for different
reasons and should be readable apart.
"""
import os
from datetime import date
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from dependencies import MOCK_TENANT_ID, get_db_session  # noqa: E402
from main import app  # noqa: E402
from models import ChatMessage, ChatSession  # noqa: E402

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool
)

# Every key H16 puts on the wire. Declared once here and imported from the router
# in the test below, so a key added to one and not the other fails a test rather
# than silently dropping a field again.
CONTRACT_KEYS = (
    "attachment_confirmation",
    "attachment_comparison",
    "attachment_clarification",
    "suggested_actions",
    "evidence",
    "needs_confirmation",
    "line_items",
    "unmatched",
    "reconciliation",
    # Gap 387 (Phase 2.3): two attached documents compared to each other.
    "attachment_pair_comparison",
)


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="sync_chat", autouse=True)
def sync_chat_fixture(monkeypatch):
    """Pin the SYNCHRONOUS chat path for this file.

    The developer `.env` sets `ENABLE_ASYNC_CHAT_QUEUE=true`, so with Redis
    running the endpoint enqueues and returns `202 Accepted` with a `job_id`,
    and the assistant row is written later by the worker in a different process
    and a different session -- which this file's `db_session` cannot see. That
    is BE Gap 390, and it is exactly the environment coupling that gap describes:
    three `test_rag.py` tests pass only while Redis is down.

    What H16 asserts is that the answer contract survives persistence and
    serialisation on the sync path, so the sync path is pinned explicitly rather
    than left to depend on whether a container happens to be running. The async
    path carries the same `attachment_payload=` argument
    (`queue_worker/handlers.py`), and H7 is what makes attachment turns reachable
    through it; V-16..V-18 cover that path and are still open.
    """
    import config

    monkeypatch.setattr(config.settings, "ENABLE_ASYNC_CHAT_QUEUE", False)
    yield


@pytest.fixture(name="client")
def client_fixture(db_session):
    from fastapi.testclient import TestClient

    def _override_db():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def _session_row(db):
    # str() first: MOCK_TENANT_ID is already a UUID in this build, and UUID(UUID)
    # raises. Going through str() works whichever type dependencies.py exports.
    row = ChatSession(id=uuid4(), tenant_id=UUID(str(MOCK_TENANT_ID)), title="H16")
    db.add(row)
    db.commit()
    return row


def _attachment(db, session_id):
    """A real ChatAttachment row.

    `_run_attached_document_turn()` loads the row before either branch and
    answers "I can't find that attachment on this conversation" for an unknown
    id (`agents/query_agent.py:3158`) -- so a fabricated UUID never reaches the
    code under test.
    """
    from models import ChatAttachment

    row = ChatAttachment(
        id=uuid4(),
        tenant_id=UUID(str(MOCK_TENANT_ID)),
        session_id=session_id,
        filename="po.pdf",
        blob_path="tenants/x/chat-attachments/po.pdf",
        doc_type="PURCHASE_ORDER",
        file_size_bytes=1024,
        extraction_status="EXTRACTED",
    )
    db.add(row)
    db.commit()
    return row


def _post(client, session_id, content="was I over-billed?", attachment_id=None):
    body = {"content": content}
    if attachment_id is not None:
        body["attachment_id"] = str(attachment_id)
    return client.post(f"/api/v1/chat/sessions/{session_id}/message", json=body)


def _assistant_rows(client, session_id):
    res = client.get(f"/api/v1/chat/sessions/{session_id}")
    assert res.status_code == 200, res.text
    return [m for m in res.json() if m["role"] == "assistant"]


def test_v27_a_confirmation_turn_reaches_the_client_and_survives_a_reload(
    db_session, client
):
    """The whole of Gap 386 end to end: response body, then reload.

    Two assertions, and the second is the one the column exists for. A transient
    response field would satisfy the first and still leave the reload path
    (spec P2.6.6) with nothing to restore — which is exactly why amendment B12
    chose persistence over a transient field.
    """
    import routers.chat as rc

    session = _session_row(db_session)
    payload = {
        "kind": "attachment_confirmation",
        "attachment_id": str(uuid4()),
        "tier": 1,
        "truncated": False,
        "requires_manual_entry": False,
        "candidates": [
            {
                "invoice_id": str(uuid4()),
                "invoice_number": "INV-1",
                "party_name": "Acme Supplies Ltd",
                "grand_total": "1380.00",
                "currency": "INR",
                "status": "AUDIT_REQUIRED",
                "flow_direction": "INBOUND",
            }
        ],
    }

    with patch.object(rc, "run_query_agent") as run:
        run.return_value = {
            "content": "Which of these invoices should I compare it against?",
            "generated_sql": "",
            "citations": [],
            "result_invoice_ids": [],
            "attachment_confirmation": payload,
        }
        res = _post(client, session.id, attachment_id=uuid4())

    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("attachment_confirmation") == payload, (
        "the confirmation payload did not survive serialisation; "
        f"keys present: {sorted(body)}"
    )

    assistant = _assistant_rows(client, session.id)
    assert assistant, "no assistant message was persisted"
    assert assistant[-1]["attachment_confirmation"] == payload, (
        "the confirmation payload was not restored on reload — "
        "ChatMessage.attachment_payload did not round-trip"
    )


def test_v27_a_comparison_turn_carries_its_diff_and_actions_both_ways(db_session, client):
    """`attachment_comparison` + `suggested_actions` — the diff table and D6 links."""
    import routers.chat as rc

    session = _session_row(db_session)
    diff = {
        "reference": {"doc_number": "PO-2024/0043"},
        "compared_count": 1,
        "blocked_count": 0,
        "comparisons": [],
    }
    actions = [
        {"label": "Open in Trainer", "href": "/trainer", "precondition": "always legal"}
    ]

    with patch.object(rc, "run_query_agent") as run:
        run.return_value = {
            "content": "The invoice is 200 higher than the PO.",
            "generated_sql": "",
            "citations": [],
            "result_invoice_ids": [],
            "attachment_comparison": diff,
            "suggested_actions": actions,
        }
        res = _post(client, session.id, attachment_id=uuid4())

    body = res.json()
    assert body.get("attachment_comparison") == diff
    assert body.get("suggested_actions") == actions

    assistant = _assistant_rows(client, session.id)[-1]
    assert assistant["attachment_comparison"] == diff
    assert assistant["suggested_actions"] == actions


def test_v27_content_and_clarifying_turns_carry_their_own_keys(db_session, client):
    """`evidence` + `needs_confirmation`, then the clarifying turn's own key."""
    import routers.chat as rc

    session = _session_row(db_session)
    evidence = [{"page": 2, "text": "Payment terms: Net 45 days", "distance": 0.31}]

    with patch.object(rc, "run_query_agent") as run:
        run.return_value = {
            "content": "The payment terms are Net 45 days.",
            "generated_sql": "",
            "citations": [],
            "result_invoice_ids": [],
            "evidence": evidence,
            "needs_confirmation": False,
        }
        res = _post(client, session.id, "what are the payment terms?", uuid4())

    body = res.json()
    assert body.get("evidence") == evidence
    # False must survive as False, not be dropped as falsy — the content branch
    # emits `needs_confirmation=False` deliberately (it is the assertion that no
    # confirmation is outstanding), so losing it is not the same as absence.
    assert body.get("needs_confirmation") is False

    clarification = {
        "message": "Would you like me to read the document, or compare it to your invoices?",
        "options": [
            {"intent": "read", "label": "Read the document"},
            {"intent": "compare", "label": "Compare to my invoices"},
        ],
    }
    with patch.object(rc, "run_query_agent") as run:
        run.return_value = {
            "content": clarification["message"],
            "generated_sql": "",
            "citations": [],
            "result_invoice_ids": [],
            "attachment_clarification": clarification,
        }
        res2 = _post(client, session.id, "tell me about this", uuid4())

    assert res2.json().get("attachment_clarification") == clarification


def test_v27_an_ordinary_chat_turn_is_byte_identical_to_before_h16(db_session, client):
    """The regression guard.

    Every new field is Optional and defaults to None, so an ordinary chat turn
    must not gain a single key. Nine nulls on every non-attachment response would
    be a wire-shape change for every existing FE consumer, which H16 explicitly
    is not.
    """
    import routers.chat as rc

    session = _session_row(db_session)
    with patch.object(rc, "run_query_agent") as run:
        run.return_value = {
            "content": "You spent 12,000 last month.",
            "generated_sql": "SELECT 1",
            "citations": [],
            "result_invoice_ids": [],
        }
        res = _post(client, session.id, "how much did we spend?")

    body = res.json()
    for key in CONTRACT_KEYS:
        assert body.get(key) is None, f"an ordinary turn leaked {key}"

    row = db_session.exec(
        select(ChatMessage).where(
            ChatMessage.session_id == session.id, ChatMessage.role == "assistant"
        )
    ).first()
    assert row is not None
    # None, not {}. The column means "not an attachment turn"; an empty dict would
    # read as "an attachment turn that answered nothing", which P2.8's contract
    # rule defines as a bug rather than a state.
    assert row.attachment_payload is None


def test_v27_extractor_keeps_absent_keys_absent_rather_than_null():
    """P2.8's contract rule turns on ABSENCE.

    `attachment_comparison` missing on the content branch is the assertion that
    no comparison ran. A payload that stored every key as null would destroy that
    distinction and make the contract unfalsifiable.
    """
    from routers.chat import extract_attachment_payload

    assert extract_attachment_payload({"content": "hi"}) is None

    out = extract_attachment_payload(
        {"content": "hi", "evidence": [], "needs_confirmation": False}
    )
    assert out == {"evidence": [], "needs_confirmation": False}
    assert "attachment_comparison" not in out


def test_v27_the_persist_side_and_the_wire_side_cannot_drift():
    """One tuple drives both. A key added to the response model but not to
    `ATTACHMENT_CONTRACT_KEYS` would serialise as null forever and never persist —
    the same silent-drop failure as Gap 386, one field at a time.
    """
    from routers.chat import ATTACHMENT_CONTRACT_KEYS, MessageResponse

    assert set(ATTACHMENT_CONTRACT_KEYS) == set(CONTRACT_KEYS)
    for key in ATTACHMENT_CONTRACT_KEYS:
        assert key in MessageResponse.model_fields, (
            f"{key} is persisted but is not a MessageResponse field, so it can "
            f"never reach a client"
        )
