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
from models import AuditLog, User

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


class AdminUserRemoved(BaseModel):
    """Outcome of DELETE /admin/users/{user_ref}.

    `detached` distinguishes the two legal end states: the row was deleted
    outright, or it was kept but stripped of its tenant and permissions because
    `audit_logs.actor_user_id` still references it (see remove_tenant_user).
    Either way the user is gone from GET /admin/users, which is tenant-scoped.
    """
    id: UUID
    clerk_user_id: str
    email: str
    detached: bool


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


@router.delete("/users/{user_ref}", response_model=AdminUserRemoved)
async def remove_tenant_user(
    user_ref: str,
    context: TenantContext = Depends(require_admin),
    db_session: Session = Depends(get_db_session),
):
    """Remove a user from the caller's tenant. Admin-only, tenant-scoped.

    FE Gap 168: the Admin console's "Remove" button had no endpoint behind it
    at all -- it filtered the row out of React state and nothing else, so the
    user kept every bit of their access and reappeared on the next page load.

    `user_ref` accepts the same two forms as PUT .../permissions: the backend
    `users.id` UUID (what GET /admin/users returns) or a Clerk user ID.

    Two guards, both deliberate:
      - an Admin cannot remove themselves (that would leave a tenant with no
        one able to administer it, and is almost always a misclick);
      - an Admin cannot remove another Admin here. Admin comes from the Clerk
        org role the JWT carries, not from this table, so deleting the row
        would not demote them -- it would be undone on their next request.
        Demotion belongs in Clerk.

    Rows referenced by `audit_logs.actor_user_id` are detached rather than
    deleted (tenant_id cleared, permissions revoked): the audit trail must keep
    naming who acted, and a hard delete would either violate the FK or orphan
    history. A detached row is invisible to every tenant-scoped query,
    including GET /admin/users.

    Note what this endpoint is and is not: it removes the user from *this
    tenant's* data. Deleting their Clerk account -- the thing that actually
    grants sign-in -- is done by the FE route that calls this
    (`app/api/admin/users/[userRef]/route.ts`), for the same reason
    `POST /api/admin/create-user` creates it there: Clerk user administration
    lives on the Next.js side, which holds CLERK_SECRET_KEY.
    """
    user: User | None = None

    try:
        user = db_session.get(User, UUID(user_ref))
    except ValueError:
        user = db_session.exec(
            select(User).where(User.clerk_user_id == user_ref)
        ).first()

    # Never leak the existence of another tenant's user.
    if not user or user.tenant_id != context.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if user.clerk_user_id == context.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot remove your own account.",
        )

    if user.role == "Admin":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Another Admin cannot be removed here. Change their role in Clerk first.",
        )

    removed = AdminUserRemoved(
        id=user.id,
        clerk_user_id=user.clerk_user_id,
        email=user.email,
        detached=False,
    )

    has_audit_history = db_session.exec(
        select(AuditLog.id).where(AuditLog.actor_user_id == user.id).limit(1)
    ).first() is not None

    if has_audit_history:
        user.tenant_id = None
        user.can_train = False
        user.can_audit = False
        user.can_load = False
        user.role = "Viewer"
        db_session.add(user)
        removed.detached = True
    else:
        db_session.delete(user)

    db_session.commit()

    logger.info(
        "Admin %s removed user %s (%s) from tenant %s (detached=%s)",
        context.user_id, removed.clerk_user_id, removed.email,
        context.tenant_id, removed.detached,
    )
    return removed
