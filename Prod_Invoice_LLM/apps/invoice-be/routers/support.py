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

import ipaddress
import logging
import secrets
import time
from collections import OrderedDict
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
# Client IP resolution for rate limiting (BE Gap 249)
# ---------------------------------------------------------------------------
#
# The value this returns is a rate-limit *key*, so anything the caller can
# freely choose is worthless: pick a fresh one per request and the window
# resets every time. The original implementation took the leftmost entry of
# `X-Forwarded-For`, which is precisely the attacker-controlled one -- a proxy
# appends the peer it actually saw to the *right* of whatever the client sent,
# so the leftmost element is just the first hop's unverified claim.
#
# Deployment topology this is written against (verified 2026-08-18 against
# infra/, not assumed):
#   * `invoice-website` is a Container App with `ingress.external: true`
#     (modules/compute/invoice-website.bicep) -- it is the real internet edge.
#   * `invoice-be` is `ingress.external: false` (modules/compute/invoice-be.bicep),
#     so the only thing that can reach this endpoint is an in-cluster caller,
#     in practice the website's /api/contact proxy.
#   * Azure Front Door exists in `infra/modules/network/front-door.bicep` on
#     master, but it is gated on the `customDomainName` param in 08-apps.bicep,
#     that param defaults to empty, and no deployment has been run. So Front
#     Door is NOT in the request path today, and X-Azure-* headers do not
#     currently arrive from anything trustworthy.
#
# Resolution order below follows from that, most trustworthy first.
#
# NOTE ON THE X-FORWARDED-FOR FALLBACK: Container Apps' ingress is Envoy, which
# runs with `use_remote_address` and therefore *appends* the connection peer to
# X-Forwarded-For rather than replacing the header. That makes the rightmost
# entry the one the platform itself observed. Taking the rightmost is also the
# strictly safer choice under uncertainty: if the platform appends, rightmost is
# the true peer; if it replaced the header outright, rightmost == leftmost ==
# the true peer. Only in the case where the platform passes the header through
# untouched would rightmost be attacker-controlled -- and in that case no header
# value is trustworthy and `request.client` is the only real source anyway.


def _parse_ip(value: str | None) -> str | None:
    """
    Return `value` normalised if it is a syntactically valid IP address, else None.

    Validating is not cosmetic: an unvalidated header value becomes an
    unbounded-cardinality rate-limit key, which is the memory-growth half of
    Gap 249. Rejecting non-IPs caps how much junk can ever enter the limiter.
    """
    if not value:
        return None
    candidate = value.strip()
    # Tolerate the "host:port" form some proxies emit for IPv4, and the
    # bracketed "[::1]:443" form used for IPv6.
    if candidate.startswith("["):
        candidate = candidate[1:].split("]", 1)[0]
    elif candidate.count(":") == 1:
        candidate = candidate.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _get_client_ip(request: Request) -> str:
    """
    Resolve the rate-limiting key for this request, trusting only values our own
    infrastructure produced. See the block comment above for the reasoning.
    """
    headers = request.headers

    # 1. Front Door, but only once it is genuinely deployed AND the request
    #    proves it came through our profile. Front Door overwrites X-Azure-FDID
    #    with its own profile GUID on every request, so a match means the
    #    request traversed our Front Door and X-Azure-ClientIP is its reading of
    #    the true client. Unset FRONT_DOOR_ID (today's state) skips this
    #    entirely rather than trusting a forgeable header.
    expected_fdid = (settings.FRONT_DOOR_ID or "").strip()
    if expected_fdid and headers.get("x-azure-fdid", "").strip() == expected_fdid:
        fd_ip = _parse_ip(headers.get("x-azure-clientip"))
        if fd_ip:
            return fd_ip

    # 2. The contract with our own website proxy. `app/api/contact/route.ts`
    #    resolves the client IP at the true edge and sends it as X-Client-IP,
    #    building the outbound header set explicitly -- it never forwards a
    #    client-supplied X-Client-IP, so this cannot be set by the browser.
    #    This has to outrank X-Forwarded-For below, because on that hop the
    #    platform-appended rightmost XFF entry is the website's own pod IP,
    #    which would collapse every website visitor into one shared bucket.
    proxy_ip = _parse_ip(headers.get("x-client-ip"))
    if proxy_ip:
        return proxy_ip

    # 3. Rightmost X-Forwarded-For entry -- the hop the platform observed.
    forwarded = headers.get("x-forwarded-for")
    if forwarded:
        for candidate in reversed(forwarded.split(",")):
            parsed = _parse_ip(candidate)
            if parsed:
                return parsed

    # 4. The socket peer. X-Real-IP is deliberately NOT consulted: nothing in
    #    our path sets it that does not also set one of the above, and it is
    #    trivially forgeable, so honouring it would just reopen the bypass.
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


