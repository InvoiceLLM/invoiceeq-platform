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

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlmodel import Session, select, or_

from dependencies import (
    get_db_session,
    require_admin,
    # Feature 25 (Gap 335): used only to filter the synthetic API-key service
    # user out of the Admin user list -- see list_tenant_users().
    api_key_service_clerk_id,
    TenantContext,
)
from models import AuditLog, DroppedInboundEmail, RoleMapper, Tenant, TenantEmailSender, User
from services.inbound_mail_security import sender_domain_of

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
    can_send_invoices: bool  # Gap 369
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
    can_send_invoices: bool = False  # Gap 369 — defaulted so an older FE build omitting the field still validates
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


class DroppedEmailOut(BaseModel):
    """One inbound mail that never became an invoice — Gap 124 item 6.

    `attributed` says whether the drop is definitely this tenant's (the sender
    was in its authorized set) or only *probably* (an unattributed drop shown
    here because the sender's domain is one of this workspace's). The UI shows
    the difference so an Admin doesn't read a domain-matched row as proof the
    mail was addressed to them.
    """
    id: UUID
    reason: str
    detail: str
    from_email: str | None = None
    to_email: str | None = None
    filename: str | None = None
    content_length: int | None = None
    attributed: bool
    created_at: datetime


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
    # Feature 25 (Gap 335): exclude this tenant's synthetic API-key service
    # user. It is a real `users` row -- it has to be, so that an
    # `actions`-scoped key's audit entries satisfy AuditLog's non-null
    # actor_user_id FK -- but it is not a person, has no permissions of its own,
    # and must not appear in the Admin console as though an Admin could grant it
    # any. Filtered by exact clerk_user_id equality rather than a `LIKE`
    # pattern: `_` is a SQL LIKE wildcard, and "api\_key\_service\_%" is the
    # kind of subtly-wrong pattern that works until it doesn't.
    service_user_clerk_id = api_key_service_clerk_id(context.tenant_id)
    users = db_session.exec(
        select(User)
        .where(
            User.tenant_id == context.tenant_id,
            User.clerk_user_id != service_user_clerk_id,
        )
        .order_by(User.created_at)
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
    row is created here it gets `RoleMapper.NO_ROLE` — the zero-permission
    fallback, spelled "Viewer" until Gap 337 retired that name — because no role
    has been established for this user yet. Admin is never granted by this
    endpoint, only by the Clerk-side role the JWT carries. The per-area
    permissions in the payload are still applied on top, which is the whole
    point of the pre-provisioning path.
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
            role=RoleMapper.NO_ROLE,
            clerk_user_id=user_ref,
            created_at=datetime.utcnow(),
        )

    user.can_train = payload.can_train
    user.can_audit = payload.can_audit
    user.can_load = payload.can_load
    user.can_send_invoices = payload.can_send_invoices  # Gap 369
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    logger.info(
        "Admin %s set permissions for user %s: train=%s audit=%s load=%s send_invoices=%s",
        context.user_id, user.clerk_user_id, user.can_train, user.can_audit, user.can_load, user.can_send_invoices,
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
        # Gap 337: demote to the zero-permission fallback, not to one of the
        # three assignable roles -- a detached user must hold nothing.
        user.role = RoleMapper.NO_ROLE
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


def _tenant_email_domains(db_session: Session, tenant_id: UUID) -> set[str]:
    """Domains this workspace can legitimately claim mail from.

    Its own `Tenant.domain` plus the domain of every address in its authorized
    inbound/outbound sets. Used only to decide which *unattributed* dropped
    mails to surface — never to grant access to another tenant's rows.
    """
    domains: set[str] = set()

    tenant = db_session.get(Tenant, tenant_id)
    if tenant and tenant.domain:
        domains.add(tenant.domain.strip().lower())

    senders = db_session.exec(
        select(TenantEmailSender.email).where(TenantEmailSender.tenant_id == tenant_id)
    ).all()
    for address in senders:
        domain = sender_domain_of(address)
        if domain:
            domains.add(domain)

    return {d for d in domains if d}


@router.get("/dropped-emails", response_model=list[DroppedEmailOut])
async def list_dropped_emails(
    limit: int = Query(default=50, ge=1, le=200),
    context: TenantContext = Depends(require_admin),
    db_session: Session = Depends(get_db_session),
):
    """Inbound mail that was rejected or skipped instead of becoming an invoice.

    Gap 124 item 6. Before this, every drop path in the mailintegration webhook
    ended at a `logger.warning` and a 200 — a vendor could email an invoice, the
    webhook could refuse it for any of eight reasons, and no one outside the
    container logs would ever know. This is the read side of that record.

    **Visibility rule.** The app mailbox is platform-wide, so a drop is only
    attributable to a tenant once the From address has matched
    `tenant_email_senders`. Two kinds of row are therefore returned:

      * `tenant_id == caller's tenant` — attributed, unambiguously theirs;
      * `tenant_id IS NULL` **and** the sender's domain is one of this
        workspace's (its own `Tenant.domain`, or the domain of any address in
        its authorized sets).

    The second case is what makes the common failure legible: someone at the
    customer's own company emails from an address nobody registered, so the
    webhook cannot attribute it, and without the domain match the row would be
    invisible to the only person who could fix it. It is deliberately narrow —
    an unattributed drop from an unrelated domain is shown to nobody rather
    than to every Admin on the platform, because the From addresses of other
    tenants' senders are not this tenant's business. Nothing is silently lost
    either way: unattributed rows outside every tenant's domain set are still
    in the table for a platform operator.
    """
    domains = _tenant_email_domains(db_session, context.tenant_id)

    visibility = DroppedInboundEmail.tenant_id == context.tenant_id
    if domains:
        visibility = or_(
            visibility,
            (DroppedInboundEmail.tenant_id.is_(None))
            & (DroppedInboundEmail.sender_domain.in_(sorted(domains))),
        )

    rows = db_session.exec(
        select(DroppedInboundEmail)
        .where(visibility)
        .order_by(DroppedInboundEmail.created_at.desc())
        .limit(limit)
    ).all()

    return [
        DroppedEmailOut(
            id=row.id,
            reason=row.reason,
            detail=row.detail,
            from_email=row.from_email,
            to_email=row.to_email,
            filename=row.filename,
            content_length=row.content_length,
            attributed=row.tenant_id == context.tenant_id,
            created_at=row.created_at,
        )
        for row in rows
    ]
