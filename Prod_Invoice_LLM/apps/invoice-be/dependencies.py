import httpx
import jwt
import logging
from jwt.algorithms import RSAAlgorithm
from uuid import UUID
from typing import Generator
from fastapi import Header, HTTPException, status, Depends
from pydantic import BaseModel
from sqlmodel import Session, select
import time
from datetime import datetime

from config import settings

logger = logging.getLogger(__name__)
from database import engine
from models import Tenant, User, RoleMapper
from services.billing_lifecycle import enforce_lapse, refresh_free_quota

class TenantContext(BaseModel):
    tenant_id: UUID
    user_id: str
    db_user_id: UUID | None = None
    role: str
    billing_plan: str
    # Gap 133: the display name of the tenant the backend ACTUALLY resolved.
    # The FE used to render Clerk's `unsafeMetadata.orgName` (written at
    # sign-up, never reconciled with the backend), so a user whose org failed
    # to provision saw the org name they signed up with while their data lived
    # somewhere else entirely -- the mismatch was invisible. Populated from the
    # Tenant row this request already loaded, so it costs no extra query.
    tenant_name: str | None = None
    # Feature 1.1 (Task 1.1.3): per-area permissions, resolved from the User
    # row rather than the JWT -- permissions are our data, not Clerk's, so an
    # Admin's grant takes effect on the very next request without waiting for
    # a token refresh. Admin implies all three (see resolve_permissions).
    # GET /auth/me returns this model verbatim, so the FE gets them for free.
    can_train: bool = False
    can_audit: bool = False
    can_load: bool = False
    # Feature 25 (Gap 335): which door this request came through -- "clerk" for a
    # browser session, "api_key" for an `inv_live_...` credential.
    #
    # Gap 184 deliberately made these indistinguishable ("downstream handlers
    # cannot tell (or need to tell) which door a request came through"), which
    # was right while a key could only echo its own identity. Once a key can
    # approve, send and mark-paid an invoice it stops being right: "who did
    # this" is an audit question, and "a machine, via key inv_live_ab12cd" is a
    # materially different answer from "Priya, in a browser".
    #
    # `key_scope` is the Tenant.api_key_scope the request resolved at, or None
    # on the Clerk path. Carried explicitly rather than inferred back out of the
    # permission booleans so require_key_scope() reads as what it is.
    #
    # Both default to the Clerk values, so every existing TenantContext(...)
    # construction site is unaffected. Both surface in GET /auth/me, which
    # returns this model verbatim (routers/auth.py, response_model=TenantContext)
    # -- purely additive there.
    auth_method: str = "clerk"
    key_scope: str | None = None

# Cache for Clerk JWKS keys
_jwks_cache = {}

MOCK_TENANT_ID = UUID("00000000-0000-0000-0000-000000000000")
MOCK_USER_ID = "user_test_default"
MOCK_ROLE = "Admin"
MOCK_BILLING_PLAN = "active"

def get_db_session() -> Generator[Session, None, None]:
    """FastAPI dependency to yield a database session."""
    with Session(engine) as session:
        yield session

def require_clerk_jwt_config() -> None:
    """
    Gap 4 (fail closed): refuse to verify a token unless BOTH Clerk JWT settings
    are present.

    Previously an empty CLERK_JWT_ISSUER made `verify_iss` evaluate to False, so
    a correctly signed token from ANY Clerk instance was accepted. Treating
    incomplete config as a hard 500 means a misconfigured deployment denies
    every request instead of silently widening who it trusts.
    """
    missing = [
        name
        for name, value in (
            ("CLERK_JWKS_URL", settings.CLERK_JWKS_URL),
            ("CLERK_JWT_ISSUER", settings.CLERK_JWT_ISSUER),
        )
        if not value
    ]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Authentication is misconfigured: "
                f"{', '.join(missing)} not set. Refusing to verify tokens."
            ),
        )


def get_jwk(kid: str) -> dict:
    """Fetch public keys dynamically from the configured JWKS URL."""
    global _jwks_cache
    if kid in _jwks_cache:
        return _jwks_cache[kid]
    
    if not settings.CLERK_JWKS_URL:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CLERK_JWKS_URL is not configured in settings."
        )
    
    try:
        response = httpx.get(settings.CLERK_JWKS_URL, timeout=5.0)
        response.raise_for_status()
        jwks = response.json()
        for key in jwks.get("keys", []):
            _jwks_cache[key["kid"]] = key
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch JWKS from identity provider: {str(e)}"
        )
    
    if kid not in _jwks_cache:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token key ID (kid)."
        )
    
    return _jwks_cache[kid]

def verify_clerk_jwt(token: str) -> dict:
    """
    Verify a real Clerk session token and return its claims.

    Extracted from get_tenant_context_allow_unpaid() by Gap 133 so that
    POST /auth/provision can authenticate its caller with exactly the same
    verification (issuer pinned, signature checked against the live JWKS,
    fail-closed on incomplete config) instead of running unauthenticated. The
    body is unchanged from the inline version it replaces, diagnostics included.
    """
    # Gap 4: fail closed before touching the token -- incomplete config
    # must never soften verification (see require_clerk_jwt_config).
    require_clerk_jwt_config()
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        # Diagnostic logging, kept intentionally for future auth-issue debugging: unverified claims are
        # safe to log (no signature/secret exposure) and show exactly
        # what the token claims before we judge whether it's valid.
        # print(), not logger.warning() -- confirmed live that this
        # container's log stream only captures stdout (uvicorn's own
        # access-log lines), not Python logging module output.
        try:
            unverified = jwt.decode(token, options={"verify_signature": False})
            # Gap 133: email_present is here because a missing `email` claim is
            # what produced the synthetic `user_<id>@domain.com` addresses that
            # the (now removed) email-domain fallback then merged on. The
            # fallback is gone, but the claim being absent is still the signal
            # that this deployment's Clerk JWT Template needs checking.
            print(
                f"[jwt-diag] kid={kid} token_iss={unverified.get('iss')!r} "
                f"expected_iss={settings.CLERK_JWT_ISSUER!r} exp={unverified.get('exp')} "
                f"now={int(time.time())} org_id={unverified.get('org_id')!r} "
                f"org_role={unverified.get('org_role')!r} sub={unverified.get('sub')!r} "
                f"email_present={bool(unverified.get('email') or unverified.get('email_address'))}",
                flush=True,
            )
        except Exception as diag_e:
            print(f"[jwt-diag] could not decode unverified claims: {diag_e}", flush=True)
        if not kid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing key ID (kid) in token header."
            )

        jwk_dict = get_jwk(kid)
        public_key = RSAAlgorithm.from_jwk(jwk_dict)

        # Gap 4: issuer verification is now unconditional. It was
        # previously `bool(settings.CLERK_JWT_ISSUER)`, which silently
        # disabled the check whenever the setting was empty.
        # require_clerk_jwt_config() above guarantees it is non-empty.
        # Clerk session JWTs often have iat a second or two in the future vs
        # the local clock; PyJWT default leeway is 0, which 401s Help/dashboard
        # as "The token is not yet valid (iat)". 60s covers skew without
        # stretching expiry in a meaningful way.
        return jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            issuer=settings.CLERK_JWT_ISSUER,
            leeway=60,
            options={"verify_iss": True}
        )
    except jwt.ExpiredSignatureError:
        print("[jwt-diag] ExpiredSignatureError", flush=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token signature has expired."
        )
    except jwt.InvalidTokenError as e:
        print(f"[jwt-diag] InvalidTokenError: {e}", flush=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}"
        )


