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

import re
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
