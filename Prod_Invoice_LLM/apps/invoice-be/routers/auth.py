from uuid import uuid4
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from dependencies import get_tenant_context_allow_unpaid, get_db_session, TenantContext
from models import Tenant, User
from config import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])


# --- Request / Response Schemas ---

class TenantProvisionRequest(BaseModel):
    """Request body for POST /auth/provision."""
    clerk_org_id: str          # Clerk Organization ID, e.g. "org_2abc..."
    org_name: str              # Display name chosen during signup
    admin_email: str           # Admin's email (used as domain fallback)
    clerk_user_id: str         # Clerk user ID of the admin, e.g. "user_2xyz..."
    first_name: str | None = None
    last_name: str | None = None


class TenantProvisionResponse(BaseModel):
    """Response body for POST /auth/provision."""
    tenant_id: str
    clerk_org_id: str
    org_name: str
    billing_plan: str
    free_invoices_remaining: int
    is_new: bool               # True if tenant was just created, False if already existed


class LogoutRequest(BaseModel):
    """Request body for POST /auth/logout."""
    clerk_user_id: str | None = None


class LogoutResponse(BaseModel):
    """Response body for POST /auth/logout."""
    status: str
    message: str


# --- Endpoints ---

@router.get("/me", response_model=TenantContext)
async def get_current_user_context(context: TenantContext = Depends(get_tenant_context_allow_unpaid)):
    """Returns the authenticated tenant and user context parsed from the JWT.

    Gap 71: deliberately allow-unpaid. This is the FE's identity source
    (hooks/useAuth.ts) -- if it 402'd for a lapsed tenant the app could not
    read its own billing_plan to explain *why* everything else is failing, and
    would fall back to the anonymous least-privilege identity instead. Returning
    the real context with billing_plan='unpaid' is what lets the UI say
    "your plan lapsed" and route the user to checkout."""
    return context


@router.post("/provision", response_model=TenantProvisionResponse)
async def provision_tenant(
    body: TenantProvisionRequest,
    db_session: Session = Depends(get_db_session),
):
    """
    Called by the website after admin signup to register a Clerk Organization
    as a tenant in the backend database.

    Idempotent -- calling again with the same clerk_org_id returns the
    existing tenant without creating a duplicate.
    """
    existing_tenant = db_session.exec(
        select(Tenant).where(Tenant.clerk_org_id == body.clerk_org_id)
    ).first()

    if existing_tenant:
        return TenantProvisionResponse(
            tenant_id=str(existing_tenant.id),
            clerk_org_id=existing_tenant.clerk_org_id,
            org_name=existing_tenant.name,
            billing_plan=existing_tenant.billing_plan,
            free_invoices_remaining=existing_tenant.free_invoices_remaining,
            is_new=False,
        )

    domain = body.admin_email.split("@")[-1] if "@" in body.admin_email else "unknown.com"

    # A tenant may already exist for this domain from before Clerk Organizations
    # were wired in -- link it instead of creating a duplicate.
    domain_tenant = db_session.exec(
        select(Tenant).where(Tenant.domain == domain)
    ).first()

    if domain_tenant and not domain_tenant.clerk_org_id:
        domain_tenant.clerk_org_id = body.clerk_org_id
        domain_tenant.name = body.org_name
        domain_tenant.updated_at = datetime.utcnow()
        db_session.add(domain_tenant)
        db_session.commit()
        db_session.refresh(domain_tenant)

        return TenantProvisionResponse(
            tenant_id=str(domain_tenant.id),
            clerk_org_id=domain_tenant.clerk_org_id,
            org_name=domain_tenant.name,
            billing_plan=domain_tenant.billing_plan,
            free_invoices_remaining=domain_tenant.free_invoices_remaining,
            is_new=False,
        )

    new_tenant = Tenant(
        id=uuid4(),
        name=body.org_name,
        domain=domain,
        clerk_org_id=body.clerk_org_id,
        billing_plan="free",
        free_invoices_remaining=settings.DEFAULT_FREE_INVOICES_LIMIT,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db_session.add(new_tenant)
    db_session.commit()
    db_session.refresh(new_tenant)

    existing_user = db_session.exec(
        select(User).where(User.clerk_user_id == body.clerk_user_id)
    ).first()

    if not existing_user:
        admin_user = User(
            id=uuid4(),
            tenant_id=new_tenant.id,
            email=body.admin_email,
            first_name=body.first_name,
            last_name=body.last_name,
            role="Admin",
            clerk_user_id=body.clerk_user_id,
            created_at=datetime.utcnow(),
        )
        db_session.add(admin_user)
        db_session.commit()
    elif not existing_user.tenant_id:
        existing_user.tenant_id = new_tenant.id
        db_session.add(existing_user)
        db_session.commit()

    return TenantProvisionResponse(
        tenant_id=str(new_tenant.id),
        clerk_org_id=new_tenant.clerk_org_id,
        org_name=new_tenant.name,
        billing_plan=new_tenant.billing_plan,
        free_invoices_remaining=new_tenant.free_invoices_remaining,
        is_new=True,
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(body: LogoutRequest):
    """
    Called by the frontend after signing out from Clerk, for server-side
    session cleanup/audit logging.

    Always returns 200 OK regardless of JWT presence -- logout is idempotent
    and should not fail even if Clerk already cleared the session.
    """
    return LogoutResponse(
        status="signed_out",
        message="Session cleared successfully",
    )