class AuthenticatedClerkIdentity(BaseModel):
    """
    Gap 133 (Checkpoint 3c): the claims POST /auth/provision is allowed to trust.

    Checkpoint 3b returned only the verified `sub` from this dependency, which
    authenticated *who* was calling but nothing about *what they were allowed to
    claim* -- the caller still supplied `clerk_org_id` and `admin_email` freely
    in the request body. Carrying `org_id` and `email` out of the same verified
    payload is what lets the handler bind both to the token instead.

    `is_mock` is True only on the ALLOW_MOCK_AUTH path (default off), where
    there is no token to bind anything to; the handler treats it exactly as
    every other dependency here treats mock auth.
    """
    clerk_user_id: str | None = None
    org_id: str | None = None
    email: str | None = None
    is_mock: bool = False


def get_authenticated_clerk_identity(
    authorization: str | None = Header(None),
) -> AuthenticatedClerkIdentity:
    """
    Gap 133: authenticate a caller that has no tenant yet.

    POST /auth/provision runs at sign-up, before any Tenant/User row exists, so
    it cannot use get_tenant_context(). It previously took no auth dependency at
    all -- reproduced in Checkpoint 3a: an anonymous caller could POST an
    arbitrary clerk_org_id/org_name and rename or claim an existing tenant.

    Returns the verified `sub`/`org_id`/`email` so the handler can check the
    request body against the token rather than trusting it. Returns
    `is_mock=True` with everything None only on the mock path (ALLOW_MOCK_AUTH,
    default False), which the handler treats as "identity check skipped" the
    same way every other dependency here treats mock auth.

    Checkpoint 3c renamed this from `get_authenticated_clerk_user_id()` (which
    returned the bare `sub`): a name promising only a user id is the reason the
    org/email binding was missed in 3b.
    """
    if not authorization or not authorization.startswith("Bearer "):
        print(f"[jwt-diag] provision header branch: authorization={authorization!r}", flush=True)
        if not settings.ALLOW_MOCK_AUTH:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or malformed Authorization header. Expected 'Bearer <token>'.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return AuthenticatedClerkIdentity(is_mock=True)

    token = authorization.split(" ")[1]

    if token.startswith("test_"):
        if not settings.ALLOW_MOCK_AUTH:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Test tokens are rejected when ALLOW_MOCK_AUTH is disabled.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return AuthenticatedClerkIdentity(is_mock=True)

    payload = verify_clerk_jwt(token)
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token carries no subject (sub) claim.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return AuthenticatedClerkIdentity(
        clerk_user_id=sub,
        org_id=payload.get("org_id"),
        # Same claim pair and precedence as the real-token branch of
        # get_tenant_context_allow_unpaid() below -- deliberately one pattern,
        # not two, so a JWT Template that omits `email` behaves identically in
        # both places.
        email=payload.get("email") or payload.get("email_address"),
        is_mock=False,
    )


def resolve_permissions(role: str, user: User | None) -> tuple[bool, bool, bool]:
    """
    Feature 1.1 (Task 1.1.3) / Gap 73: resolve (can_train, can_audit, can_load).
    Delegates to RoleMapper for enterprise-scale role mapping and fallback permissions.
    """
    return RoleMapper.resolve_permissions(role, user)


def reconcile_role_with_org(
    token_role: str,
    user: User | None,
    tenant: Tenant | None,
    clerk_org_id: str | None,
    is_mock_identity: bool,
) -> str:
    """
    Gap 133 (Checkpoint 3c): the role this request actually runs as.

    Gap 173 already established that `org_role` describes whichever Clerk
    Organization is *active on the session*, and that any signed-in user can
    self-serve create a new org and be made its `org:admin` by Clerk. It also
    already computed `org_matches` -- but only used it to gate *persisting*
    `user.role` to the database. The role handed to `TenantContext` for the
    current request was still taken straight from the token, so the escalation
    the check was written to stop worked anyway: a permission-less user creates a throwaway
    org, switches their active org to it, and every request that session carries
    `org_role=org:admin`. The tenant resolved is still their real one (from
    `user.tenant_id`), so they got Admin `TenantContext` -- and, through
    resolve_permissions(), can_train/can_audit/can_load -- on somebody else's
    workspace. The stored role was correctly left alone the whole time, which is
    precisely why nothing looked wrong.

    So: a token's role claim is only usable when the token's `org_id` is the org
    the resolved tenant is actually tied to. Otherwise fall back to the role we
    persisted for this user (our own data, unforgeable from a browser), and to
    the zero-permission fallback `RoleMapper.NO_ROLE` if there is none.

    Gap 337: that clamp target used to be the literal "Viewer". It is now
    `NO_ROLE` ("Restricted") — an internal, never-assignable value — precisely so
    that retiring "Viewer" from the user-facing vocabulary could not quietly turn
    this clamp into a grant of some real role's permissions.

    Mock/test identities (ALLOW_MOCK_AUTH, default off) are exempt: they have no
    org and no token, and gating them would just disable the whole suite's
    Admin context.
    """
    if is_mock_identity:
        return token_role

    if tenant is not None and tenant.clerk_org_id == clerk_org_id:
        return token_role

    persisted_role = getattr(user, "role", None)
    return RoleMapper.normalize_role(persisted_role) if persisted_role else RoleMapper.NO_ROLE


