"""Gap 124 items 5–7: authenticity, size cap and drop-recording for the
SendGrid Inbound Parse webhook (`POST /api/v1/email/mailintegration`).

Why this is a separate module rather than helpers inside
`routers/email_ingestion.py`: that router is mostly tenant-scoped, Clerk-authed
CRUD over `tenant_email_senders`. The mailintegration webhook is the one
endpoint in the app with **no** authenticated caller at all — SendGrid has no
Clerk session — so its authorization story is entirely different from every
other route's, and keeping it in one file makes it reviewable on its own.

### Authenticity (item 5)

SendGrid Inbound Parse offers no request signing: the only thing configurable
in its dashboard is the Destination URL. There is no equivalent of the
`X-Twilio-Email-Event-Webhook-Signature` header that SendGrid's *Event* webhook
sends — Inbound Parse simply POSTs multipart/form-data. So the shared secret has
to travel in the URL, and `presented_inbound_secret` accepts the three shapes
that URL can take:

  1. `X-Inbound-Secret: <secret>` — used by anything we control (the
     invoice-website relay forwards it verbatim, and tests use it);
  2. `?key=<secret>` / `?secret=<secret>` — what a SendGrid Destination URL can
     actually carry;
  3. `https://sendgrid:<secret>@host/...` — Basic credentials in the
     Destination URL, which SendGrid also supports; only the password half is
     compared, the username is ignored.

Comparison is `hmac.compare_digest`, so a wrong-but-same-length secret cannot be
recovered by timing the response.

This is a shared *bearer* secret, not a signature — it proves the caller knows a
value we configured, not that SendGrid produced the body. That is the strongest
guarantee Inbound Parse makes available, and it is strictly better than the
previous state (anything that could reach the relay was accepted). The BE's own
ingress is `external: false`, so the reachable surface is the website relay
alone.

### Size cap (item 7)

`MAX_INBOUND_BYTES` (settings.INBOUND_EMAIL_MAX_BYTES, 25 MiB) is checked twice:

  * `oversize_from_content_length` reads the declared `Content-Length` *before*
    the body is touched. This is the check that matters — Starlette spools a
    multipart body to a temp file while parsing, so a body only rejected after
    `request.form()` has already cost disk. SendGrid always sends
    Content-Length (Inbound Parse is not chunked), so in practice this is the
    path every real oversized POST takes.
  * the router additionally sums the bytes it actually read from the parsed
    attachments, which covers a request that arrives with no Content-Length at
    all (a hand-rolled or chunked client).

### Drop recording (item 6)

`record_dropped_email` is the single writer for `DroppedInboundEmail`. Every
early return in the webhook goes through it, so "the mail vanished" is no longer
a reachable state — there is always a row, and `GET /api/v1/admin/dropped-emails`
renders it.
"""
import hmac
import logging
from base64 import b64decode
from binascii import Error as BinasciiError
from typing import Optional
from uuid import UUID, uuid4

from sqlmodel import Session
from starlette.requests import Request

from config import get_settings
from models import DroppedInboundEmail

logger = logging.getLogger(__name__)


# --- Drop reasons ----------------------------------------------------------
# Stored verbatim in DroppedInboundEmail.reason and rendered by the Admin
# console, so they are a stable vocabulary rather than free text.

REASON_SECRET_UNCONFIGURED = "secret_unconfigured"
REASON_UNVERIFIED_SECRET = "unverified_secret"
REASON_OVERSIZED = "oversized"
REASON_MALFORMED = "malformed"
REASON_UNKNOWN_SENDER = "unknown_sender"
REASON_MISSING_TENANT = "missing_tenant"
REASON_NO_PDF_ATTACHMENT = "no_pdf_attachment"
REASON_QUOTA_EXHAUSTED = "quota_exhausted"
REASON_INGEST_REJECTED = "ingest_rejected"
REASON_INGEST_FAILED = "ingest_failed"

DROP_REASONS = (
    REASON_SECRET_UNCONFIGURED,
    REASON_UNVERIFIED_SECRET,
    REASON_OVERSIZED,
    REASON_MALFORMED,
    REASON_UNKNOWN_SENDER,
    REASON_MISSING_TENANT,
    REASON_NO_PDF_ATTACHMENT,
    REASON_QUOTA_EXHAUSTED,
    REASON_INGEST_REJECTED,
    REASON_INGEST_FAILED,
)

# Header and query-parameter names the shared secret may arrive under.
SECRET_HEADERS = ("x-inbound-secret", "x-sendgrid-inbound-secret")
SECRET_QUERY_PARAMS = ("key", "secret")


