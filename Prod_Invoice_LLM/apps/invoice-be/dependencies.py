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
from models import Tenant, User

class TenantContext(BaseModel):
    tenant_id: UUID
    user_id: str
    db_user_id: UUID | None = None
    role: str
    billing_plan: str

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

def get_tenant_context(
    authorization: str | None = Header(None),
    db_session: Session = Depends(get_db_session)
) -> TenantContext:
    """
    Decodes and validates the Clerk JWT token.
    Falls back to a mock context if no header is present or if using a 'test_' token.
    Blocks any request with an 'unpaid' billing plan with HTTP 402.
    Provisions Tenant and User rows in the database if they do not exist.
    """
    # 1. Local Development / Test Fallback
    if not authorization or not authorization.startswith("Bearer "):
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
                
                payload = jwt.decode(
                    token,
                    public_key,
                    algorithms=["RS256"],
                    issuer=settings.CLERK_JWT_ISSUER or None,
                    options={"verify_iss": bool(settings.CLERK_JWT_ISSUER)}
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
            role = payload.get("role") or payload.get("org_role", "Viewer")
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

    context = TenantContext(
        tenant_id=tenant_id,
        user_id=user_id,
        db_user_id=user.id,
        role=role,
        billing_plan=tenant.billing_plan
    )
    
    # 4. Enforce billing subscription gate
    if context.billing_plan == "unpaid":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Tenant subscription is unpaid. Access blocked."
        )
        
    return context