def get_tenant_context_allow_unpaid(
    authorization: str | None = Header(None),
    db_session: Session = Depends(get_db_session)
) -> TenantContext:
    """
    Decodes and validates the Clerk JWT token.
    Provisions Tenant and User rows in the database if they do not exist.

    Identical to get_tenant_context() except that it does NOT raise 402 for an
    'unpaid' plan -- it only resolves and returns the context. Use this on the
    handful of endpoints a lapsed tenant must still be able to reach: billing
    checkout (the remedy for 402) and GET /auth/me (so the FE can read
    billing_plan and render a "your plan lapsed" state instead of failing
    opaquely). Everything else should depend on get_tenant_context().

    Gap 4: the mock/test fallback is gated behind settings.ALLOW_MOCK_AUTH,
    which defaults False. With it disabled, a missing/malformed header or a
    'test_' token is a 401 -- there is no path that downgrades an
    unauthenticated request to a mock Admin context.
    """
    # 1. Local Development / Test Fallback -- only when explicitly enabled
    if not authorization or not authorization.startswith("Bearer "):
        # Diagnostic logging, kept intentionally for future auth-issue debugging: confirms whether this is the
        # branch actually firing, distinct from a failure further down after a
        # real header IS present. print(), not logger -- see note below.
        print(f"[jwt-diag] header branch: authorization={authorization!r}", flush=True)
        if not settings.ALLOW_MOCK_AUTH:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or malformed Authorization header. Expected 'Bearer <token>'.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        tenant_id = MOCK_TENANT_ID
        user_id = MOCK_USER_ID
        role = MOCK_ROLE
        plan = MOCK_BILLING_PLAN
        email = "test@example.com"
        first_name = "Test"
        last_name = "User"
        clerk_org_id = None
        raw_org_role = None
        # Gap 133: the mock/test identities below have no Clerk org and no real
        # email, so they can never satisfy the org/tenant-claim lookup that real
        # tokens are now required to satisfy. They keep the old auto-provision
        # behaviour (they are the whole point of ALLOW_MOCK_AUTH, which defaults
        # off); only real tokens are gated.
        is_mock_identity = True
        email_is_placeholder = True
    else:
        token = authorization.split(" ")[1]

        # Check for mock test token format (e.g. 'test_', 'test_unpaid')
        if token.startswith("test_"):
            if not settings.ALLOW_MOCK_AUTH:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Test tokens are rejected when ALLOW_MOCK_AUTH is disabled.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            plan = "unpaid" if "unpaid" in token else MOCK_BILLING_PLAN
            # Gap 337: the *token spelling* `test_viewer` is deliberately kept
            # working alongside `test_restricted` -- it is a fixture vocabulary
            # used across the whole suite, not user-facing copy -- but what it
            # resolves to is now the zero-permission fallback, not a role named
            # "Viewer".
            role = (
                RoleMapper.NO_ROLE
                if ("viewer" in token or "restricted" in token)
                else MOCK_ROLE
            )

            tenant_id = MOCK_TENANT_ID
            clerk_org_id = None
            raw_org_role = None
            # Extract UUID if provided in test token
            for part in token.split("_"):
                try:
                    tenant_id = UUID(part)
                except ValueError:
                    continue
            user_id = MOCK_USER_ID
            email = "test@example.com"
            first_name = "Test"
            last_name = "User"
            is_mock_identity = True
            email_is_placeholder = True
        else:
            # 2. Live JWT Decoding & Verification
            # Gap 133: the decode/verify body moved verbatim into
            # verify_clerk_jwt() so POST /auth/provision can authenticate its
            # caller with the identical checks.
            payload = verify_clerk_jwt(token)
            is_mock_identity = False

            # 3. Extract tenant parameters from JWT claims
            # clerk_org_id (e.g. "org_2abc...") is a Clerk-assigned string, not a UUID --
            # kept separate from tenant_id (only ever populated from a custom "tenant_id"
            # claim) so it can't be mistakenly parsed as one.
            clerk_org_id = payload.get("org_id")
            tenant_id = None

            # Gap 133 (Checkpoint 3c), finding 8 -- no functional change, this
            # claim is inert today: the Clerk JWT Template does not emit
            # `tenant_id` at all, so this branch never fires in any deployed
            # environment. It is documented here because the day it IS added it
            # becomes a direct tenant selector, trusted verbatim below (Priority
            # 2 loads whatever tenant it names). If that day comes, it MUST be
            # sourced from Clerk `public_metadata` (backend-writable only) or
            # from an org shortcode -- never from `unsafe_metadata`, which any
            # signed-in user can rewrite on themselves from a browser console
            # via Clerk.user.update(). That is not hypothetical: it is exactly
            # what the `role` claim just below was sourced from, and Gap 173 was
            # opened because it let any user grant themselves Admin.
            tenant_id_str = payload.get("tenant_id")
            if tenant_id_str:
                try:
                    tenant_id = UUID(tenant_id_str)
                except ValueError:
                    pass  # Not a valid UUID, ignore

            user_id = payload.get("sub", MOCK_USER_ID)

            # Gap 173: `org_role` comes from Clerk Organizations and can only be
            # changed via Clerk's own permission-checked API (or the Dashboard) --
            # it's the one trustworthy signal here. `role` is sourced from
            # unsafe_metadata, which any signed-in user can rewrite on themselves
            # via the client SDK (Clerk.user.update()), no backend involved. It
            # used to be checked first, so any user could grant themselves Admin
            # from a browser console. Users with no Clerk org membership at all
            # (everyone added via the Settings "add user" flow -- see admin.py,
            # which never adds them as an org member) have no org_role to fall
            # back on; for them `role` is still read for display-ish labels, but
            # it may never resolve to Admin on its own.
            raw_org_role = payload.get("org_role")
            raw_role = payload.get("role")
            if raw_org_role:
                role = RoleMapper.normalize_role(raw_org_role)
            else:
                role = RoleMapper.normalize_role(raw_role or RoleMapper.NO_ROLE)
                if role == "Admin":
                    role = RoleMapper.NO_ROLE
            plan = payload.get("billing_plan", "free")
            # Gap 133: track at the source whether this is a real email or the
            # synthetic `user_<clerkid>@domain.com` placeholder. The placeholder
            # is what the old Priority-3 email-domain fallback matched on --
            # every user with a missing `email` claim shared the literal domain
            # "domain.com" and so got merged into one unrelated "Domain
            # Workspace" tenant. The fallback is gone (see below), so this is
            # now diagnostic only: it tells us whether the Clerk JWT Template is
            # still failing to emit an `email` claim.
            email_claim = payload.get("email") or payload.get("email_address")
            email_is_placeholder = not email_claim
            email = email_claim or f"{user_id}@domain.com"
            first_name = payload.get("first_name") or payload.get("given_name")
            last_name = payload.get("last_name") or payload.get("family_name")

    # DB Provisioning and Lookup
    user = db_session.exec(select(User).where(User.clerk_user_id == user_id)).first()
    
    if not user:
        domain = email.split("@")[-1]

        tenant = None

        # Priority 1: look up by clerk_org_id (Clerk Organizations flow)
        if clerk_org_id:
            tenant = db_session.exec(
                select(Tenant).where(Tenant.clerk_org_id == clerk_org_id)
            ).first()

        # Priority 2: look up by internal tenant_id UUID (custom JWT template)
        if not tenant and tenant_id:
            tenant = db_session.get(Tenant, tenant_id)

        # Gap 133: there is deliberately no Priority 3 any more. It used to look
        # the tenant up by email domain and, failing that, CREATE one -- which
        # is how a user whose Clerk Organization never provisioned silently
        # ended up inside an unrelated tenant (confirmed live: two unrelated
        # sign-ups both landed in one generic "Domain Workspace" tenant, because
        # their synthetic placeholder emails shared the literal domain
        # "domain.com"). Neither adopting a domain-matched tenant nor
        # auto-creating one at request time is an identity decision this
        # function is entitled to make: provisioning happens once, explicitly,
        # at sign-up via POST /auth/provision. If that did not happen, fail
        # loudly here rather than inventing an answer.
        if not tenant and not is_mock_identity:
            print(
                "[jwt-diag] provision-gate: no tenant for "
                f"sub={user_id!r} org_id={clerk_org_id!r} tenant_id_claim={tenant_id!r} "
                f"email_placeholder={email_is_placeholder}",
                flush=True,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Your account is not linked to a provisioned organisation. "
                    "Sign-up did not finish registering this organisation with the "
                    f"backend (Clerk org id: {clerk_org_id or 'none on this token'}). "
                    "Sign up again and use Retry if provisioning fails, or contact "
                    "support with that org id -- access is refused rather than "
                    "placing your data in an unrelated workspace."
                ),
            )

        if not tenant:
            # Mock/test identities only (ALLOW_MOCK_AUTH, default off).
            if not tenant_id:
                import uuid
                tenant_id = uuid.uuid4()
            tenant = Tenant(
                id=tenant_id,
                name=f"{domain.split('.')[0].title()} Workspace" if "." in domain else "Tenant Account",
                domain=domain,
                clerk_org_id=clerk_org_id,
                billing_plan=plan
            )
            db_session.add(tenant)
            db_session.commit()
            db_session.refresh(tenant)
        else:
            tenant_id = tenant.id
            if clerk_org_id and not tenant.clerk_org_id:
                # Backfill clerk_org_id onto a tenant found via tenant_id/domain
                tenant.clerk_org_id = clerk_org_id
                db_session.add(tenant)
                db_session.commit()
                db_session.refresh(tenant)

        # Gap 133 (Checkpoint 3c): the same rule reconcile_role_with_org()
        # applies to the request's own role, applied here *before* the row is
        # written -- a first-login role claim for an org that is not this
        # tenant's must not be persisted either, or the fallback below would
        # later read back the very value it was meant to distrust. There is no
        # persisted role yet on this path, so a mismatch clamps to the
        # zero-permission fallback (Gap 337: RoleMapper.NO_ROLE, was "Viewer").
        role = reconcile_role_with_org(role, None, tenant, clerk_org_id, is_mock_identity)

        user = User(
            clerk_user_id=user_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            role=role,
            tenant_id=tenant_id,
            last_login=datetime.utcnow()
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
    else:
        user.last_login = datetime.utcnow()

        # Gap 173 (cont'd): org_role is only meaningful for whichever org is
        # currently active on the session -- and any signed-in user can
        # self-serve create-and-activate a brand-new Clerk Organization
        # (Clerk makes its creator that org's org:admin by default, no
        # spoofing involved). That's real, Clerk-issued data, but it says
        # nothing about this user's actual tenant. Without this check, a
        # permission-less user could self-escalate on their real tenant just by switching
        # their active org to a throwaway one they made themselves. Only
        # apply a role change when the token's org_id matches the org this
        # user's tenant is already tied to; a role claim for an unrelated
        # org must never touch this user's role here.
        # Gap 157/173 (cont'd): `clerk_org_id is None` used to count as a match
        # (needed so Settings-added, never-org-member users can still get a
        # role synced at all) -- but that also let a real org member's
        # momentarily stale session cookie (no org_role this request, e.g. a
        # brief window right after Clerk.setActive() before the cookie catches
        # up) fall through this same branch and overwrite their real, correct
        # Admin role with the org-less clamp's fallback role ("Viewer" at the
        # time; RoleMapper.NO_ROLE since Gap 337). Confirmed live: this
        # is what silently demoted an actual Admin's stored role after a
        # normal navigation, well after login, with no error visible anywhere.
        # Fix: only ever sync role from a request that actually carried a real
        # org_role claim. No org_role this request -> leave the stored role
        # untouched, regardless of what `role` clamped down to.
        existing_tenant = db_session.get(Tenant, user.tenant_id) if user.tenant_id else None
        org_matches = existing_tenant is not None and existing_tenant.clerk_org_id == clerk_org_id
        if raw_org_role and org_matches and role and user.role != role:
            user.role = role
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)

        if user.tenant_id:
            tenant_id = user.tenant_id
            tenant = existing_tenant if existing_tenant is not None else db_session.get(Tenant, tenant_id)
            if not tenant:
                tenant = Tenant(
                    id=tenant_id,
                    name="Tenant Account",
                    domain=f"domain-{tenant_id}.com",
                    clerk_org_id=clerk_org_id,
                    billing_plan=plan
                )
                db_session.add(tenant)
                db_session.commit()
                db_session.refresh(tenant)
            elif clerk_org_id and not tenant.clerk_org_id:
                # Backfill clerk_org_id on an existing tenant if missing
                tenant.clerk_org_id = clerk_org_id
                db_session.add(tenant)
                db_session.commit()
                db_session.refresh(tenant)
        else:
            # User has no tenant -- try to find one by clerk_org_id first
            tenant = None
            if clerk_org_id:
                tenant = db_session.exec(
                    select(Tenant).where(Tenant.clerk_org_id == clerk_org_id)
                ).first()

            if not tenant:
                if not tenant_id and is_mock_identity:
                    tenant_id = MOCK_TENANT_ID
                tenant = db_session.get(Tenant, tenant_id) if tenant_id else None

            # Gap 133: same gate as the new-user path above, for the same
            # reason. This branch used to fall through to MOCK_TENANT_ID and
            # then to creating a "Tenant Account" row -- i.e. a real user whose
            # org never provisioned got silently attached to whatever tenant
            # happened to sit on the mock UUID.
            if not tenant and not is_mock_identity:
                print(
                    "[jwt-diag] provision-gate (tenant-less user): "
                    f"sub={user_id!r} org_id={clerk_org_id!r} tenant_id_claim={tenant_id!r} "
                    f"email_placeholder={email_is_placeholder}",
                    flush=True,
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Your account is not linked to a provisioned organisation. "
                        "Sign-up did not finish registering this organisation with the "
                        f"backend (Clerk org id: {clerk_org_id or 'none on this token'}). "
                        "Contact support with that org id -- access is refused rather "
                        "than placing your data in an unrelated workspace."
                    ),
                )

            if not tenant:
                tenant = Tenant(
                    id=tenant_id or MOCK_TENANT_ID,
                    name="Tenant Account",
                    domain=f"domain-{tenant_id}.com",
                    clerk_org_id=clerk_org_id,
                    billing_plan=plan
                )
                db_session.add(tenant)
                db_session.commit()
                db_session.refresh(tenant)

            tenant_id = tenant.id
            user.tenant_id = tenant_id
            db_session.add(user)
            db_session.commit()

    # Gap 133 (Checkpoint 3c): decide the role this request runs as against the
    # tenant that was ACTUALLY resolved above, not against the token alone. The
    # org_matches check further up only ever gated the DB write; without this,
    # an org_role claim from an unrelated (e.g. self-created throwaway) org
    # still produced an Admin TenantContext -- and therefore all three
    # permissions -- on the user's real tenant. See reconcile_role_with_org().
    role = reconcile_role_with_org(role, user, tenant, clerk_org_id, is_mock_identity)

    can_train, can_audit, can_load = resolve_permissions(role, user)

    # Gap 71: lazy lapse check. PayU's classic API has no recurring object and
    # no cancellation webhook, so a lapse can only be inferred from a date --
    # and if nothing ever evaluates that date, the 402 gate below is dead code
    # (which it was, from Feature 11 shipping until now). Doing it here means
    # enforcement needs no new infrastructure and takes effect on the very next
    # request. The cost on this hot path is one datetime comparison against a
    # Tenant row that has already been loaded above; the DB write only happens
    # on the single request that actually crosses the boundary, after which the
    # plan is 'unpaid' and is_lapsed() short-circuits on the plan check.
    # scripts/sweep_billing_lifecycle.py (Gaps 119/121 ACA Job) covers idle
    # tenants who never make a request -- see sweep_lapsed_tenants() /
    # sweep_free_quotas().
    enforce_lapse(tenant, db_session)

    # Gap 118: the free tier's mirror of the same problem, checked in the same
    # place for the same reasons. routers/invoices.py only ever decrements
    # free_invoices_remaining, so the advertised "50 invoices a month" was in
    # practice 50 invoices ever. Doing the refill here rather than at the two
    # upload call sites means the tenant's allowance is already correct
    # whichever door they come in through (upload, directory watcher, or just
    # loading a page that reads the counter), and costs one datetime comparison
    # against the Tenant row this request has already loaded. Deliberately
    # ordered after enforce_lapse(): a tenant demoted to 'unpaid' on this very
    # request must not then be handed a fresh free allowance -- refresh_free_
    # quota() only acts on plan == 'free'. Idle free tenants who never make a
    # request are covered by Gap 121's scheduled sweep_free_quotas().
    refresh_free_quota(tenant, db_session)

    context = TenantContext(
        tenant_id=tenant_id,
        user_id=user_id,
        db_user_id=user.id,
        role=role,
        billing_plan=tenant.billing_plan,
        # Gap 133: from the Tenant row already loaded above -- no extra query.
        tenant_name=tenant.name,
        can_train=can_train,
        can_audit=can_audit,
        can_load=can_load,
    )

    return context