# ---------------------------------------------------------------------------
# Rate limiting for public contact inquiries (BE Gap 249)
# ---------------------------------------------------------------------------

_RATE_LIMIT_MAX_REQUESTS = 5
_RATE_LIMIT_WINDOW_SECONDS = 300
_REDIS_KEY_PREFIX = "support:contact:ratelimit:"
# Ceiling on distinct keys held by the in-process fallback. Only reached if
# Redis is down *and* something is rotating keys; at that point the oldest
# entries are dropped, which can forgive an in-flight attacker but can never
# grow memory without bound. 10k keys of a few floats each is well under a MiB.
_MEMORY_MAX_TRACKED_KEYS = 10_000


class _ContactRateLimiter:
    """
    Sliding-window rate limiter for public contact submissions, keyed on both
    origin IP and submitter email.

    Backed by Redis so the window is shared across all backend replicas (the
    app scales to `maxReplicas: 5`). Redis entries carry a TTL equal to the
    window, so the keyspace bounds itself.

    Falls back to an in-process store when Redis is unreachable, following the
    same degrade-don't-fail pattern as services/trainer_sessions.py::_get_redis.
    The fallback is bounded two ways -- stale keys are pruned on every check,
    and the total key count is capped -- so losing Redis cannot turn this
    endpoint into a memory-exhaustion vector.

    Caveat, deliberate and documented: while running on the fallback the window
    is per-replica, so the effective platform-wide limit is up to
    replica_count x `_RATE_LIMIT_MAX_REQUESTS`. That is a degraded mode only;
    the normal Redis path is genuinely global.
    """

    def __init__(self):
        # OrderedDict, not defaultdict: eviction needs insertion/refresh order,
        # and defaultdict's __getitem__ silently created a permanent entry for
        # every key ever *looked at*, including ones that were then rejected.
        self._memory: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = Lock()
        # None = not yet attempted, False = known unavailable, else a client.
        self._redis_client: Any = None

    # -- Redis plumbing -----------------------------------------------------

    def _redis(self):
        """Return a live Redis client, or None to signal fallback mode."""
        if self._redis_client is None:
            try:
                import redis

                client = redis.Redis.from_url(
                    get_settings().REDIS_URL, decode_responses=True
                )
                client.ping()
                self._redis_client = client
            except Exception as exc:
                logger.warning(
                    "support/contact rate limiter: Redis unavailable (%s); "
                    "falling back to a bounded per-replica in-process window.",
                    exc,
                )
                self._redis_client = False
        return self._redis_client or None

    @staticmethod
    def _keys(ip: str, email: str) -> list[str]:
        return [f"ip:{ip}", f"email:{email.lower().strip()}"]

    def _check_redis(self, client, keys, max_requests, window_seconds) -> bool:
        now = time.time()
        cutoff = now - window_seconds
        full_keys = [f"{_REDIS_KEY_PREFIX}{k}" for k in keys]

        # One round trip to drop expired members and read both counts.
        pipe = client.pipeline()
        for key in full_keys:
            pipe.zremrangebyscore(key, 0, cutoff)
            pipe.zcard(key)
        counts = pipe.execute()[1::2]

        if any(int(count) >= max_requests for count in counts):
            return False

        # Record the attempt against both dimensions. EXPIRE on every write
        # keeps idle keys from lingering, so the keyspace stays bounded.
        member = f"{now}:{secrets.token_hex(4)}"
        pipe = client.pipeline()
        for key in full_keys:
            pipe.zadd(key, {member: now})
            pipe.expire(key, window_seconds)
        pipe.execute()
        return True

    # -- Bounded in-process fallback ---------------------------------------

    def _prune_locked(self, cutoff: float) -> None:
        """Drop keys with no timestamps left inside the window."""
        stale = [k for k, stamps in self._memory.items() if not any(t > cutoff for t in stamps)]
        for key in stale:
            del self._memory[key]

    def _check_memory(self, keys, max_requests, window_seconds) -> bool:
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            self._prune_locked(cutoff)

            for key in keys:
                live = [t for t in self._memory.get(key, []) if t > cutoff]
                if len(live) >= max_requests:
                    self._memory[key] = live
                    return False

            for key in keys:
                live = [t for t in self._memory.get(key, []) if t > cutoff]
                live.append(now)
                self._memory[key] = live
                self._memory.move_to_end(key)

            # Hard ceiling, evicting least-recently-touched first.
            while len(self._memory) > _MEMORY_MAX_TRACKED_KEYS:
                self._memory.popitem(last=False)
            return True

    # -- Public API ---------------------------------------------------------

    def check(
        self,
        ip: str,
        email: str,
        max_requests: int = _RATE_LIMIT_MAX_REQUESTS,
        window_seconds: int = _RATE_LIMIT_WINDOW_SECONDS,
    ) -> bool:
        """True if this submission is allowed (and it is then recorded)."""
        keys = self._keys(ip, email)
        client = self._redis()
        if client is not None:
            try:
                return self._check_redis(client, keys, max_requests, window_seconds)
            except Exception as exc:
                # A mid-flight Redis failure must not 500 the contact form, and
                # must not fail *open* either -- degrade to the local window.
                logger.warning(
                    "support/contact rate limiter: Redis check failed (%s); "
                    "degrading to the in-process window for this request.",
                    exc,
                )
                self._redis_client = False
        return self._check_memory(keys, max_requests, window_seconds)

    def reset(self):
        """Clear all rate limit state, both tiers (used by the test suite)."""
        with self._lock:
            self._memory.clear()
        client = self._redis()
        if client is None:
            return
        try:
            stale = list(client.scan_iter(match=f"{_REDIS_KEY_PREFIX}*", count=500))
            if stale:
                client.delete(*stale)
        except Exception as exc:
            logger.warning("support/contact rate limiter: Redis reset failed (%s).", exc)


_rate_limiter = _ContactRateLimiter()


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

# Mirrors SupportTicket.subject's Field(max_length=255) in models.py. Every
# subject written to the table is capped against this; keep the two in step.
_SUBJECT_MAX_LENGTH = 255

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
        return v[:_SUBJECT_MAX_LENGTH]

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

    # Truncated at construction, not by capping `name`'s validator: the overflow
    # comes from prefix + name, and `name` alone is within its own limit.
    # `SupportTicket.subject` is Field(max_length=255) (models.py), so on real
    # Postgres an over-length value is a StringDataRightTruncation -> uncaught
    # 500; the category prefix adds 31-41 chars on top of a name that may
    # legitimately be the full 255. Truncating here is deliberately the last
    # step before persistence so a future change to the prefix format cannot
    # silently reintroduce the overflow. (The in-memory SQLite the tests run on
    # does not enforce max_length, which is why this was invisible -- the test
    # for it asserts on the stored string's length directly.)
    subject = f"[{body.category}] Contact inquiry from {body.name}"[:_SUBJECT_MAX_LENGTH]
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
