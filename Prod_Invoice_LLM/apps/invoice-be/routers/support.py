"""
Feature Website 5 / Feature 19: Support Router — public inquiry intake + ticket creation.

Endpoints
---------
POST /api/v1/support/contact
    Public (unauthenticated) endpoint consumed by the invoice-website /contact
    form proxy. Creates a SupportTicket(source=WEBSITE_CONTACT) and dispatches
    alert emails to SUPPORT_NOTIFY_EMAIL + an acknowledgement receipt to the
    submitter.

POST /api/v1/support/ticket
    Authenticated endpoint consumed by the invoice-fe Help Center.
    Used for chatbot-escalated tickets (source=HELP_CHATBOT) and direct manual
    tickets (source=DIRECT_TICKET). Attaches the conversation transcript.

GET  /api/v1/support/tickets
    Authenticated — lists a tenant's own submitted tickets.
"""
from __future__ import annotations

import logging
import secrets
import time
from collections import defaultdict
from datetime import datetime
from threading import Lock
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlmodel import Session, select

from config import get_settings
from dependencies import get_tenant_context_allow_unpaid, get_db_session, TenantContext
from models import SupportTicket, User
from services.support_email import dispatch_support_ticket_email
from agents.support_agent import evaluate_support_query

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Support"])
settings = get_settings()

# ---------------------------------------------------------------------------
# Ticket number generation
# ---------------------------------------------------------------------------

def _generate_ticket_number(prefix: str) -> str:
    """
    Generates a human-visible reference like INQ-2026-A1B2C3D4 or TICK-2026-9173A5B8.
    Uses 8 hex characters from secrets.token_hex(4), providing 4.29 billion
    possible values per year per prefix.
    """
    year = datetime.utcnow().year
    suffix = secrets.token_hex(4).upper()
    return f"{prefix}-{year}-{suffix}"


def _unique_ticket_number(db: Session, prefix: str, max_attempts: int = 10) -> str:
    """Retries until a number is not already in the table."""
    for _ in range(max_attempts):
        number = _generate_ticket_number(prefix)
        existing = db.exec(select(SupportTicket).where(SupportTicket.ticket_number == number)).first()
        if not existing:
            return number
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Ticket generation service temporarily busy — please retry.",
    )


# ---------------------------------------------------------------------------
# Rate limiting for public contact inquiries (BE Gap 249)
# ---------------------------------------------------------------------------

class _ContactRateLimiter:
    """
    Thread-safe in-memory sliding window rate limiter for public contact submissions.
    Tracks timestamps per IP and per email.
    """
    def __init__(self):
        self._ip_history: dict[str, list[float]] = defaultdict(list)
        self._email_history: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def check(self, ip: str, email: str, max_requests: int = 5, window_seconds: int = 300) -> bool:
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            # Clean and check IP
            ip_records = [t for t in self._ip_history[ip] if t > cutoff]
            self._ip_history[ip] = ip_records
            if len(ip_records) >= max_requests:
                return False

            # Clean and check email
            email_norm = email.lower().strip()
            email_records = [t for t in self._email_history[email_norm] if t > cutoff]
            self._email_history[email_norm] = email_records
            if len(email_records) >= max_requests:
                return False

            # Record this attempt
            self._ip_history[ip].append(now)
            self._email_history[email_norm].append(now)
            return True

    def reset(self):
        """Reset rate limit state (useful in tests)."""
        with self._lock:
            self._ip_history.clear()
            self._email_history.clear()

_rate_limiter = _ContactRateLimiter()