def get_tenant_context(
    context: TenantContext = Depends(get_tenant_context_allow_unpaid),
) -> TenantContext:
    """
    The default auth dependency for every tenant-scoped endpoint.

    Resolves the context exactly as get_tenant_context_allow_unpaid() does, then
    enforces the billing subscription gate: an 'unpaid' plan is blocked with
    HTTP 402. As of Gap 71 this is reachable in practice -- billing lapse now
    actually sets that plan.
    """
    if context.billing_plan == "unpaid":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Tenant subscription is unpaid. Access blocked."
        )

    return context


# --- Gap 184: programmatic API-key authentication --------------------------
#
# A PARALLEL auth path to the Clerk one above, not a replacement. Clerk session
# JWTs authenticate a *person* in a browser; an API key authenticates a
# *tenant's own integration* with no browser and no session to refresh. Both
# produce the same TenantContext so downstream handlers cannot tell (or need to
# tell) which door a request came through.
#
# Two header spellings are accepted because both are in common use for this and
# integrators reach for one or the other without checking:
#   Authorization: Bearer inv_live_...
#   X-API-Key: inv_live_...
# The `inv_live_` prefix is what distinguishes an API key from a Clerk JWT in
# the shared Authorization header -- a Clerk token can never start with it.

# The `user_id` an API-key request runs as. It is not a real Clerk user (there
# is no human on this request), and it is deliberately distinct from
# MOCK_USER_ID so audit rows written by an integration are attributable.
API_KEY_USER_ID = "api_key_client"


