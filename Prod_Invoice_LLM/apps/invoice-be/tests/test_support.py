"""
Tests for Feature 19 / Feature Website 5: Support Ticket Router (routers/support.py).

Coverage
--------
POST /api/v1/support/contact — public, unauthenticated
  1.  Valid payload creates a SupportTicket with source=WEBSITE_CONTACT
  2.  ticket_number is INQ-YYYY-XXXX format
  3.  Returns HTTP 201 with success=True and a ticket_number
  4.  Missing name   → HTTP 422
  5.  Missing email  → HTTP 422
  6.  Missing message → HTTP 422
  7.  Invalid email  → HTTP 422
  8.  Message > 5000 chars → HTTP 422
  9.  Category defaults to GENERAL for unknown category
  10. Urgency defaults to NORMAL for unknown urgency

POST /api/v1/support/ticket — authenticated (mocked via ALLOW_MOCK_AUTH)
  11. Valid payload creates a SupportTicket with source=DIRECT_TICKET
  12. ticket_number is TICK-YYYY-XXXX format
  13. Returns HTTP 201 with success=True
  14. chat_transcript is persisted alongside the ticket
  15. source=HELP_CHATBOT is accepted and stored correctly

GET /api/v1/support/tickets — authenticated
  16. Returns empty list when no tickets exist for the tenant
  17. Returns ticket summary list for the tenant's own tickets

Email dispatch (mocked in all tests)
  18. dispatch_support_email is called once for each successful ticket creation
  19. A SendGrid failure (RuntimeError) does NOT prevent the 201 response
"""
from __future__ import annotations

import os

# Gap 403: evaluate_support_query() now has a vector-search fallback
# (agents/support_agent.py) that goes through chroma_client.get_embeddings().
# Must be set before `config`/`main` are imported anywhere (see conftest.py's
# comment on ALLOW_MOCK_AUTH for why) so this file never pays the real
# BAAI/bge-m3 model's load cost — every existing test in this file that falls
# through to a miss now also exercises that fallback, and the mock path's
# high-dimensional random vectors are what keeps that safe (see
# TestSupportAgentVectorFallback below for why that isn't just assumed).
os.environ.setdefault("MOCK_EMBEDDINGS", "true")

import re
import time
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from dependencies import MOCK_TENANT_ID, get_db_session
from main import app
from models import SupportTicket

# ---------------------------------------------------------------------------
# In-memory SQLite test database
# ---------------------------------------------------------------------------

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

client = TestClient(app)


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def override_db_session(db_session):
    def _override():
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Silence real email dispatch in all tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_email_dispatch():
    with patch(
        "routers.support.dispatch_support_ticket_email",
        return_value={"staff_alert": {"status": "sent"}, "user_receipt": {"status": "sent"}},
    ) as m:
        yield m


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_CONTACT_PAYLOAD = {
    "name": "Jane Smith",
    "email": "jane@enterprise.com",
    "category": "SALES",
    "company": "Acme Corp",
    "urgency": "NORMAL",
    "message": "We are interested in an enterprise demo. Please reach out.",
}

VALID_TICKET_PAYLOAD = {
    "subject": "Invoice extraction failing on PDF type X",
    "description": "All invoices from vendor Y fail with a 500 error.",
    "category": "TECHNICAL_SUPPORT",
    "priority": "URGENT",
    "source": "DIRECT_TICKET",
    "company": "Acme Corp",
    "chat_transcript": [],
}

