"""Admin console backend — Feature 1.1, Task 1.1.6.

New router rather than an extension of an existing one: `routers/settings.py`
is tenant-scoped *configuration* (service-flow toggles, email senders) and
`routers/auth.py` is deliberately unprefixed (mounted without /api/v1), so
neither is a natural home for tenant-user administration. A dedicated
`/api/v1/admin` prefix also keeps the Admin-only gate uniform at router level
instead of repeated per handler.

Every endpoint here is gated by `dependencies.require_admin` and additionally
scoped to the caller's own tenant — an Admin of tenant A can never read or
modify a user belonging to tenant B.
"""
import logging
from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from dependencies import get_db_session, require_admin, TenantContext
from models import User

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(require_admin)],
)


# --- Schemas ---------------------------------------------------------------

class AdminUserOut(BaseModel):
    """A tenant user as shown in the Admin console's user table."""
    id: UUID
    clerk_user_id: str
    email: str
    first_name: str | None = None
    last_name: str | None = None
    role: str
    can_train: bool
    can_audit: bool
    can_load: bool
    created_at: datetime
    last_login: datetime | None = None


class PermissionsUpdate(BaseModel):
    """Body for PUT /admin/users/{user_ref}/permissions.

    The identity fields are only consulted when `user_ref` is a Clerk user ID
    with no backing row yet — see set_user_permissions for why that case exists.
    """
    can_train: bool
    can_audit: bool
    can_load: bool
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None


# --- Endpoints -------------------------------------------------------------

@router.get("/users", response_model=list[AdminUserOut])
async def list_tenant_users(
    context: TenantContext = Depends(require_admin),
    db_session: Session = Depends(get_db_session),
):
    """List every user in the caller's tenant, with their current permissions.

    The Admin console needs this to render checkboxes reflecting real stored
    state — before this, `app/admin/page.tsx` held its user list in ephemeral
    client state that vanished on reload.
    """
    users = db_session.exec(
        select(User).where(User.tenant_id == context.tenant_id).order_by(User.created_at)
    ).all()
    return [AdminUserOut.model_validate(u, from_attributes=True) for u in users]


@router.put("/users/{user_ref}/permissions", response_model=AdminUserOut)
async def set_user_permissions(
    user_ref: str,
    payload: PermissionsUpdate,
    context: TenantContext = Depends(require_admin),
    db_session: Session = Depends(get_db_session),
):
    """Set a user's can_train / can_audit / can_load flags. Admin-only.

    `user_ref` accepts either the backend `users.id` UUID (what GET /admin/users
    returns, used at edit time) or a Clerk user ID (what POST
    /api/admin/create-user returns, used at create time).

    The Clerk-ID case needs a pre-provisioning fallback: `get_tenant_context`
    only writes a `users` row the first time someone actually calls the API, so
    a user created seconds ago in the Admin console has no row yet. Without the
    fallback, permissions ticked at create time would be silently dropped and
    the Admin would have to come back after the user's first login. When the
    row is created here it gets role "Viewer" — Admin is never granted by this
    endpoint, only by the Clerk-side role the JWT carries.
    """
    user: User | None = None

    try:
        user = db_session.get(User, UUID(user_ref))
    except ValueError:
        user = db_session.exec(
            select(User).where(User.clerk_user_id == user_ref)
        ).first()

    if user and user.tenant_id != context.tenant_id:
        # Never leak the existence of another tenant's user.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if not user:
        if not user_ref.startswith("user_") or not payload.email:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        existing_email = db_session.exec(
            select(User).where(User.email == payload.email)
        ).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with that email already exists.",
            )
        user = User(
            id=uuid4(),
            tenant_id=context.tenant_id,
            email=payload.email,
            first_name=payload.first_name,
            last_name=payload.last_name,
            role="Viewer",
            clerk_user_id=user_ref,
            created_at=datetime.utcnow(),
        )

    user.can_train = payload.can_train
    user.can_audit = payload.can_audit
    user.can_load = payload.can_load
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    logger.info(
        "Admin %s set permissions for user %s: train=%s audit=%s load=%s",
        context.user_id, user.clerk_user_id, user.can_train, user.can_audit, user.can_load,
    )
    return AdminUserOut.model_validate(user, from_attributes=True)