# --- Feature 25 (Gap 335): the two API-key action scopes --------------------
#
# The founder's own definition, verbatim:
#   Full Auto-Pilot = full automation -- the API key gets to call
#                     approve/reject/verify/send/mark-paid.
#   Strict Review   = the key stays read/upload-only, a human finalizes in the
#                     web UI.
#
# (Working user-facing name for the first one is "Full Automation", NOT "Full
# Auto-Pilot" -- Feature 13 already ships a "Tenant Autopilot" that means
# scheduled Google Drive sync, and both are configured from Settings. Founder
# has not ruled on the rename; see docs/feature_25_plug_and_play_workflows.md.)
KEY_SCOPE_READONLY = "readonly"
KEY_SCOPE_ACTIONS = "actions"
KEY_SCOPE_VALUES = (KEY_SCOPE_READONLY, KEY_SCOPE_ACTIONS)

# Non-routable domain for the synthetic service users below. `users.email` is
# globally unique, so the tenant id goes inside the local part.
API_KEY_SERVICE_USER_EMAIL_DOMAIN = "service.invoice-llm.internal"


def permissions_for_key_scope(scope: str | None) -> tuple[bool, bool, bool]:
    """
    Feature 25 (Gap 335): (can_train, can_audit, can_load) for an API-key scope.

    Replaces Gap 184's hardcoded `role = "Viewer"` -> resolve_permissions(). The
    readonly row below is the SAME effective permission set that Viewer label
    produced, so no existing tenant's behaviour changes; only the derivation is
    now explicit instead of being a side effect of a role name. (Gap 337 then
    retired that label entirely -- which is exactly why deriving key permissions
    from scope rather than from a role string mattered: nothing here had to
    change when the role vocabulary did.)

        readonly -> (False, False, False)
        actions  -> (False, True,  True)

    can_train is False at BOTH scopes, deliberately. The founder's description
    of full automation named approve/reject/verify/send (and mark-paid);
    training was not among them. Letting an integration rewrite the tenant's
    extraction rules is a much larger claim than letting it finish an invoice,
    and it will not arrive here as a side effect.

    Anything unrecognised (including None, i.e. a row predating the migration on
    a database that somehow skipped the server_default) falls to readonly --
    fail closed, never open.
    """
    if scope == KEY_SCOPE_ACTIONS:
        return False, True, True
    return False, False, False