INQ_PATTERN = re.compile(r"^INQ-\d{4}-[0-9A-F]{8}$")
TICK_PATTERN = re.compile(r"^TICK-\d{4}-[0-9A-F]{8}$")


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset support router rate limiter before each test."""
    from routers.support import _rate_limiter
    _rate_limiter.reset()
    yield
    _rate_limiter.reset()


# ---------------------------------------------------------------------------
# POST /api/v1/support/contact
# ---------------------------------------------------------------------------

class TestContactEndpoint:
    """Tests 1–10"""

    def test_valid_payload_creates_ticket(self, db_session: Session):
        """Test 1, 3: valid payload → 201, success=True."""
        res = client.post("/api/v1/support/contact", json=VALID_CONTACT_PAYLOAD)
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["success"] is True
        assert "ticket_number" in body

    def test_ticket_number_format(self, db_session: Session):
        """Test 2: ticket_number follows INQ-YYYY-XXXX pattern."""
        res = client.post("/api/v1/support/contact", json=VALID_CONTACT_PAYLOAD)
        assert res.status_code == 201
        number = res.json()["ticket_number"]
        assert INQ_PATTERN.match(number), f"Unexpected format: {number}"

    def test_ticket_persisted_in_db(self, db_session: Session):
        """Test 1 (DB side): ticket is written to the SupportTicket table."""
        res = client.post("/api/v1/support/contact", json=VALID_CONTACT_PAYLOAD)
        assert res.status_code == 201
        number = res.json()["ticket_number"]
        ticket = db_session.exec(
            __import__("sqlmodel").select(SupportTicket).where(
                SupportTicket.ticket_number == number
            )
        ).first()
        assert ticket is not None
        assert ticket.source == "WEBSITE_CONTACT"
        assert ticket.user_email == "jane@enterprise.com"
        assert ticket.category == "SALES"

    @pytest.mark.parametrize(
        "missing_field",
        ["name", "email", "message"],
    )
    def test_missing_required_field(self, db_session: Session, missing_field: str):
        """Tests 4–6: each required field returns 422 when absent."""
        payload = {**VALID_CONTACT_PAYLOAD}
        del payload[missing_field]
        res = client.post("/api/v1/support/contact", json=payload)
        assert res.status_code == 422, f"Expected 422 for missing {missing_field}"

    def test_invalid_email(self, db_session: Session):
        """Test 7: malformed email → 422."""
        payload = {**VALID_CONTACT_PAYLOAD, "email": "not-an-email"}
        res = client.post("/api/v1/support/contact", json=payload)
        assert res.status_code == 422

    def test_message_too_long(self, db_session: Session):
        """Test 8: message > 5000 chars → 422."""
        payload = {**VALID_CONTACT_PAYLOAD, "message": "x" * 5001}
        res = client.post("/api/v1/support/contact", json=payload)
        assert res.status_code == 422

    def test_unknown_category_defaults_to_general(self, db_session: Session):
        """Test 9: unrecognised category is coerced to GENERAL, not rejected."""
        payload = {**VALID_CONTACT_PAYLOAD, "category": "INVALID_CAT"}
        res = client.post("/api/v1/support/contact", json=payload)
        assert res.status_code == 201

    def test_unknown_urgency_defaults_to_normal(self, db_session: Session):
        """Test 10: unrecognised urgency is coerced to NORMAL, not rejected."""
        payload = {**VALID_CONTACT_PAYLOAD, "urgency": "SUPER_DUPER_URGENT"}
        res = client.post("/api/v1/support/contact", json=payload)
        assert res.status_code == 201


# ---------------------------------------------------------------------------
# POST /api/v1/support/ticket
# ---------------------------------------------------------------------------

class TestAppTicketEndpoint:
    """Tests 11–15"""

    def test_valid_direct_ticket(self, db_session: Session):
        """Test 11, 13: valid payload → 201, success=True."""
        res = client.post("/api/v1/support/ticket", json=VALID_TICKET_PAYLOAD)
        assert res.status_code == 201, res.text
        assert res.json()["success"] is True

    def test_tick_ticket_number_format(self, db_session: Session):
        """Test 12: ticket_number follows TICK-YYYY-XXXX pattern."""
        res = client.post("/api/v1/support/ticket", json=VALID_TICKET_PAYLOAD)
        assert res.status_code == 201
        number = res.json()["ticket_number"]
        assert TICK_PATTERN.match(number), f"Unexpected format: {number}"

    def test_chat_transcript_persisted(self, db_session: Session):
        """Test 14: chat_transcript list is stored in the DB column."""
        transcript = [
            {"role": "user",      "content": "How do I export invoices?"},
            {"role": "assistant", "content": "Use the Export CSV button on the dashboard."},
        ]
        payload = {**VALID_TICKET_PAYLOAD, "source": "HELP_CHATBOT", "chat_transcript": transcript}
        res = client.post("/api/v1/support/ticket", json=payload)
        assert res.status_code == 201
        number = res.json()["ticket_number"]
        ticket = db_session.exec(
            __import__("sqlmodel").select(SupportTicket).where(
                SupportTicket.ticket_number == number
            )
        ).first()
        assert ticket is not None
        assert ticket.chat_transcript == transcript

    def test_help_chatbot_source_stored(self, db_session: Session):
        """Test 15: source=HELP_CHATBOT is accepted and stored."""
        payload = {**VALID_TICKET_PAYLOAD, "source": "HELP_CHATBOT"}
        res = client.post("/api/v1/support/ticket", json=payload)
        assert res.status_code == 201
        number = res.json()["ticket_number"]
        ticket = db_session.exec(
            __import__("sqlmodel").select(SupportTicket).where(
                SupportTicket.ticket_number == number
            )
        ).first()
        assert ticket is not None
        assert ticket.source == "HELP_CHATBOT"


# ---------------------------------------------------------------------------
# GET /api/v1/support/tickets
# ---------------------------------------------------------------------------

class TestListTicketsEndpoint:
    """Tests 16–17"""

    def test_empty_list_when_no_tickets(self, db_session: Session):
        """Test 16: no tickets for this tenant → tickets: []."""
        res = client.get("/api/v1/support/tickets")
        assert res.status_code == 200
        assert res.json()["tickets"] == []

    def test_returns_own_tickets(self, db_session: Session):
        """Test 17: after creating tickets they appear in the list."""
        # Create two tickets for this tenant via the endpoint
        client.post("/api/v1/support/ticket", json=VALID_TICKET_PAYLOAD)
        client.post(
            "/api/v1/support/ticket",
            json={**VALID_TICKET_PAYLOAD, "subject": "Second ticket"},
        )
        res = client.get("/api/v1/support/tickets")
        assert res.status_code == 200
        tickets = res.json()["tickets"]
        assert len(tickets) >= 2  # may be more if tests run in sequence
        # All returned tickets have required fields
        for t in tickets:
            assert "ticket_number" in t
            assert "subject" in t
            assert "status" in t


# ---------------------------------------------------------------------------
# Email dispatch behaviour
# ---------------------------------------------------------------------------

class TestEmailDispatch:
    """Tests 18–19"""

    def test_email_dispatched_on_contact(self, db_session: Session, mock_email_dispatch):
        """Test 18: dispatch_support_ticket_email is called once per successful contact."""
        client.post("/api/v1/support/contact", json=VALID_CONTACT_PAYLOAD)
        mock_email_dispatch.assert_called_once()

    def test_email_failure_does_not_break_response(self, db_session: Session):
        """Test 19: a RuntimeError in email dispatch still yields 201.
        The router wraps dispatch_support_ticket_email in try/except so an
        email outage never prevents the ticket record from being confirmed."""
        with patch(
            "routers.support.dispatch_support_ticket_email",
            side_effect=RuntimeError("SendGrid is down"),
        ):
            res = client.post("/api/v1/support/contact", json=VALID_CONTACT_PAYLOAD)
            # Ticket is persisted before email is attempted; email failure is
            # caught and logged, so the 201 is still returned.
            assert res.status_code == 201
            body = res.json()
            assert body["success"] is True
            assert body["email_dispatched"] is False


# ---------------------------------------------------------------------------
# POST /api/v1/support/chat  — authenticated, AI support assistant
# ---------------------------------------------------------------------------

class TestSupportChatEndpoint:
    """Tests 20–24"""

    def test_documentation_query_returns_answer(self, db_session: Session):
        """Test 20: Knowledge query about trainer returns guidance with no escalation."""
        res = client.post("/api/v1/support/chat", json={"message": "How do I train a new vendor format?"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert "Trainer" in body["answer"] or "trainer" in body["answer"].lower()
        assert body["suggest_escalation"] is False
        assert body["escalation_context"] is None

    def test_error_keyword_triggers_escalation(self, db_session: Session):
        """Test 21: Query containing 504 gateway timeout returns smart escalation card."""
        res = client.post("/api/v1/support/chat", json={"message": "We experienced a 504 gateway timeout during batch sync"})
        assert res.status_code == 200
        body = res.json()
        assert body["suggest_escalation"] is True
        assert body["escalation_context"] is not None
        assert body["escalation_context"]["category"] == "TECHNICAL_SUPPORT"
        assert body["escalation_context"]["priority"] == "URGENT"

    def test_human_help_request_triggers_escalation(self, db_session: Session):
        """Test 22: Query requesting to speak to human/agent returns escalation trigger."""
        res = client.post("/api/v1/support/chat", json={"message": "I need to raise a support ticket and talk to an agent"})
        assert res.status_code == 200
        body = res.json()
        assert body["suggest_escalation"] is True
        assert body["escalation_context"] is not None

    def test_empty_message_returns_422(self, db_session: Session):
        """Test 23: Empty message returns 422 validation error."""
        res = client.post("/api/v1/support/chat", json={"message": "   "})
        assert res.status_code == 422

    def test_word_boundary_matching_prevents_substring_collisions(self, db_session: Session):
        """BE Gap 254: Verification that word-boundary matching prevents false positive topic matches."""
        # 1. "confidence" contains "id" but should NOT match account_auth. It should match auditor (due to confidence keyword).
        res = client.post("/api/v1/support/chat", json={"message": "What does the confidence score mean?"})
        assert res.status_code == 200
        body = res.json()
        assert "Auditor" in body["answer"] or "auditor" in body["answer"].lower()
        assert "Password" not in body["answer"]

        # 2. "processing" contains "pro" but should NOT match billing plan info.
        res = client.post("/api/v1/support/chat", json={"message": "my invoice is stuck in processing"})
        assert res.status_code == 200
        body = res.json()
        assert "Statuses" in body["answer"] or "statuses" in body["answer"].lower()
        assert "PayU" not in body["answer"]

    def test_new_knowledge_topics(self, db_session: Session):
        """BE Gap 254: Verification that newly added topics return correct guidance."""
        # Ingestion / Upload Limits
        res = client.post("/api/v1/support/chat", json={"message": "What is the maximum upload file size limit?"})
        assert res.status_code == 200
        assert "25 MB" in res.json()["answer"]

        # Invoice Statuses
        res = client.post("/api/v1/support/chat", json={"message": "Tell me about the audit_required status"})
        assert res.status_code == 200
        assert "lifecycle" in res.json()["answer"].lower()

        # Dashboard / Analytics
        res = client.post("/api/v1/support/chat", json={"message": "Show me the dashboard spending trends"})
        assert res.status_code == 200
        assert "real-time financial visibility" in res.json()["answer"].lower()

        # User Management
        res = client.post("/api/v1/support/chat", json={"message": "How do I invite team members?"})
        assert res.status_code == 200
        assert "Invite User" in res.json()["answer"]

        # Security & Retention
        res = client.post("/api/v1/support/chat", json={"message": "data encryption at rest"})
        assert res.status_code == 200
        assert "AES-256" in res.json()["answer"]

        # Autopilot
        res = client.post("/api/v1/support/chat", json={"message": "how does autopilot deduplication work?"})
        assert res.status_code == 200
        assert "tenant_autopilot_logs" in res.json()["answer"]

    def test_generic_keyword_does_not_beat_a_more_specific_topic(self, db_session: Session):
        """BE Gap 254: "Is my data encrypted at rest?" used to return the CSV
        export guide. `"data"` is a genuine whole word, so word-boundary matching
        did nothing for it — export_reports and security_retention tied 1-1 on
        hit count and the stable sort handed it to whichever came first in the
        topic list. Fixed by dropping the over-generic keyword and tie-breaking
        on total matched-keyword length (specificity) rather than list order."""
        res = client.post("/api/v1/support/chat", json={"message": "Is my data encrypted at rest?"})
        assert res.status_code == 200
        body = res.json()
        assert "AES-256" in body["answer"]
        assert "Export CSV" not in body["answer"]

    def test_low_confidence_fallback_is_not_framed_as_a_diagnosed_incident(self, db_session: Session):
        """BE Gap 254: a plain miss must not raise the red "Issue Diagnosis"
        card — but it must still leave a way to raise a ticket, hence the
        separate `low_confidence` flag plus a prefillable context (Fix 9)."""
        res = client.post("/api/v1/support/chat", json={"message": "how do I wash my car?"})
        assert res.status_code == 200
        body = res.json()
        assert "I couldn't find a specific help article" in body["answer"]
        assert body["suggest_escalation"] is False
        assert body["low_confidence"] is True
        assert body["escalation_context"]["priority"] == "NORMAL"

    def test_answered_and_escalated_paths_are_not_low_confidence(self, db_session: Session):
        """The new flag must mean "no article matched", not "anything at all"."""
        answered = client.post("/api/v1/support/chat", json={"message": "How do I reset my password?"})
        assert answered.json()["low_confidence"] is False

        escalated = client.post(
            "/api/v1/support/chat",
            json={"message": "We experienced a 504 gateway timeout during batch sync"},
        )
        assert escalated.json()["suggest_escalation"] is True
        assert escalated.json()["low_confidence"] is False

    def test_matched_topic_echoes_topic_id(self, db_session: Session):
        """BE Gap 256: the response must carry the matched topic id for the FE."""
        res = client.post("/api/v1/support/chat", json={"message": "How do I invite team members?"})
        assert res.status_code == 200
        assert res.json()["topic_id"] == "user_management"

    def test_follow_up_resolves_via_last_topic_id(self, db_session: Session):
        """BE Gap 256: a short anaphoric follow-up reuses the prior topic."""
        res = client.post(
            "/api/v1/support/chat",
            json={"message": "how do I do that?", "last_topic_id": "user_management"},
        )
        assert res.status_code == 200
        body = res.json()
        assert "Invite User" in body["answer"]
        assert body["topic_id"] == "user_management"
        assert body["low_confidence"] is False

    def test_follow_up_without_last_topic_id_still_misses(self, db_session: Session):
        """Without `last_topic_id`, an anaphoric follow-up must still be a plain miss."""
        res = client.post("/api/v1/support/chat", json={"message": "how do I do that?"})
        assert res.status_code == 200
        body = res.json()
        assert body["low_confidence"] is True
        assert body["topic_id"] is None

    def test_invalid_last_topic_id_is_ignored(self, db_session: Session):
        res = client.post(
            "/api/v1/support/chat",
            json={"message": "how do I do that?", "last_topic_id": "not_a_real_topic"},
        )
        assert res.status_code == 200
        assert res.json()["low_confidence"] is True

    def test_history_is_accepted_but_does_not_resolve_follow_ups(self, db_session: Session):
        """BE Gap 256: `history` alone must not resolve a follow-up — only `last_topic_id`."""
        history = [
            {"role": "user", "content": "How do I invite team members?"},
            {"role": "assistant", "content": "### User Management & Permissions\n\nGo to settings."},
        ]
        with_history = client.post(
            "/api/v1/support/chat", json={"message": "how do I do that?", "history": history}
        )
        without_history = client.post("/api/v1/support/chat", json={"message": "how do I do that?"})
        assert with_history.status_code == 200
        assert with_history.json() == without_history.json()
        assert with_history.json()["low_confidence"] is True

    def test_error_triggers_are_not_shadowed_by_kb_keywords(self, db_session: Session):
        """BE Gap 254 / Fix 7 — a standing screen, not a one-off assertion.

        KB topics are matched before ERROR_TRIGGERS and return early, so any KB
        keyword overlapping an error phrasing makes that error path unreachable.
        That is how `billing`'s `"payu"`/`"checkout"` keywords silently disabled
        `ERR_PAYU_BILLING_FAILURE`. Any future topic/keyword addition that
        re-creates the collision fails here rather than in production.
        """
        phrasings = {
            "ERR_GATEWAY_TIMEOUT_504": [
                "We experienced a 504 gateway timeout during batch sync",
                "getting a gateway timeout",
                "batch sync timeout",
            ],
            "ERR_INTERNAL_SERVER_500": [
                "internal server error",
                "database connection error",
                "the app keeps throwing a 500",
            ],
            "ERR_PAYU_BILLING_FAILURE": [
                "payu error",
                "my payment failed",
                "double charge",
                "checkout crash",
            ],
        }
        for expected_code, messages in phrasings.items():
            for message in messages:
                body = client.post("/api/v1/support/chat", json={"message": message}).json()
                assert body["suggest_escalation"] is True, f"{message!r} never reached the error path"
                assert body["escalation_context"]["error_code"] == expected_code, (
                    f"{message!r} resolved to {body['escalation_context']['error_code']}, "
                    f"expected {expected_code} — a KB keyword is shadowing this trigger"
                )


# ---------------------------------------------------------------------------
# Gap 403: semantic (vector) fallback for zero-keyword-match queries
# ---------------------------------------------------------------------------

class TestSupportAgentVectorFallback:
    """
    Gap 403 — support_agent.py's evaluate_support_query() now tries a
    semantic match over KNOWLEDGE_TOPICS before giving up on a query that
    scored zero keyword hits (and isn't an error trigger / human-help ask).

    Why these tests don't rely on real embeddings: MOCK_EMBEDDINGS=true (set
    at the top of this file) means every call goes through
    chroma_client.get_embeddings()'s mock branch, which returns
    random.uniform(-0.1, 0.1) vectors over 1024 dims, normalized. Two
    independent random unit vectors in 1024 dimensions concentrate tightly
    around cosine distance 1.0 (orthogonal) — nowhere near
    SUPPORT_RELEVANCE_DISTANCE_THRESHOLD's 0.35 — which is *why* every
    pre-existing "should miss" test above (e.g. "how do I wash my car?")
    still passes unmodified with this fallback wired in: the mock path
    essentially never produces a false-positive semantic match. That property
    is exercised directly below rather than just asserted in prose. Proving a
    *correct* semantic match (as opposed to "nothing accidentally matched")
    needs a controlled embedding, since random mock vectors carry no real
    meaning to test against (Gap 244's process lesson) — so the positive
    match test below monkeypatches agents.support_agent.get_embeddings
    directly rather than relying on MOCK_EMBEDDINGS' randomness.
    """

    @pytest.fixture(autouse=True)
    def _fresh_support_collection(self):
        """Every test in this class re-seeds the shared support-topics Chroma
        collection from scratch, so whichever embedding function (default
        mock or a test's own monkeypatch) is active at test time is the one
        that actually populates it — this class neither depends on nor leaks
        into another test's seeding order."""
        import agents.support_agent as support_agent_mod

        def _reset():
            chroma = support_agent_mod.get_chroma_client()
            try:
                chroma.delete_collection(name=support_agent_mod._SUPPORT_COLLECTION_NAME)
            except Exception:
                pass
            support_agent_mod._support_collection_seeded = False

        _reset()
        yield
        _reset()

    def test_random_mock_vectors_do_not_produce_false_positive_matches(self, db_session: Session):
        """The safety property every other test in this file leans on: under
        the mock embedding path, a query semantically unrelated to all 12
        topics still falls through to the existing low-confidence miss."""
        res = client.post(
            "/api/v1/support/chat",
            json={"message": "recommend a good pizza topping for dinner tonight"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["low_confidence"] is True
        assert body["topic_id"] is None

    def test_semantic_match_with_no_keyword_overlap_resolves_via_vector_search(
        self, db_session: Session, monkeypatch
    ):
        """The actual point of Gap 403: a paraphrase sharing *zero* keywords
        with any topic (so the existing keyword pass cannot match it) still
        resolves to the right topic once semantic distance is small.
        Embeddings are monkeypatched to a controlled mapping — this proves
        the retrieval *wiring* (query embed -> Chroma query -> threshold ->
        topic lookup), not a real model's judgment, which is what the
        approved scope deliberately left out (be_features_tracker.md Gap 403:
        hybrid vector search only, no LLM call, and a real-model quality
        claim would need a live/manual run this task didn't do)."""
        import agents.support_agent as support_agent_mod

        autopilot_topic = next(
            t for t in support_agent_mod.KNOWLEDGE_TOPICS if t["id"] == "autopilot"
        )
        autopilot_text = support_agent_mod._topic_embedding_text(autopilot_topic)
        paraphrase = "does the tool stop me from feeding it the same document more than once"

        # Precondition: the paraphrase must not already win on keywords, or
        # this test would pass for the wrong reason (step 1, not step 5).
        assert support_agent_mod._score_topic(autopilot_topic, paraphrase.lower())[0] == 0

        def fake_get_embeddings(texts: list[str]) -> list[list[float]]:
            near = [1.0] + [0.0] * 1023  # the "autopilot" concept
            far = [0.0, 1.0] + [0.0] * 1022  # every other topic
            return [near if t in (autopilot_text, paraphrase) else far for t in texts]

        monkeypatch.setattr(support_agent_mod, "get_embeddings", fake_get_embeddings)

        res = client.post("/api/v1/support/chat", json={"message": paraphrase})
        assert res.status_code == 200
        body = res.json()
        assert body["topic_id"] == "autopilot"
        assert body["low_confidence"] is False
        assert body["suggest_escalation"] is False
        assert "Autopilot" in body["answer"]

    def test_vector_fallback_never_overrides_a_keyword_match(self, db_session: Session, monkeypatch):
        """A genuine keyword hit is decided in step 1 and must never reach the
        vector fallback — proven with a call counter, not just the final
        topic_id, since a forced-identical-vector mock would otherwise "match"
        every topic equally and mask an ordering bug that let it through."""
        import agents.support_agent as support_agent_mod

        calls: list[list[str]] = []

        def spy_get_embeddings(texts: list[str]) -> list[list[float]]:
            calls.append(texts)
            return [[1.0] + [0.0] * 1023 for _ in texts]

        monkeypatch.setattr(support_agent_mod, "get_embeddings", spy_get_embeddings)

        res = client.post("/api/v1/support/chat", json={"message": "How do I reset my password?"})
        assert res.status_code == 200
        assert res.json()["topic_id"] == "account_auth"
        assert calls == [], "vector fallback ran even though the keyword pass already matched"

    def test_error_trigger_still_wins_over_a_forced_semantic_match(self, db_session: Session, monkeypatch):
        """Hard guarantee that must survive Gap 403: error triggers are
        checked before the vector fallback, so a real incident escalation can
        never even reach embedding code, let alone be suppressed by it."""
        import agents.support_agent as support_agent_mod

        calls: list[list[str]] = []

        def spy_get_embeddings(texts: list[str]) -> list[list[float]]:
            calls.append(texts)
            return [[1.0] + [0.0] * 1023 for _ in texts]

        monkeypatch.setattr(support_agent_mod, "get_embeddings", spy_get_embeddings)

        res = client.post(
            "/api/v1/support/chat",
            json={"message": "We experienced a 504 gateway timeout during batch sync"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["suggest_escalation"] is True
        assert body["escalation_context"]["error_code"] == "ERR_GATEWAY_TIMEOUT_504"
        assert calls == [], "vector fallback ran for a query that should have escalated on the error-trigger path"

    def test_vector_search_failure_degrades_to_the_existing_miss(self, db_session: Session, monkeypatch):
        """A Chroma/embedding outage must not break the Support Assistant —
        it should only cost this one enhancement and behave exactly as it did
        before Gap 403."""
        import agents.support_agent as support_agent_mod

        def broken_get_embeddings(texts: list[str]) -> list[list[float]]:
            raise RuntimeError("chroma is unreachable")

        monkeypatch.setattr(support_agent_mod, "get_embeddings", broken_get_embeddings)

        res = client.post(
            "/api/v1/support/chat",
            json={"message": "recommend a good pizza topping for dinner tonight"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["low_confidence"] is True
        assert body["topic_id"] is None


# ---------------------------------------------------------------------------
# Security & Hardening Tests (BE Gaps 249, 250, 251)
# ---------------------------------------------------------------------------

class TestSecurityHardening:
    """Tests 25–33: HTML escaping, length limits, rate limiting, and keyspace."""

    def test_html_in_name_is_escaped_in_receipt_email(self, db_session: Session):
        """Test 25 (BE 250): Malicious HTML in name is escaped in user receipt email."""
        from services.support_email import _receipt_html
        ticket = SupportTicket(
            ticket_number="INQ-2026-A1B2C3D4",
            user_email="victim@example.com",
            user_name='</p><a href="https://evil.tld">Click here</a><p>',
            priority="NORMAL",
            source="WEBSITE_CONTACT",
            category="GENERAL",
            subject="Test Subject",
            description="Test Message",
        )
        html = _receipt_html(ticket)
        assert "<script>" not in html
        assert '<a href="https://evil.tld">' not in html
        assert "&lt;a href=&quot;https://evil.tld&quot;&gt;Click here&lt;/a&gt;" in html or "&lt;/p&gt;" in html

    def test_html_in_name_is_escaped_in_staff_alert(self, db_session: Session):
        """Test 26 (BE 250): Malicious HTML in name is escaped in staff alert email."""
        from services.support_email import _ticket_html
        ticket = SupportTicket(
            ticket_number="INQ-2026-A1B2C3D4",
            user_email="victim@example.com",
            user_name='<script>alert("pwned")</script>',
            priority="NORMAL",
            source="WEBSITE_CONTACT",
            category="GENERAL",
            subject="Test Subject",
            description="Test Message",
        )
        html = _ticket_html(ticket)
        assert "<script>" not in html
        assert "&lt;script&gt;alert(&quot;pwned&quot;)&lt;/script&gt;" in html

    def test_html_in_description_is_escaped_in_staff_alert(self, db_session: Session):
        """Test 27 (BE 250): Malicious HTML in description/message is escaped."""
        from services.support_email import _ticket_html
        ticket = SupportTicket(
            ticket_number="INQ-2026-A1B2C3D4",
            user_email="victim@example.com",
            user_name="John Doe",
            priority="NORMAL",
            source="WEBSITE_CONTACT",
            category="GENERAL",
            subject="Test Subject",
            description='<img src=x onerror="alert(1)">',
        )
        html = _ticket_html(ticket)
        assert "<img src=x" not in html
        assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in html

    def test_html_in_company_is_escaped_in_staff_alert(self, db_session: Session):
        """Test 28 (BE 250): Malicious HTML in company name is escaped."""
        from services.support_email import _ticket_html
        ticket = SupportTicket(
            ticket_number="INQ-2026-A1B2C3D4",
            user_email="victim@example.com",
            user_name="John Doe",
            company_name='<b>Evil Corp</b><iframe src="evil.com"></iframe>',
            priority="NORMAL",
            source="WEBSITE_CONTACT",
            category="GENERAL",
            subject="Test Subject",
            description="Test Message",
        )
        html = _ticket_html(ticket)
        assert "<iframe>" not in html
        assert "&lt;iframe src=&quot;evil.com&quot;&gt;&lt;/iframe&gt;" in html

    def test_name_over_255_chars_is_rejected(self, db_session: Session):
        """Test 29 (BE 250): Name exceeding 255 chars returns 422 rather than 500 DB error."""
        payload = {**VALID_CONTACT_PAYLOAD, "name": "A" * 256}
        res = client.post("/api/v1/support/contact", json=payload)
        assert res.status_code == 422
        assert "255 characters" in res.text

    def test_company_over_255_chars_is_rejected(self, db_session: Session):
        """Test 30 (BE 250): Company exceeding 255 chars returns 422 rather than 500 DB error."""
        payload = {**VALID_CONTACT_PAYLOAD, "company": "B" * 256}
        res = client.post("/api/v1/support/contact", json=payload)
        assert res.status_code == 422
        assert "255 characters" in res.text

    def test_rate_limit_returns_429_after_threshold(self, db_session: Session):
        """Test 31 (BE 249): 6th submission within window returns 429 Too Many Requests."""
        headers = {"X-Forwarded-For": "198.51.100.42"}
        for i in range(5):
            res = client.post(
                "/api/v1/support/contact",
                json={**VALID_CONTACT_PAYLOAD, "email": f"user{i}@test.com"},
                headers=headers,
            )
            assert res.status_code == 201, f"Attempt {i+1} failed: {res.text}"

        # 6th attempt from the same IP should be blocked
        res = client.post(
            "/api/v1/support/contact",
            json={**VALID_CONTACT_PAYLOAD, "email": "user6@test.com"},
            headers=headers,
        )
        assert res.status_code == 429
        assert "Retry-After" in res.headers
        assert res.headers["Retry-After"] == "300"
        assert "Too many requests" in res.json()["detail"]

    def test_ticket_number_uses_hex_format(self, db_session: Session):
        """Test 32 (BE 251): Generated ticket number has 8-character uppercase hex suffix."""
        res = client.post("/api/v1/support/contact", json=VALID_CONTACT_PAYLOAD)
        assert res.status_code == 201
        ticket_number = res.json()["ticket_number"]
        parts = ticket_number.split("-")
        assert len(parts) == 3
        assert parts[0] == "INQ"
        assert len(parts[1]) == 4  # year
        assert len(parts[2]) == 8  # 8 hex chars
        assert re.match(r"^[0-9A-F]{8}$", parts[2]) is not None

    def test_ticket_generation_exhaustion_returns_503_not_500(self, db_session: Session):
        """Test 33 (BE 251): When ticket collision occurs 10 times, returns 503 rather than unhandled 500."""
        from routers.support import _unique_ticket_number
        from fastapi import HTTPException

        # Seed a dummy ticket
        dummy = SupportTicket(
            ticket_number="INQ-2026-DEADBEEF",
            user_email="test@example.com",
            user_name="Test",
            priority="NORMAL",
            source="WEBSITE_CONTACT",
            category="GENERAL",
            subject="Test",
            description="Test",
        )
        db_session.add(dummy)
        db_session.commit()

        # Patch _generate_ticket_number to always return the existing number
        with patch("routers.support._generate_ticket_number", return_value="INQ-2026-DEADBEEF"):
            with pytest.raises(HTTPException) as exc_info:
                _unique_ticket_number(db_session, prefix="INQ", max_attempts=3)
            assert exc_info.value.status_code == 503
            assert "temporarily busy" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Gap 249 hardening pass (2026-08-18): holes left by the first Gap 249 fix
# ---------------------------------------------------------------------------


def _fake_request(headers: dict[str, str], client_host: str | None = "10.0.0.1"):
    """Minimal Starlette Request carrying just the headers/peer under test."""
    from starlette.requests import Request

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/support/contact",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (client_host, 12345) if client_host else None,
    }
    return Request(scope)


class TestSubjectLengthOverflow:
    """
    Test 34: the subject built by submit_contact_inquiry must never exceed
    SupportTicket.subject's max_length=255.

    This is the bug class the branch claimed to have closed by capping `name` at
    255: `name` alone passes that validator, but the "[CATEGORY] Contact inquiry
    from " prefix adds another 31-41 characters on top, so the *constructed*
    subject overflowed and Postgres raised StringDataRightTruncation -- an
    uncaught 500.

    The assertion is on the stored string's length rather than on the response
    status deliberately: these tests run against in-memory SQLite, which does
    not enforce max_length, so a status-only assertion would pass even with the
    bug present. Asserting the length directly is what makes this a real
    regression test -- it fails against the pre-fix code.
    """

    def test_long_name_does_not_produce_oversized_subject(self, db_session: Session):
        from sqlmodel import select

        category = "TECHNICAL_SUPPORT"  # the longest category, worst-case prefix
        prefix = f"[{category}] Contact inquiry from "
        name = "A" * 255

        # Preconditions that define the bug: the name is individually legal,
        # but prefix + name is not.
        assert len(name) <= 255, "name must pass its own validator"
        assert len(prefix) + len(name) > 255, "this input must overflow pre-fix"

        res = client.post(
            "/api/v1/support/contact",
            json={**VALID_CONTACT_PAYLOAD, "name": name, "category": category},
        )
        assert res.status_code == 201, res.text

        ticket = db_session.exec(
            select(SupportTicket).where(
                SupportTicket.ticket_number == res.json()["ticket_number"]
            )
        ).first()
        assert ticket is not None
        assert len(ticket.subject) <= 255, (
            f"subject is {len(ticket.subject)} chars -- would be a "
            f"StringDataRightTruncation 500 on real Postgres"
        )
        assert ticket.subject.startswith(prefix)

    def test_shortest_prefix_boundary_also_capped(self, db_session: Session):
        """The tight boundary: GENERAL's 31-char prefix + a 225-char name = 256."""
        from sqlmodel import select

        prefix = "[GENERAL] Contact inquiry from "
        name = "B" * (256 - len(prefix))
        assert len(prefix) + len(name) == 256

        res = client.post(
            "/api/v1/support/contact",
            json={**VALID_CONTACT_PAYLOAD, "name": name, "category": "GENERAL"},
        )
        assert res.status_code == 201, res.text
        ticket = db_session.exec(
            select(SupportTicket).where(
                SupportTicket.ticket_number == res.json()["ticket_number"]
            )
        ).first()
        assert len(ticket.subject) == 255

    def test_subject_within_limit_is_not_truncated(self, db_session: Session):
        """Guard against over-truncating a normal-length subject."""
        from sqlmodel import select

        res = client.post(
            "/api/v1/support/contact",
            json={**VALID_CONTACT_PAYLOAD, "name": "Jane Doe", "category": "SALES"},
        )
        assert res.status_code == 201
        ticket = db_session.exec(
            select(SupportTicket).where(
                SupportTicket.ticket_number == res.json()["ticket_number"]
            )
        ).first()
        assert ticket.subject == "[SALES] Contact inquiry from Jane Doe"


class TestClientIpResolution:
    """
    Test 35: the rate-limit key must not be attacker-controlled.

    The original _get_client_ip took the leftmost X-Forwarded-For entry, which
    is the value the *client* supplied -- rotating it reset the window on every
    request, defeating the limiter entirely.
    """

    def test_parse_ip_accepts_real_addresses(self):
        from routers.support import _parse_ip

        assert _parse_ip("203.0.113.5") == "203.0.113.5"
        assert _parse_ip("  203.0.113.5  ") == "203.0.113.5"
        assert _parse_ip("203.0.113.5:443") == "203.0.113.5"
        assert _parse_ip("2001:db8::1") == "2001:db8::1"
        assert _parse_ip("[2001:db8::1]:443") == "2001:db8::1"

    @pytest.mark.parametrize(
        "value",
        [
            "not-an-ip",
            "",
            "   ",
            None,
            "999.999.999.999",
            "1.2.3.4.5",
            "<script>alert(1)</script>",
            "A" * 5000,
        ],
    )
    def test_parse_ip_rejects_junk(self, value):
        """Junk must not become a rate-limit key -- that is the memory-growth vector."""
        from routers.support import _parse_ip

        assert _parse_ip(value) is None

    def test_rightmost_forwarded_for_entry_wins(self):
        """The platform appends the peer it saw; the leftmost is the client's claim."""
        from routers.support import _get_client_ip

        req = _fake_request({"X-Forwarded-For": "1.1.1.1, 2.2.2.2, 203.0.113.9"})
        assert _get_client_ip(req) == "203.0.113.9"

    def test_junk_entries_are_skipped_right_to_left(self):
        from routers.support import _get_client_ip

        req = _fake_request({"X-Forwarded-For": "203.0.113.9, garbage, unknown"})
        assert _get_client_ip(req) == "203.0.113.9"

    def test_x_client_ip_outranks_forwarded_for(self):
        """Our own proxy's attestation beats the pod IP the platform appends."""
        from routers.support import _get_client_ip

        req = _fake_request(
            {"X-Client-IP": "203.0.113.77", "X-Forwarded-For": "1.1.1.1, 10.0.0.5"}
        )
        assert _get_client_ip(req) == "203.0.113.77"

    def test_x_real_ip_is_ignored(self):
        """X-Real-IP is forgeable and nothing in our path needs it -- honouring
        it would reopen the bypass."""
        from routers.support import _get_client_ip

        req = _fake_request({"X-Real-IP": "1.2.3.4"}, client_host="10.0.0.9")
        assert _get_client_ip(req) == "10.0.0.9"

    def test_falls_back_to_socket_peer(self):
        from routers.support import _get_client_ip

        assert _get_client_ip(_fake_request({}, client_host="10.0.0.9")) == "10.0.0.9"
        assert _get_client_ip(_fake_request({}, client_host=None)) == "unknown"

    def test_azure_client_ip_ignored_when_front_door_id_unset(self, monkeypatch):
        """Today's real state: Front Door is not deployed, so X-Azure-* headers
        are forgeable and must be ignored outright."""
        import routers.support as support_mod
        from routers.support import _get_client_ip

        monkeypatch.setattr(support_mod.settings, "FRONT_DOOR_ID", "")
        req = _fake_request(
            {
                "X-Azure-FDID": "anything-at-all",
                "X-Azure-ClientIP": "1.2.3.4",
                "X-Forwarded-For": "203.0.113.9",
            }
        )
        assert _get_client_ip(req) == "203.0.113.9"

    def test_azure_client_ip_used_when_fdid_matches(self, monkeypatch):
        import routers.support as support_mod
        from routers.support import _get_client_ip

        monkeypatch.setattr(support_mod.settings, "FRONT_DOOR_ID", "real-fd-guid")
        req = _fake_request(
            {
                "X-Azure-FDID": "real-fd-guid",
                "X-Azure-ClientIP": "198.51.100.20",
                "X-Forwarded-For": "203.0.113.9",
            }
        )
        assert _get_client_ip(req) == "198.51.100.20"

    def test_azure_client_ip_rejected_when_fdid_mismatches(self, monkeypatch):
        import routers.support as support_mod
        from routers.support import _get_client_ip

        monkeypatch.setattr(support_mod.settings, "FRONT_DOOR_ID", "real-fd-guid")
        req = _fake_request(
            {
                "X-Azure-FDID": "attacker-guess",
                "X-Azure-ClientIP": "1.2.3.4",
                "X-Forwarded-For": "203.0.113.9",
            }
        )
        assert _get_client_ip(req) == "203.0.113.9"


class TestRateLimitBypassResistance:
    """Test 36: end-to-end -- spoofed headers must not reset the window."""

    def test_rotating_leftmost_forwarded_for_cannot_reset_window(self, db_session: Session):
        """
        The core Gap 249 bypass. Each request carries a fresh spoofed leftmost
        XFF entry but the same platform-appended rightmost one. Pre-fix every
        request keyed on the rotating value and none were ever limited.

        Emails are distinct so the block can only come from the IP dimension.
        """
        for i in range(5):
            res = client.post(
                "/api/v1/support/contact",
                json={**VALID_CONTACT_PAYLOAD, "email": f"spoof{i}@test.com"},
                headers={"X-Forwarded-For": f"10.99.{i}.{i}, 198.51.100.77"},
            )
            assert res.status_code == 201, f"Attempt {i + 1}: {res.text}"

        res = client.post(
            "/api/v1/support/contact",
            json={**VALID_CONTACT_PAYLOAD, "email": "spoof6@test.com"},
            headers={"X-Forwarded-For": "10.99.6.6, 198.51.100.77"},
        )
        assert res.status_code == 429, (
            "rotating the client-supplied XFF entry bypassed the limiter"
        )

    def test_rotating_azure_client_ip_cannot_reset_window(self, db_session: Session):
        """Same bypass via forged Front Door headers, with FRONT_DOOR_ID unset."""
        for i in range(5):
            res = client.post(
                "/api/v1/support/contact",
                json={**VALID_CONTACT_PAYLOAD, "email": f"azspoof{i}@test.com"},
                headers={
                    "X-Azure-FDID": "forged",
                    "X-Azure-ClientIP": f"10.98.{i}.{i}",
                    "X-Forwarded-For": "198.51.100.88",
                },
            )
            assert res.status_code == 201, f"Attempt {i + 1}: {res.text}"

        res = client.post(
            "/api/v1/support/contact",
            json={**VALID_CONTACT_PAYLOAD, "email": "azspoof6@test.com"},
            headers={
                "X-Azure-FDID": "forged",
                "X-Azure-ClientIP": "10.98.6.6",
                "X-Forwarded-For": "198.51.100.88",
            },
        )
        assert res.status_code == 429

    def test_email_dimension_still_limits_across_distinct_ips(self, db_session: Session):
        """A distributed caller rotating *real* IPs is still caught on email."""
        for i in range(5):
            res = client.post(
                "/api/v1/support/contact",
                json={**VALID_CONTACT_PAYLOAD, "email": "same@test.com"},
                headers={"X-Forwarded-For": f"198.51.100.{100 + i}"},
            )
            assert res.status_code == 201, f"Attempt {i + 1}: {res.text}"

        res = client.post(
            "/api/v1/support/contact",
            json={**VALID_CONTACT_PAYLOAD, "email": "same@test.com"},
            headers={"X-Forwarded-For": "198.51.100.199"},
        )
        assert res.status_code == 429


class TestRateLimiterStateBounds:
    """
    Test 37: limiter state must be bounded and must survive Redis being down.

    The Redis path is the shared-across-replicas one; these exercise the
    in-process fallback, which is what has to be bounded.
    """

    @staticmethod
    def _memory_limiter():
        from routers.support import _ContactRateLimiter

        limiter = _ContactRateLimiter()
        limiter._redis_client = False  # force the fallback path
        return limiter

    def test_memory_fallback_enforces_the_limit(self):
        limiter = self._memory_limiter()
        for _ in range(5):
            assert limiter.check("203.0.113.1", "a@test.com") is True
        assert limiter.check("203.0.113.1", "a@test.com") is False

    def test_memory_fallback_prunes_expired_keys(self):
        """Entries outside the window are dropped on every check, not left to
        accumulate -- this is the memory-growth half of the finding."""
        limiter = self._memory_limiter()
        stale_at = time.time() - 10_000
        limiter._memory["ip:198.51.100.1"] = [stale_at]
        limiter._memory["email:stale@test.com"] = [stale_at]

        assert limiter.check("203.0.113.2", "fresh@test.com") is True

        assert "ip:198.51.100.1" not in limiter._memory
        assert "email:stale@test.com" not in limiter._memory
        assert "ip:203.0.113.2" in limiter._memory

    def test_memory_fallback_caps_total_tracked_keys(self, monkeypatch):
        """An attacker rotating keys cannot grow the store without bound."""
        import routers.support as support_mod

        monkeypatch.setattr(support_mod, "_MEMORY_MAX_TRACKED_KEYS", 50)
        limiter = self._memory_limiter()
        for i in range(400):
            limiter.check(f"198.51.{i // 256}.{i % 256}", f"u{i}@test.com")

        assert len(limiter._memory) <= 50, (
            f"tracked keys grew to {len(limiter._memory)} despite the cap"
        )

    def test_rejected_lookup_does_not_create_a_permanent_key(self):
        """The old defaultdict created an entry for every key merely looked at,
        including ones whose request was then rejected."""
        limiter = self._memory_limiter()
        for _ in range(5):
            limiter.check("203.0.113.3", "blocked@test.com")
        keys_before = set(limiter._memory)

        assert limiter.check("203.0.113.3", "brand-new@test.com") is False
        # The IP was already over the limit, so the email key must not be
        # created as a side effect of the rejected check.
        assert "email:brand-new@test.com" not in limiter._memory
        assert set(limiter._memory) == keys_before

    def test_redis_failure_degrades_to_memory_instead_of_500(self, db_session: Session):
        """A Redis outage must not fail the contact form, and must not fail open."""
        from routers.support import _rate_limiter

        class _BrokenRedis:
            def pipeline(self):
                raise RuntimeError("redis connection lost")

        original = _rate_limiter._redis_client
        _rate_limiter._redis_client = _BrokenRedis()
        try:
            res = client.post(
                "/api/v1/support/contact",
                json={**VALID_CONTACT_PAYLOAD, "email": "degraded@test.com"},
                headers={"X-Client-IP": "203.0.113.40"},
            )
            assert res.status_code == 201, res.text

            # Still limiting, now via the in-process window.
            for i in range(4):
                assert (
                    client.post(
                        "/api/v1/support/contact",
                        json={**VALID_CONTACT_PAYLOAD, "email": f"degraded{i}@test.com"},
                        headers={"X-Client-IP": "203.0.113.40"},
                    ).status_code
                    == 201
                )
            res = client.post(
                "/api/v1/support/contact",
                json={**VALID_CONTACT_PAYLOAD, "email": "degraded-last@test.com"},
                headers={"X-Client-IP": "203.0.113.40"},
            )
            assert res.status_code == 429, "limiter failed open when Redis died"
        finally:
            _rate_limiter._redis_client = original


# ---------------------------------------------------------------------------
# Gap 430: prose embeddings, the margin guard, and the re-seeding fix
# ---------------------------------------------------------------------------

class TestSupportRetrievalTuning:
    """The Gap 403 fallback shipped dead: threshold 0.35 against genuine
    matches measured at 0.31-0.53. These pin the corrected behaviour."""

    @pytest.fixture(autouse=True)
    def _fresh_collection(self):
        import agents.support_agent as sa

        def _reset():
            try:
                sa.get_chroma_client().delete_collection(name=sa._SUPPORT_COLLECTION_NAME)
            except Exception:
                pass
            sa._support_collection_seeded = False

        _reset()
        yield
        _reset()

    def test_topics_are_embedded_as_prose_not_a_keyword_dump(self):
        """The ranking inversion that made this feature useless came from
        embedding a bag of keywords: a question matched whichever bag shared
        vocabulary rather than the topic that answers it."""
        import agents.support_agent as sa

        topic = next(t for t in sa.KNOWLEDGE_TOPICS if t["id"] == "autopilot")
        text = sa._topic_embedding_text(topic)

        assert topic["guidance"] in text, "the prose answer must be what is embedded"
        assert topic["title"] in text
        # The keyword list must NOT be appended -- that reintroduces the exact
        # vocabulary collision this change removes.
        assert "sync now" not in text.replace(topic["guidance"], "")

    def test_thresholds_are_internally_consistent(self):
        """Guards against a future 'tidy-up' silently re-breaking this: the
        measured genuine band tops out at 0.5320 and the closest false positive
        sits at 0.5228, so the distance cutoff must sit between them, and the
        margin must stay below the tightest genuine gap (0.0193)."""
        import agents.support_agent as sa

        assert 0.50 <= sa.SUPPORT_RELEVANCE_DISTANCE_THRESHOLD <= 0.5228
        assert 0.0061 < sa.SUPPORT_RELEVANCE_MARGIN < 0.0193

    def test_ambiguous_match_returns_no_answer(self, monkeypatch):
        """Two topics scoring near-identically means the question belongs to
        neither. Answering with whichever won by a hair is how a confidently
        wrong article gets shown -- worse than the honest miss it replaced."""
        import agents.support_agent as sa

        # Two topics at effectively the same distance -> inside the margin.
        def near_identical(texts):
            out = []
            for t in texts:
                if t.startswith("QUERY"):
                    out.append([1.0, 0.0] + [0.0] * 1022)
                elif "Autopilot" in t:
                    out.append([0.78, 0.62] + [0.0] * 1022)
                else:
                    out.append([0.775, 0.632] + [0.0] * 1022)
            return out

        monkeypatch.setattr(sa, "get_embeddings", near_identical)
        assert sa._vector_match_topic("QUERY something ambiguous") is None

    def test_editing_the_knowledge_base_reseeds_the_index(self, monkeypatch):
        """The latent bug: seeding was guarded by `count() == 0`, so once the
        collection existed it was NEVER refreshed. Editing a topic left the
        index serving stale vectors forever, silently, in every environment."""
        import agents.support_agent as sa

        first = sa._topics_content_fingerprint()
        sa._get_support_collection()
        assert sa._support_collection_seeded is True

        # Simulate an edit to the knowledge base.
        original_title = sa.KNOWLEDGE_TOPICS[0]["title"]
        try:
            sa.KNOWLEDGE_TOPICS[0]["title"] = original_title + " (edited)"
            assert sa._topics_content_fingerprint() != first, "fingerprint must track content"

            # A new process would start with the module flag cleared.
            sa._support_collection_seeded = False
            collection = sa._get_support_collection()

            found = collection.get(ids=[sa._SUPPORT_VERSION_DOC_ID])
            stored = (found["metadatas"] or [{}])[0].get("fingerprint")
            assert stored == sa._topics_content_fingerprint(), "index must be re-seeded after an edit"
        finally:
            sa.KNOWLEDGE_TOPICS[0]["title"] = original_title

    def test_version_sentinel_is_never_returned_as_an_answer(self, monkeypatch):
        """The fingerprint marker is a zero vector living in the same
        collection. If it ever ranked, the user would get a blank answer."""
        import agents.support_agent as sa

        sa._get_support_collection()

        def all_equal(texts):
            return [[0.0] * 1024 for _ in texts]

        monkeypatch.setattr(sa, "get_embeddings", all_equal)
        result = sa._vector_match_topic("anything at all")
        # Either no answer, or a real topic -- never the sentinel.
        assert result is None or result["id"] != sa._SUPPORT_VERSION_DOC_ID
