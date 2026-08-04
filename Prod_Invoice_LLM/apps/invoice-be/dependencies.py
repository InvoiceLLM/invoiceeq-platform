import httpx
import jwt
from jwt.algorithms import RSAAlgorithm
from uuid import UUID
from typing import Generator
from fastapi import Header, HTTPException, status, Depends
from pydantic import BaseModel
from sqlmodel import Session, select
from datetime import datetime

from config import settings
from database import engine
from models import Tenant, User, RoleMapper
from services.billing_lifecycle import enforce_lapse

class TenantContext(BaseModel):
    tenant_id: UUID
    user_id: str
    db_user_id: UUID | None = None
    role: str
    billing_plan: str
    # Feature 1.1 (Task 1.1.3): per-area permissions, resolved from the User
    # row rather than the JWT -- permissions are our data, not Clerk's, so an
    # Admin's grant takes effect on the very next request without waiting for
    # a token refresh. Admin implies all three (see resolve_permissions).
    # GET /auth/me returns this model verbatim, so the FE gets them for free.
    can_train: bool = False
    can_audit: bool = False
    can_load: bool = False

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

def resolve_permissions(role: str, user: User | None) -> tuple[bool, bool, bool]:
    """
    Feature 1.1 (Task 1.1.3) / Gap 73: resolve (can_train, can_audit, can_load).
    Delegates to RoleMapper for enterprise-scale role mapping and fallback permissions.
    """
    return RoleMapper.resolve_permissions(role, user)


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
            role = "Viewer" if "viewer" in token else MOCK_ROLE

            tenant_id = MOCK_TENANT_ID
            clerk_org_id = None
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
        else:
            # 2. Live JWT Decoding & Verification
            # Gap 4: fail closed before touching the token -- incomplete config
            # must never soften verification (see require_clerk_jwt_config).
            require_clerk_jwt_config()
            try:
                header = jwt.get_unverified_header(token)
                kid = header.get("kid")
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
                payload = jwt.decode(
                    token,
                    public_key,
                    algorithms=["RS256"],
                    issuer=settings.CLERK_JWT_ISSUER,
                    options={"verify_iss": True}
                )
            except jwt.ExpiredSignatureError:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token signature has expired."
                )
            except jwt.InvalidTokenError as e:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=f"Invalid token: {str(e)}"
                )
            
            # 3. Extract tenant parameters from JWT claims
            # clerk_org_id (e.g. "org_2abc...") is a Clerk-assigned string, not a UUID --
            # kept separate from tenant_id (only ever populated from a custom "tenant_id"
            # claim) so it can't be mistakenly parsed as one.
            clerk_org_id = payload.get("org_id")
            tenant_id = None

            tenant_id_str = payload.get("tenant_id")
            if tenant_id_str:
                try:
                    tenant_id = UUID(tenant_id_str)
                except ValueError:
                    pass  # Not a valid UUID, ignore

            user_id = payload.get("sub", MOCK_USER_ID)
            raw_role = payload.get("role") or payload.get("org_role", "Viewer")
            role = RoleMapper.normalize_role(raw_role)
            plan = payload.get("billing_plan", "free")
            email = payload.get("email") or payload.get("email_address") or f"{user_id}@domain.com"
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

        # Priority 3: look up by email domain (legacy fallback)
        if not tenant:
            tenant = db_session.exec(select(Tenant).where(Tenant.domain == domain)).first()

        if not tenant:
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
        if role and user.role != role:
            user.role = role
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        
        if user.tenant_id:
            tenant_id = user.tenant_id
            tenant = db_session.get(Tenant, tenant_id)
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
                if not tenant_id:
                    tenant_id = MOCK_TENANT_ID
                tenant = db_session.get(Tenant, tenant_id)

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
    # scripts/sweep_lapsed_billing.py covers idle tenants who never make a
    # request at all -- see services/billing_lifecycle.sweep_lapsed_tenants().
    enforce_lapse(tenant, db_session)

    context = TenantContext(
        tenant_id=tenant_id,
        user_id=user_id,
        db_user_id=user.id,
        role=role,
        billing_plan=tenant.billing_plan,
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


def require_admin(context: TenantContext = Depends(get_tenant_context)) -> TenantContext:
    """Admin-only gate, for the Feature 1.1 Task 1.1.6 permission-granting endpoints."""
    if context.role != "Admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Admin users can manage user permissions.",
        )
    return context

