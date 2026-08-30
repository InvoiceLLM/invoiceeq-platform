"""
Feature 25 (Gap 340): the sandbox `inv_test_` key endpoints.

POST /api/v1/sandbox/keys
    **Public and unauthenticated.** Issues a sandbox key and the fresh, real
    Tenant row behind it. Rate-limited per IP and capped globally.

GET  /api/v1/sandbox/keys/me
    Authenticated BY the sandbox key. Reports what is left -- expiry, chat
    messages, invoice allowance -- so the marketing site can render a countdown
    instead of the visitor discovering the limits by hitting them.

POST /api/v1/sandbox/claim
    Authenticated by a **Clerk session** (the same dependency
    `POST /auth/provision` uses) and additionally requires possession of the
    sandbox key. Promotes the sandbox workspace into the caller's real one.

WHY THIS IS ITS OWN ROUTER
--------------------------
Gap 336's precedent says not to add a router for two endpoints, and that was
right for workflow settings -- they belonged on the Settings surface they were
configuring. This is the opposite case:

* `POST /sandbox/keys` is one of only two unauthenticated endpoints in the whole
  product (the other is the website contact form), and an unauthenticated
  endpoint hidden inside `routers/auth.py` -- the single most incident-prone
  module in this codebase, per Gaps 133/157/173 -- is not where it belongs;
* the security review's constraint is that claiming must NOT be a side effect of
  `provision_tenant()`'s adoption logic, and keeping it in a different file is
  the cheapest way to make that stay true;
* everything here is gated on `SANDBOX_KEYS_ENABLED`, which is a property of
  this whole surface rather than of individual handlers.
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlmodel import Session

from config import get_settings
from dependencies import (
    AuthenticatedClerkIdentity,
    TenantContext,
    get_api_key_context,
    get_authenticated_clerk_identity,
    get_db_session,
)
from models import Tenant
from services.api_keys import generate_sandbox_key, looks_like_sandbox_key
from services.sandbox import (
    SandboxClaimError,
    claim_sandbox_tenant,
    is_sandbox_tenant,
    issue_sandbox_tenant,
    sandbox_is_expired,
)
# Gap 340 requirement 5: REUSE the contact form's limiter rather than writing a
# second one. The hard part it already solves is not the sliding window, it is
# `_get_client_ip()`'s answer to "which IP claim can this platform trust" --
# X-Azure-FDID-verified Front Door header, then our own website proxy's
# X-Client-IP, then the *rightmost* X-Forwarded-For entry (the one Envoy
# appended), then the socket peer. A second implementation would have been a
# second, drifting answer to that question, and BE Gap 249 is the record of what
# getting it wrong costs. The private names are imported deliberately: this is
# reuse of a specific vetted implementation, not of a general utility.
from routers.support import _ContactRateLimiter, _get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sandbox", tags=["Sandbox"])

# Its own Redis keyspace, so a visitor's contact-form submissions and their
# sandbox requests do not consume each other's window (both key on `ip:<addr>`).
_SANDBOX_RATE_LIMIT_KEY_PREFIX = "sandbox:issue:ratelimit:"
_rate_limiter = _ContactRateLimiter(redis_key_prefix=_SANDBOX_RATE_LIMIT_KEY_PREFIX)


def _require_sandbox_enabled() -> None:
    """404 the whole surface when `SANDBOX_KEYS_ENABLED` is off.

    404 rather than 403: a deployment that has not opted in should look like one
    that does not have the feature, not like one that has it and is refusing.
    The setting defaults to False for the same fail-closed reason
    `ALLOW_MOCK_AUTH` does -- a deployment that has not thought about the abuse
    surface must not be handing credentials to strangers.
    """
    if not get_settings().SANDBOX_KEYS_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found.")


class SandboxKeyResponse(BaseModel):
    """The one and only response that carries a raw sandbox key.

    Same shown-once contract as `ApiKeyRotateResponse` and
    `TenantProvisionResponse.api_key` -- it is hashed on the way in, never
    stored in plaintext and never logged.
    """
    api_key: str
    tenant_id: str
    expires_at: datetime
    chat_message_limit: int
    invoice_limit: int
    # Spelled out in the response rather than left to documentation: whoever is
    # integrating the "try it" button should not have to look up why approve/send
    # 403s on this credential.
    scope: str = "readonly"
    note: str = (
        "Sandbox workspace. Read/upload only, expires automatically, and can be "
        "claimed by a real signup to keep everything in it."
    )


class SandboxStatusResponse(BaseModel):
    tenant_id: str
    expires_at: datetime
    expired: bool
    claimed: bool
    chat_messages_used: int
    chat_message_limit: int
    invoices_remaining: int


class SandboxClaimRequest(BaseModel):
    """Body for POST /sandbox/claim.

    `sandbox_key` proves possession of the workspace being claimed -- that is
    what makes this an explicit claim on one specific workspace rather than the
    heuristic guess `provision_tenant()`'s domain-adoption branch makes.

    `clerk_org_id` and `clerk_user_id` are checked against the caller's own
    verified token claims, exactly as `POST /auth/provision` does (Gap 133
    Checkpoint 3c) -- they are not trusted from the body.
    """
    sandbox_key: str
    clerk_org_id: str
    org_name: str
    clerk_user_id: str


class SandboxClaimResponse(BaseModel):
    tenant_id: str
    clerk_org_id: str
    org_name: str
    billing_plan: str
    free_invoices_remaining: int
    # The replacement production key, minted in the same transaction that
    # revoked the `inv_test_` one. Shown once, same contract as everywhere else.
    api_key: str


@router.post(
    "/keys",
    response_model=SandboxKeyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a sandbox API key (public, no login)",
)
def issue_sandbox_key(
    request: Request,
    db_session: Session = Depends(get_db_session),
):
    """Hand an anonymous visitor a sandbox key and a real workspace to use it on.

    THIS ENDPOINT IS UNAUTHENTICATED, which is the whole point and also the whole
    risk. Three controls, in the order they run:

    1. **Feature flag** -- off by default, see `_require_sandbox_enabled()`.
    2. **Per-IP rate limit**, through the same Redis-backed sliding window and
       the same trusted-IP resolution the public contact form uses. Answering
       429 here rather than issuing is what stops one client minting workspaces
       in a loop.
    3. **Global unclaimed cap**, checked under a Postgres advisory lock inside
       `issue_sandbox_tenant()` and **failing closed**: past the cap this returns
       503 "temporarily unavailable" rather than creating another tenant. A
       rate limit bounds one client; only a global cap bounds a botnet.

    What it creates is documented in `services/sandbox.py` -- in particular it
    creates NO `User` row and NO `TenantEmailSender` row, because both of those
    tables have globally unique email columns that an anonymous visitor must not
    be able to squat.
    """
    _require_sandbox_enabled()
    settings = get_settings()

    client_ip = _get_client_ip(request)
    if not _rate_limiter.check(
        client_ip,
        max_requests=settings.SANDBOX_ISSUE_RATE_LIMIT,
        window_seconds=settings.SANDBOX_ISSUE_RATE_WINDOW_SECONDS,
    ):
        logger.warning("sandbox: issuance rate limit exceeded for ip=%s", client_ip)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Too many sandbox workspaces requested from this address. Try "
                "again later, or sign up for a free workspace."
            ),
            headers={"Retry-After": str(settings.SANDBOX_ISSUE_RATE_WINDOW_SECONDS)},
        )

    raw_key = generate_sandbox_key()
    issued = issue_sandbox_tenant(db_session, raw_key, issued_from_ip=client_ip)
    if issued is None:
        # Fail closed at the cap. 503 + Retry-After, not 500: nothing is broken,
        # there is simply no capacity for another throwaway workspace right now.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Sandbox workspaces are temporarily unavailable. Please try again "
                "later, or sign up for a free workspace."
            ),
            headers={"Retry-After": "600"},
        )

    tenant, sandbox = issued
    return SandboxKeyResponse(
        api_key=raw_key,
        tenant_id=str(tenant.id),
        expires_at=sandbox.expires_at,
        chat_message_limit=settings.SANDBOX_CHAT_MESSAGE_LIMIT,
        invoice_limit=settings.SANDBOX_INVOICE_LIMIT,
    )


@router.get(
    "/keys/me",
    response_model=SandboxStatusResponse,
    summary="What is left on this sandbox key (authenticated by the key itself)",
)
def get_sandbox_status(
    context: TenantContext = Depends(get_api_key_context),
    db_session: Session = Depends(get_db_session),
):
    """Report the sandbox's remaining allowances.

    Authenticated by `get_api_key_context` -- the key-ONLY dependency, the same
    one `GET /settings/security/api-key/verify` uses -- so a browser session
    cannot read it. An `inv_live_` key belonging to an ordinary tenant
    authenticates fine and then gets a 404, because there is nothing here to
    report for a workspace that is not a sandbox; that is a real answer, not an
    error condition, and it keeps this endpoint from becoming a second identity
    echo.
    """
    _require_sandbox_enabled()

    sandbox = is_sandbox_tenant(db_session, context.tenant_id)
    if sandbox is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This workspace is not a sandbox.",
        )

    tenant = db_session.get(Tenant, context.tenant_id)
    settings = get_settings()
    return SandboxStatusResponse(
        tenant_id=str(context.tenant_id),
        expires_at=sandbox.expires_at,
        expired=sandbox_is_expired(sandbox),
        claimed=sandbox.claimed_at is not None,
        chat_messages_used=sandbox.chat_messages_used,
        chat_message_limit=settings.SANDBOX_CHAT_MESSAGE_LIMIT,
        invoices_remaining=tenant.free_invoices_remaining if tenant else 0,
    )


@router.post(
    "/claim",
    response_model=SandboxClaimResponse,
    summary="Promote a sandbox workspace into this organisation's real one",
)
def claim_sandbox(
    body: SandboxClaimRequest,
    caller: AuthenticatedClerkIdentity = Depends(get_authenticated_clerk_identity),
    db_session: Session = Depends(get_db_session),
):
    """Claim the sandbox workspace named by `sandbox_key` for the caller's org.

    This is the deliberate alternative to letting a sandbox tenant fall into
    `provision_tenant()`'s domain-adoption branch. That branch is a heuristic --
    it guesses that an empty domain-matched tenant probably belongs to whoever
    is signing up -- and Gaps 133 and 344 are both records of that guess being
    dangerous. A sandbox claim is not a guess: the caller is presenting the
    sandbox key, which is possession of one specific workspace.

    THE THREE THINGS THIS CHECKS, in order:

    1. **Who the caller is.** `clerk_user_id` must equal the token's `sub` and
       `clerk_org_id` must equal the token's active `org_id` -- byte-for-byte
       the same two bindings `provision_tenant()` applies (Gap 133 Checkpoint
       3c), for the same reason: without them any signed-in user could claim a
       sandbox into somebody else's organisation.
    2. **Possession of the sandbox.** The raw key must verify against a tenant
       that actually has a sandbox row. A key for an ordinary tenant is refused
       here rather than being allowed to promote a real workspace into a
       different org, which would be a takeover.
    3. **That the sandbox is still claimable** -- unclaimed and unexpired,
       decided atomically under an advisory lock inside
       `claim_sandbox_tenant()`.

    The `inv_test_` key is revoked and replaced with a fresh `inv_live_` key in
    the same transaction that attaches the Clerk org, so there is never a moment
    when both the stranger's sandbox key and the new owner's access are live.
    """
    _require_sandbox_enabled()

    if not caller.is_mock:
        if caller.clerk_user_id != body.clerk_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "The authenticated user does not match clerk_user_id in the "
                    "request body."
                ),
            )
        if caller.org_id != body.clerk_org_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "The authenticated session's active organisation does not match "
                    "clerk_org_id in the request body. A sandbox can only be claimed "
                    "for the organisation the caller is actually signed in to."
                ),
            )

    raw_key = (body.sandbox_key or "").strip()
    if not looks_like_sandbox_key(raw_key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="sandbox_key must be a sandbox key (inv_test_...).",
        )

    # Resolve the key through the ordinary key path so verification is the same
    # constant-time digest comparison as everywhere else -- no second verifier.
    # It also means an expired sandbox key 401s here exactly as it would on any
    # other endpoint, from the one place that decides expiry.
    from dependencies import resolve_api_key_context

    key_context = resolve_api_key_context(raw_key, db_session)

    sandbox = is_sandbox_tenant(db_session, key_context.tenant_id)
    if sandbox is None:
        # An `inv_test_`-prefixed key that resolves to a non-sandbox tenant
        # should not exist, but refusing is the only safe answer if it ever does.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="That key does not belong to a sandbox workspace.",
        )

    try:
        tenant, raw_live_key = claim_sandbox_tenant(
            db_session,
            sandbox,
            clerk_org_id=body.clerk_org_id,
            org_name=body.org_name,
        )
    except SandboxClaimError as exc:
        # `expired` is a 410 (the resource is genuinely gone), the other two are
        # 409 (a conflict with someone else's completed action). Both are
        # actionable by the caller in different ways, so they do not share a code.
        status_code = (
            status.HTTP_410_GONE
            if exc.code == "expired"
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=status_code, detail=exc.message) from exc

    return SandboxClaimResponse(
        tenant_id=str(tenant.id),
        clerk_org_id=tenant.clerk_org_id,
        org_name=tenant.name,
        billing_plan=tenant.billing_plan,
        free_invoices_remaining=tenant.free_invoices_remaining,
        api_key=raw_live_key,
    )
