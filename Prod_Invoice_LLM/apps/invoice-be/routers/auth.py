from fastapi import APIRouter, Depends
from dependencies import get_tenant_context, TenantContext

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.get("/me", response_model=TenantContext)
async def get_current_user_context(context: TenantContext = Depends(get_tenant_context)):
    """Returns the authenticated tenant and user context parsed from the JWT."""
    return context
