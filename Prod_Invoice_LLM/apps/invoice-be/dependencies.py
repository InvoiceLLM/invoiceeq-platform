import httpx
import jwt
from jwt.algorithms import RSAAlgorithm
from uuid import UUID
from typing import Generator
from fastapi import Header, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session

from config import settings
from database import engine

class TenantContext(BaseModel):
    tenant_id: UUID
    user_id: str
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

def get_tenant_context(authorization: str | None = Header(None)) -> TenantContext:
    """
    Decodes and validates the Clerk JWT token.
    Falls back to a mock context if no header is present or if using a 'test_' token.
    Blocks any request with an 'unpaid' billing plan with HTTP 402.
    """
    # 1. Local Development / Test Fallback
    if not authorization or not authorization.startswith("Bearer "):
        return TenantContext(
            tenant_id=MOCK_TENANT_ID,
            user_id=MOCK_USER_ID,
            role=MOCK_ROLE,
            billing_plan=MOCK_BILLING_PLAN
        )
    
    token = authorization.split(" ")[1]
    
    # Check for mock test token format (e.g. 'test_', 'test_unpaid')
    if token.startswith("test_"):
        plan = "unpaid" if "unpaid" in token else MOCK_BILLING_PLAN
        role = "Viewer" if "viewer" in token else MOCK_ROLE
        
        tenant_id = MOCK_TENANT_ID
        # Extract UUID if provided in test token
        for part in token.split("_"):
            try:
                tenant_id = UUID(part)
            except ValueError:
                continue
                
        context = TenantContext(
            tenant_id=tenant_id,
            user_id=MOCK_USER_ID,
            role=role,
            billing_plan=plan
        )
        
        # Payment gate block
        if context.billing_plan == "unpaid":
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail="Tenant subscription is unpaid. Access blocked."
            )
        return context

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
    tenant_id_str = payload.get("tenant_id") or payload.get("org_id")
    if not tenant_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing tenant_id/org_id in token claims."
        )
        
    try:
        tenant_id = UUID(tenant_id_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="tenant_id in token claims is not a valid UUID."
        )
        
    context = TenantContext(
        tenant_id=tenant_id,
        user_id=payload.get("sub", MOCK_USER_ID),
        role=payload.get("role") or payload.get("org_role", "Viewer"),
        billing_plan=payload.get("billing_plan", "free")
    )
    
    # 4. Enforce billing subscription gate
    if context.billing_plan == "unpaid":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Tenant subscription is unpaid. Access blocked."
        )
        
    return context