def api_key_service_clerk_id(tenant_id: UUID) -> str:
    """The `users.clerk_user_id` of a tenant's synthetic API-key service account.

    Deterministic so the row can be looked up without storing a pointer to it,
    and unique per tenant. Cannot collide with a real Clerk subject -- those are
    `user_...`.
    """
    return f"api_key_service_{tenant_id}"


def resolve_api_key_service_user(tenant: Tenant, db_session: Session) -> UUID:
    """
    Feature 25 (Gap 335): the `users.id` an actions-scoped API-key request acts as.

    THE PROBLEM. `AuditLog.actor_user_id` is a non-null FK to `users.id`
    (models.py), written by routers/audit.py, routers/outbound_audit.py and
    routers/invoices.py. Gap 184's key path returned `db_user_id=None`, so the
    first actions-scoped key to call audit-resolve would have inserted NULL into
    that column and taken a 500 on the constraint.

    WHY NOT JUST MAKE THE FK NULLABLE. Because non-null is what guarantees every
    audited action is attributable to something. A nullable actor collapses "a
    machine did this" and "we lost track of who did this" into the same row,
    which is the opposite of what an audit trail is for.

    THE RESOLUTION. One synthetic service user per tenant, created lazily on
    first use. It satisfies the FK and names the actor -- "this action was taken
    via this tenant's API key" -- and carries NO authority of its own: role
    `RoleMapper.NO_ROLE` (the zero-permission fallback -- "Viewer" until Gap 337
    retired that name), all three permission booleans False. Permissions for a
    key request come from the scope on the TenantContext, never from this row.

    LAZY, NOT SEEDED AT PROVISIONING -- a deliberate choice:
      * seeding at provisioning would write a synthetic user for every tenant,
        including the overwhelming majority that never issue a key, and would
        need a backfill migration across every existing tenant;
      * it keeps this out of routers/auth.py's provisioning path, which is the
        most incident-prone function in this codebase (Gaps 133/157/173);
      * cost is one indexed lookup by clerk_user_id, and only at `actions`
        scope -- readonly requests keep db_user_id=None and create nothing.

    Side effect, handled: routers/admin.py::list_tenant_users() filters this row
    out so it never renders in the Settings user list as though it were a person.
    """
    clerk_id = api_key_service_clerk_id(tenant.id)
    user = db_session.exec(select(User).where(User.clerk_user_id == clerk_id)).first()
    if user:
        return user.id

    user = User(
        clerk_user_id=clerk_id,
        email=f"api-key-service+{tenant.id}@{API_KEY_SERVICE_USER_EMAIL_DOMAIN}",
        first_name="API Key",
        last_name="Service Account",
        # Carries no authority -- see docstring. The request's permissions come
        # from permissions_for_key_scope(), not from these.
        role=RoleMapper.NO_ROLE,
        can_train=False,
        can_audit=False,
        can_load=False,
        tenant_id=tenant.id,
        last_login=datetime.utcnow(),
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user.id


def resolve_api_key_context(raw_key: str, db_session: Session) -> TenantContext:
    """
    Resolve a raw API key to its tenant's context, or raise 401.

    Lookup is by the non-secret `api_key_prefix` (indexed) to find the single
    candidate row, then a constant-time digest comparison decides. A wrong key,
    an unknown prefix and a tenant that never issued a key are all the same 401
    with the same message -- the response must not reveal which tenants have
    keys.

    Gap 184 originally hardcoded `role = "Viewer"` here with no
    can_train/can_audit/can_load, on the reasoning that a key proves "this
    request comes from the tenant's own system", not "an Admin approved this
    specific action". Feature 25 (Gap 335) keeps that reasoning and makes it a
    tenant-settable decision instead of a constant: permissions now come from
    Tenant.api_key_scope via permissions_for_key_scope(). A `readonly` tenant --
    which is the default, and what every pre-existing tenant migrates to --
    resolves to exactly the same (False, False, False) this function has always
    returned.

    `role` is the same value at BOTH scopes, deliberately: scope is not a role.
    require_admin() must never be satisfiable by a key, however wide its scope --
    an integration may finish an invoice, but it may not rotate keys, manage
    users or change billing.

    Gap 337: that value was the literal "Viewer" and is now `RoleMapper.NO_ROLE`
    ("Restricted"), because a key holds no user-facing role at all -- it is the
    clearest possible statement of "no role was established for this request".
    This is a visible change to `GET /settings/security/api-key/verify`'s `role`
    field, which is the only endpoint that surfaces it; it was never a
    permission input (permissions come from the scope table above), so nothing
    is gated on it.
    """
    from services.api_keys import key_prefix, looks_like_widget_token, verify_api_key

    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or revoked API key.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Feature 25 (Gap 341). A widget token reaching this function must never
    # become a TenantContext -- that type carries `role`, `key_scope` and the
    # three permission booleans, and a credential that lives in a customer's
    # public page source has no business holding any of them. It is refused here
    # explicitly rather than being allowed to fall through to the prefix lookup
    # below and 401 as "invalid key": an integrator who pasted the wrong
    # credential needs to be told WHICH wrong credential it was, and the answer
    # must be identical whether they sent it as `X-API-Key` or as
    # `Authorization: Bearer` (which is the whole reason _extract_api_key()
    # dispatches on looks_like_platform_credential()).
    if looks_like_widget_token(raw_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "This is a chat widget token. Widget tokens are chat-only and are "
                "accepted on POST /api/v1/widget/chat/message and nowhere else. "
                "Use this workspace's API key (inv_live_...) for the REST API."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    prefix = key_prefix(raw_key)
    tenant = db_session.exec(select(Tenant).where(Tenant.api_key_prefix == prefix)).first()
    if not tenant or not verify_api_key(raw_key, tenant.api_key_salt, tenant.api_key_hash):
        raise unauthorized

    tenant.api_key_last_used_at = datetime.utcnow()
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)

    # Same billing lifecycle the Clerk path runs, for the same reasons -- an
    # integration must not be a way to keep using a lapsed tenant, and a free
    # tenant's monthly allowance must refill whichever door traffic arrives at.
    enforce_lapse(tenant, db_session)
    refresh_free_quota(tenant, db_session)

    if tenant.billing_plan == "unpaid":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Tenant subscription is unpaid. Access blocked.",
        )

    # Feature 25 (Gap 335). `or KEY_SCOPE_READONLY` covers a row that somehow
    # carries NULL despite the migration's NOT NULL server_default -- fail
    # closed rather than trusting the column blindly.
    scope = tenant.api_key_scope or KEY_SCOPE_READONLY
    role = RoleMapper.NO_ROLE

    # --- Feature 25 (Gap 340): sandbox tenants -----------------------------
    #
    # Two enforcement points, both here because this is the one function every
    # `inv_test_` request passes through.
    #
    # 1. TTL. `expires_at` is checked on EVERY authentication, not only by the
    #    reaper (scripts/sweep_sandbox_tenants.py). If expiry were the reaper's
    #    job alone then a missed job run -- an ACA Job that failed, a schedule
    #    that was never wired up -- would silently extend every outstanding
    #    sandbox key indefinitely. Expiry means the key stops verifying, and it
    #    means that whether or not anything swept.
    #
    # 2. Scope pin. A sandbox tenant is permanently readonly. This re-derives
    #    that rather than trusting the column, so even a direct database edit or
    #    some future code path that widens `api_key_scope` cannot hand
    #    approve/send/mark-paid to an anonymous visitor's key. The column is also
    #    written as readonly at creation and refused at PUT /settings/workflow --
    #    three layers, because this is the credential a stranger holds.
    #
    # A *claimed* sandbox is an ordinary tenant: sandbox_is_expired() returns
    # False for it and the pin is lifted, because at that point the workspace
    # has a real owner who may legitimately choose Full Automation.
    from services.sandbox import is_sandbox_tenant, sandbox_is_expired

    sandbox = is_sandbox_tenant(db_session, tenant.id)
    if sandbox is not None and sandbox.claimed_at is None:
        if sandbox_is_expired(sandbox):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(
                    "This sandbox key has expired. Sandbox workspaces are "
                    "temporary -- sign up for a free workspace to keep working."
                ),
                headers={"WWW-Authenticate": "Bearer"},
            )
        scope = KEY_SCOPE_READONLY
    can_train, can_audit, can_load = permissions_for_key_scope(scope)

    # Only an actions-scoped key can reach a route that writes an AuditLog, so
    # only it needs the FK-satisfying service user. A readonly key keeps
    # db_user_id=None exactly as before Gap 335 and creates no rows at all.
    db_user_id = resolve_api_key_service_user(tenant, db_session) if scope == KEY_SCOPE_ACTIONS else None

    return TenantContext(
        tenant_id=tenant.id,
        user_id=API_KEY_USER_ID,
        db_user_id=db_user_id,
        role=role,
        billing_plan=tenant.billing_plan,
        tenant_name=tenant.name,
        can_train=can_train,
        can_audit=can_audit,
        can_load=can_load,
        auth_method="api_key",
        key_scope=scope,
    )