def _get_client_ip(request: Request) -> str:
    """Extract client IP respecting proxy headers."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

_VALID_CATEGORIES = {"SALES", "TECHNICAL_SUPPORT", "BILLING", "PARTNERSHIP", "GENERAL"}
_VALID_PRIORITIES = {"LOW", "NORMAL", "URGENT"}
_VALID_SOURCES    = {"WEBSITE_CONTACT", "HELP_CHATBOT", "DIRECT_TICKET"}


class ContactInquiryRequest(BaseModel):
    """Schema for POST /api/v1/support/contact — public, unauthenticated."""
    name: str
    email: EmailStr
    category: str = "GENERAL"
    company: str | None = None
    urgency: str = "NORMAL"
    message: str

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name is required")
        if len(v) > 255:
            raise ValueError("name must be 255 characters or fewer")
        return v

    @field_validator("company")
    @classmethod
    def validate_company(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if len(v) > 255:
            raise ValueError("company must be 255 characters or fewer")
        return v or None

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message is required")
        if len(v) > 5000:
            raise ValueError("message must be 5000 characters or fewer")
        return v

    @field_validator("category")
    @classmethod
    def valid_category(cls, v: str) -> str:
        v = v.upper()
        if v not in _VALID_CATEGORIES:
            return "GENERAL"
        return v

    @field_validator("urgency")
    @classmethod
    def valid_urgency(cls, v: str) -> str:
        v = v.upper()
        if v not in _VALID_PRIORITIES:
            return "NORMAL"
        return v


class AppTicketRequest(BaseModel):
    """Schema for POST /api/v1/support/ticket — authenticated, from invoice-fe."""
    subject: str
    description: str
    category: str = "GENERAL"
    priority: str = "NORMAL"
    source: str = "DIRECT_TICKET"
    company: str | None = None
    chat_transcript: list[dict] = []

    @field_validator("subject")
    @classmethod
    def subject_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("subject is required")
        # Strip newlines from subject to prevent header injection
        v = v.replace("\r", " ").replace("\n", " ").strip()
        return v[:255]

    @field_validator("company")
    @classmethod
    def validate_company(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if len(v) > 255:
            raise ValueError("company must be 255 characters or fewer")
        return v or None

    @field_validator("category")
    @classmethod
    def valid_category(cls, v: str) -> str:
        return v.upper() if v.upper() in _VALID_CATEGORIES else "GENERAL"

    @field_validator("priority")
    @classmethod
    def valid_priority(cls, v: str) -> str:
        return v.upper() if v.upper() in _VALID_PRIORITIES else "NORMAL"

    @field_validator("source")
    @classmethod
    def valid_source(cls, v: str) -> str:
        return v.upper() if v.upper() in _VALID_SOURCES else "DIRECT_TICKET"


class TicketResponse(BaseModel):
    success: bool
    ticket_number: str
    message: str
    email_dispatched: bool


class SupportChatRequest(BaseModel):
    """Schema for POST /api/v1/support/chat — authenticated support troubleshooting."""
    message: str
    history: list[dict[str, Any]] = []

    @field_validator("message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message is required")
        return v


class SupportChatResponse(BaseModel):
    answer: str
    suggest_escalation: bool
    escalation_context: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# POST /api/v1/support/chat  — authenticated, Help Center AI assistant
# ---------------------------------------------------------------------------

@router.post(
    "/support/chat",
    response_model=SupportChatResponse,
    summary="Ask AI Support Assistant (SAGE) a troubleshooting query",
)
def support_chat_assistant(
    body: SupportChatRequest,
    context: TenantContext = Depends(get_tenant_context_allow_unpaid),
):
    result = evaluate_support_query(body.message, history=body.history)
    return SupportChatResponse(
        answer=result["answer"],
        suggest_escalation=result["suggest_escalation"],
        escalation_context=result.get("escalation_context"),
    )


# ---------------------------------------------------------------------------
# POST /api/v1/support/contact  — public, website contact form
# ---------------------------------------------------------------------------

@router.post(
    "/support/contact",
    response_model=TicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a website contact inquiry (public)",
    description=(
        "Public endpoint consumed by the invoice-website /contact form proxy. "
        "Creates a SupportTicket and dispatches an alert to SUPPORT_NOTIFY_EMAIL "
        "(Application@infinevocloud.com by default) plus an acknowledgement receipt "
        "to the submitter. No authentication required."
    ),
)
def submit_contact_inquiry(
    body: ContactInquiryRequest,
    request: Request,
    db: Session = Depends(get_db_session),
):
    client_ip = _get_client_ip(request)
    if not _rate_limiter.check(client_ip, str(body.email)):
        logger.warning("support/contact: rate limit exceeded for ip=%s email=%s", client_ip, body.email)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests — please try again in a few minutes.",
            headers={"Retry-After": "300"},
        )

    subject = f"[{body.category}] Contact inquiry from {body.name}"
    ticket_number = _unique_ticket_number(db, prefix="INQ")

    ticket = SupportTicket(
        ticket_number=ticket_number,
        user_email=str(body.email),
        user_name=body.name,
        source="WEBSITE_CONTACT",
        category=body.category,
        priority=body.urgency,
        subject=subject,
        description=body.message,
        company_name=body.company,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    logger.info("support/contact: persisted %s from %s", ticket_number, body.email)

    try:
        email_result = dispatch_support_ticket_email(ticket)
        email_ok = email_result.get("staff_alert", {}).get("status") == "sent"
    except Exception as exc:
        logger.error("support/contact: email dispatch error for %s: %s", ticket_number, exc)
        email_ok = False

    return TicketResponse(
        success=True,
        ticket_number=ticket_number,
        message=(
            f"Your inquiry has been received. Reference: {ticket_number}. "
            f"We will respond {'within 2 hours' if body.urgency == 'URGENT' else 'within 24 hours'}."
        ),
        email_dispatched=email_ok,
    )


# ---------------------------------------------------------------------------
# POST /api/v1/support/ticket  — authenticated, invoice-fe Help Center
# ---------------------------------------------------------------------------

@router.post(
    "/support/ticket",
    response_model=TicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a support ticket from the Help Center (authenticated)",
)
def submit_app_ticket(
    body: AppTicketRequest,
    context: TenantContext = Depends(get_tenant_context_allow_unpaid),
    db: Session = Depends(get_db_session),
):
    prefix = "TICK"
    ticket_number = _unique_ticket_number(db, prefix=prefix)

    # Resolve user email from the DB User row if available
    user_email = "support-user@invoiceeq.app"  # safe default
    user_name: str | None = None
    if context.db_user_id:
        db_user = db.get(User, context.db_user_id)
        if db_user:
            user_email = db_user.email
            name_parts = filter(None, [db_user.first_name, db_user.last_name])
            user_name = " ".join(name_parts) or None

    ticket = SupportTicket(
        ticket_number=ticket_number,
        tenant_id=context.tenant_id,
        user_id=context.db_user_id,
        user_email=user_email,
        user_name=user_name,
        source=body.source,
        category=body.category,
        priority=body.priority,
        subject=body.subject,
        description=body.description,
        company_name=body.company,
        chat_transcript=body.chat_transcript,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)

    logger.info(
        "support/ticket: persisted %s source=%s tenant=%s",
        ticket_number, body.source, ticket.tenant_id,
    )

    try:
        email_result = dispatch_support_ticket_email(ticket)
        email_ok = email_result.get("staff_alert", {}).get("status") == "sent"
    except Exception as exc:
        logger.error("support/ticket: email dispatch error for %s: %s", ticket_number, exc)
        email_ok = False

    return TicketResponse(
        success=True,
        ticket_number=ticket_number,
        message=f"Your support ticket has been raised. Reference: {ticket_number}.",
        email_dispatched=email_ok,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/support/tickets  — authenticated, tenant's own tickets
# ---------------------------------------------------------------------------

@router.get(
    "/support/tickets",
    summary="List this tenant's support tickets (authenticated)",
)
def list_support_tickets(
    context: TenantContext = Depends(get_tenant_context_allow_unpaid),
    db: Session = Depends(get_db_session),
):
    tickets = db.exec(
        select(SupportTicket)
        .where(SupportTicket.tenant_id == context.tenant_id)
        .order_by(SupportTicket.created_at.desc())
        .limit(50)
    ).all()
    return {
        "tickets": [
            {
                "ticket_number": t.ticket_number,
                "subject": t.subject,
                "category": t.category,
                "priority": t.priority,
                "status": t.status,
                "source": t.source,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tickets
        ]
    }