def max_inbound_bytes() -> int:
    return int(get_settings().INBOUND_EMAIL_MAX_BYTES)


def presented_inbound_secret(request: Request) -> Optional[str]:
    """Pull the caller-supplied shared secret out of a request, or None.

    Checked in order: dedicated header, query parameter, Basic-auth password.
    Returns None when the request carries no secret in any of those places,
    which `verify_inbound_secret` treats exactly like a wrong one.
    """
    for header in SECRET_HEADERS:
        value = request.headers.get(header)
        if value:
            return value.strip()

    for param in SECRET_QUERY_PARAMS:
        value = request.query_params.get(param)
        if value:
            return value.strip()

    authorization = request.headers.get("authorization") or ""
    scheme, _, encoded = authorization.partition(" ")
    if scheme.lower() == "basic" and encoded:
        try:
            decoded = b64decode(encoded.strip(), validate=True).decode("utf-8", "replace")
        except (BinasciiError, ValueError):
            return None
        # Only the password half is the secret; the username is free-form
        # (SendGrid's UI requires *something* there).
        _, sep, password = decoded.partition(":")
        if sep and password:
            return password.strip()

    return None


def verify_inbound_secret(request: Request) -> tuple[bool, str]:
    """Return (ok, reason). `reason` is a DROP_REASONS value when ok is False.

    Fail-closed on an unconfigured secret: an empty
    `INBOUND_PARSE_SHARED_SECRET` authenticates nothing, so it rejects rather
    than waves the request through. The two failure reasons are kept distinct
    because they need opposite responses from an operator — one is "seed the
    Key Vault secret", the other is "someone is calling this endpoint with the
    wrong credentials".
    """
    expected = (get_settings().INBOUND_PARSE_SHARED_SECRET or "").strip()
    if not expected:
        return False, REASON_SECRET_UNCONFIGURED

    presented = presented_inbound_secret(request)
    if not presented:
        return False, REASON_UNVERIFIED_SECRET

    if not hmac.compare_digest(presented, expected):
        return False, REASON_UNVERIFIED_SECRET

    return True, ""


def declared_content_length(request: Request) -> Optional[int]:
    """The request's Content-Length as an int, or None if absent/unparseable."""
    raw = request.headers.get("content-length")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def oversize_from_content_length(request: Request) -> Optional[int]:
    """Declared body size when it exceeds the cap, else None.

    Returning the size rather than a bool so the caller can record and report
    the actual number the client claimed to be sending.
    """
    declared = declared_content_length(request)
    if declared is not None and declared > max_inbound_bytes():
        return declared
    return None


def sender_domain_of(email: Optional[str]) -> Optional[str]:
    """Lowercased domain half of an address, or None when there isn't one."""
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].strip().lower()
    return domain or None


def describe_client(request: Request) -> str:
    """Short, log-safe description of who sent a rejected request."""
    host = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        # The website relay is the immediate peer for every real inbound POST,
        # so the originating address is only ever visible here.
        return f"{host} (x-forwarded-for: {forwarded.split(',')[0].strip()})"
    return host


def record_dropped_email(
    db_session: Session,
    *,
    reason: str,
    detail: str = "",
    tenant_id: Optional[UUID] = None,
    from_email: Optional[str] = None,
    to_email: Optional[str] = None,
    filename: Optional[str] = None,
    content_length: Optional[int] = None,
) -> Optional[DroppedInboundEmail]:
    """Persist one dropped/rejected inbound mail. Never raises.

    Called from the webhook's rejection paths, including ones that are already
    handling a failure — so a problem writing the record must not replace the
    original error with a 500. A failure here is logged and swallowed; the
    caller's own rejection still stands.
    """
    record = DroppedInboundEmail(
        id=uuid4(),
        tenant_id=tenant_id,
        reason=reason,
        detail=(detail or "")[:1024],
        from_email=(from_email or None) and from_email[:320],
        to_email=(to_email or None) and to_email[:320],
        sender_domain=sender_domain_of(from_email),
        filename=(filename or None) and filename[:512],
        content_length=content_length,
    )
    try:
        db_session.add(record)
        db_session.commit()
        db_session.refresh(record)
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Could not record dropped inbound email (%s): %s", reason, exc)
        try:
            db_session.rollback()
        except Exception:
            pass
        return None

    logger.warning(
        "Dropped inbound email — reason=%s from=%s to=%s detail=%s",
        reason, from_email, to_email, detail,
    )
    return record