def _extract_api_key(authorization: str | None, x_api_key: str | None) -> str | None:
    """
    Pull an `inv_live_...` key out of the request headers, or return None.

    Extracted verbatim from get_api_key_context() by Gap 335 so that
    get_tenant_or_api_key_context() dispatches on exactly the same rule rather
    than a second copy of it -- two copies is how the two paths would drift.
    Behaviour is unchanged: X-API-Key wins when both headers are present (a
    proxy-injected Authorization header is the likelier accident of the two),
    and a Bearer token only counts as a credential of ours if it carries a
    prefix a Clerk JWT can never carry.

    Gap 340/341 widened that prefix test from the single `inv_live_` literal to
    `looks_like_platform_credential()`, i.e. `inv_live_` OR `inv_test_` OR
    `inv_widget_`. The sandbox key genuinely IS an API key and resolves
    normally; the widget token is picked up here **so that it can be rejected
    with an accurate message** in resolve_api_key_context(). Leaving it out
    would send `Authorization: Bearer inv_widget_...` down the Clerk verifier to
    401 about an invalid token signature while the identical value in
    `X-API-Key` 401'd about an invalid API key -- one credential, two headers,
    two unrelated errors.
    """
    from services.api_keys import looks_like_platform_credential

    if x_api_key:
        # `or None` for a whitespace-only header. On the key-only path this is
        # the same 401 the previous inline version produced (it stripped to ""
        # and hit `if not raw_key`); on the dual path it simply means "no key
        # here", so a request carrying a junk X-API-Key AND a valid Clerk token
        # is still served as the human it is.
        return x_api_key.strip() or None
    if authorization and authorization.startswith("Bearer "):
        candidate = authorization.split(" ", 1)[1].strip()
        if looks_like_platform_credential(candidate):
            return candidate
    return None


def get_api_key_context(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
    db_session: Session = Depends(get_db_session),
) -> TenantContext:
    """
    Auth dependency for programmatic (non-browser) callers, Gap 184.

    Accepts `X-API-Key: <key>` or `Authorization: Bearer <key>`; X-API-Key wins
    when both are present, since a proxy-injected Authorization header is the
    likelier accident of the two. Missing/malformed credentials are 401 -- there
    is no mock fallback on this path at all, deliberately: unlike the Clerk
    dependency there is no local-development story that needs one.

    Key-ONLY. Use get_tenant_or_api_key_context() (Gap 335) for a route that
    should also accept a Clerk session. This one stays as it is because
    `GET /settings/security/api-key/verify` must reject a browser session --
    the whole point of that route is to prove a *key* works.
    """
    raw_key = _extract_api_key(authorization, x_api_key)

    if not raw_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Missing API key. Send it as 'X-API-Key: <key>' or "
                "'Authorization: Bearer <key>'."
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )

    return resolve_api_key_context(raw_key, db_session)


def get_tenant_or_api_key_context(
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None),
    db_session: Session = Depends(get_db_session),
) -> TenantContext:
    """
    Feature 25 (Gap 335): accept EITHER a Clerk session JWT or an `inv_live_`
    API key, and return one unified TenantContext.

    WHY THIS EXISTS AS ONE DEPENDENCY. FastAPI resolves dependencies eagerly, so
    "use the Clerk dependency OR the key dependency" cannot be expressed by
    declaring both -- declaring both runs both, and each 401s when its own
    credential is absent. Without this, every dual-credential route would need
    its own try/except tangle in the handler body, which is exactly the kind of
    per-route auth logic that drifts.

    DISPATCH, in order:
      1. `X-API-Key: <key>` present            -> key path
      2. `Authorization: Bearer inv_live_...`  -> key path
      3. anything else                         -> Clerk path

    Step 3 calls get_tenant_context_allow_unpaid() and then get_tenant_context()
    on its result rather than reimplementing either, so the 402-on-unpaid gate,
    the Gap 133 provisioning gate, the Gap 173 role reconciliation and the
    ALLOW_MOCK_AUTH local/test fallback all behave IDENTICALLY to a route that
    depends on get_tenant_context directly. Reimplementing any of that here is
    how the two paths would silently diverge.

    The key path already runs its own enforce_lapse/refresh_free_quota/402 gate
    inside resolve_api_key_context(), so both branches are billing-gated.

    Scope is NOT checked here -- this dependency only answers "who is calling".
    A route that needs `actions` scope wraps this in require_key_scope("actions").
    """
    raw_key = _extract_api_key(authorization, x_api_key)
    if raw_key:
        return resolve_api_key_context(raw_key, db_session)

    return get_tenant_context(
        context=get_tenant_context_allow_unpaid(
            authorization=authorization,
            db_session=db_session,
        )
    )


# --- Feature 1.1 (Task 1.1.2): permission-check dependencies ---------------
#
# Same shape as the existing inline `context.role != "Admin"` checks in
# routers/settings.py and routers/billing.py -- a 403 with a human-readable
# reason -- but expressed as a dependency so it can be attached once per
# router/endpoint instead of being repeated in every handler body.
#
# Each returns the resolved TenantContext, so a handler can use it as a drop-in
# replacement for `Depends(get_tenant_context)` rather than depending on both.

_PERMISSION_LABELS = {
    "can_train": "AI Trainer",
    "can_audit": "the Audit Queue",
    "can_load": "invoice ingestion",
}


def require_permission(permission: str):
    """
    Build a dependency that 403s unless the caller has `permission`.

    Admins always pass (resolve_permissions grants them all three). Deliberately
    NOT applied to machine-to-machine routes -- routers/email_ingestion.py's
    SendGrid webhook and routers/webhooks.py's HMAC-signed outbound deliveries
    are not user requests and gating them would break Features 14/15.
    """
    label = _PERMISSION_LABELS.get(permission, permission)

    def _dependency(context: TenantContext = Depends(get_tenant_context)) -> TenantContext:
        if not getattr(context, permission, False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You do not have permission to access {label}. Ask an Admin to grant it.",
            )
        return context

    return _dependency


require_can_train = require_permission("can_train")
require_can_audit = require_permission("can_audit")
require_can_load = require_permission("can_load")


# --- Feature 25 (Gap 335): dual-credential gates ---------------------------
#
# Same factory shape as require_permission() above -- build a dependency, attach
# it per-route or per-router, get a 403 with a human-readable reason -- but
# resolving through get_tenant_or_api_key_context() so a route can be reached by
# a browser session OR an API key, each judged by its own rule.


def require_key_scope(scope: str):
    """
    Build a dependency that 403s unless the caller may take financial ACTIONS on
    an invoice (approve / reject / verify / confirm-send / mark-paid).

    Two callers, two different questions, one gate:

      * API key   -> the tenant's Tenant.api_key_scope must be `actions`. The
                     403 message names the setting to change, because whoever
                     reads it is an integrator looking at a JSON error, not a
                     user looking at a toast.
      * Clerk JWT -> `can_audit`, exactly as require_can_audit has always
                     required, with the message text unchanged. That wording is
                     asserted by tests/test_rbac.py, and more importantly it is
                     what a human actually sees -- the arrival of API keys is no
                     reason to reword a human's permission error.

    Admins pass the human branch implicitly (resolve_permissions grants all
    three). An API key never does, at any scope: scope is not a role.
    """
    if scope not in KEY_SCOPE_VALUES:
        raise ValueError(f"Unknown API key scope {scope!r}; expected one of {KEY_SCOPE_VALUES}.")

    def _dependency(
        context: TenantContext = Depends(get_tenant_or_api_key_context),
    ) -> TenantContext:
        if scope == KEY_SCOPE_READONLY:
            # Every authenticated caller satisfies readonly -- the dependency
            # exists to admit API keys to the route at all, not to filter.
            return context

        if context.auth_method == "api_key":
            if context.key_scope != KEY_SCOPE_ACTIONS:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=(
                        "This API key is read-only and cannot approve, reject, send or "
                        "mark invoices as paid. An Admin can switch this workspace's "
                        "workflow policy to Full Automation in Settings to allow it."
                    ),
                )
            return context

        if not context.can_audit:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"You do not have permission to access {_PERMISSION_LABELS['can_audit']}. "
                    "Ask an Admin to grant it."
                ),
            )
        return context

    return _dependency


require_actions_scope = require_key_scope(KEY_SCOPE_ACTIONS)


def require_permission_or_api_key(permission: str):
    """
    Build a dependency that requires `permission` from a HUMAN caller but admits
    an API key of any scope.

    This exists for ingestion. The founder's Strict Review policy is explicitly
    "read/**upload**-only", so a `readonly` key must be able to upload -- but
    readonly grants can_load=False, and POST /invoices/upload is gated on
    require_can_load for humans. Swapping in the plain dual dependency would
    have quietly deleted that human gate (the one
    tests/test_rbac.py::test_invoice_upload_requires_can_load exists to
    protect). So: the human rule is unchanged, and the key is admitted because
    upload is ingestion, not one of the five actions `actions` scope governs.
    """
    label = _PERMISSION_LABELS.get(permission, permission)

    def _dependency(
        context: TenantContext = Depends(get_tenant_or_api_key_context),
    ) -> TenantContext:
        if context.auth_method == "api_key":
            return context
        if not getattr(context, permission, False):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You do not have permission to access {label}. Ask an Admin to grant it.",
            )
        return context

    return _dependency


require_can_load_or_api_key = require_permission_or_api_key("can_load")


# --- Feature 25 (Gap 341): the widget chat token's own, narrower context ---


class WidgetContext(BaseModel):
    """What a `inv_widget_...` token resolves to. **Not** a TenantContext.

    ------------------------------------------------------------------------
    THE SEPARATION IS THE SECURITY PROPERTY. READ THIS BEFORE WIDENING IT.
    ------------------------------------------------------------------------
    A widget token is pasted into a customer's own website's client-side code.
    It is visible in page source to every visitor, crawler and browser
    extension. So the containment cannot be "check the scope carefully at every
    gate" -- that is a promise about future code, and this codebase already has
    Gap 173 and Gap 344 as records of what happens when an authorisation
    decision depends on somebody remembering a check.

    Instead the containment is *structural*: this type deliberately has **no**
    `role`, **no** `key_scope`, **no** `db_user_id` and **none** of
    `can_train` / `can_audit` / `can_load`. Every gate in this file --
    `require_permission`, `require_key_scope`, `require_permission_or_api_key`,
    `require_admin` -- is annotated `context: TenantContext` and reads one of
    those fields. A widget token cannot reach any of them, because
    `get_widget_context()` is mounted on exactly one route and returns something
    those functions cannot consume. A scope-check bug elsewhere in the codebase
    has structurally nothing to get wrong here.

    Do not add permission fields to this model, and do not make it inherit from
    TenantContext. If a widget ever needs to do something other than send a chat
    message, that is a new decision, not a field.

    `origin` is carried for logging and for the (defence-in-depth only) origin
    check -- see services/widget_tokens.py::origin_is_allowed. It is not an
    authorisation input on its own and must never be described as one.
    """
    tenant_id: UUID
    widget_token_id: UUID
    auth_method: str = "widget"
    origin: str | None = None


def require_admin(context: TenantContext = Depends(get_tenant_context)) -> TenantContext:
    """Admin-only gate, for the Feature 1.1 Task 1.1.6 permission-granting endpoints."""
    if context.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin users can manage user permissions.",
        )
    return context

