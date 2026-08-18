from uuid import uuid4
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select, text

from dependencies import (
    AuthenticatedClerkIdentity,
    get_authenticated_clerk_identity,
    get_tenant_context_allow_unpaid,
    get_db_session,
    TenantContext,
)
from models import (
    AuditLog,
    ChatFeedback,
    ChatSession,
    ExtractionTemplate,
    ExtractionTemplateVersion,
    Invoice,
    RoleMapper,
    Tenant,
    TenantConnection,
    TenantEmailSender,
    User,
    WebhookSubscription,
)
from config import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])


# --- Request / Response Schemas ---

class TenantProvisionRequest(BaseModel):
    """Request body for POST /auth/provision."""
    clerk_org_id: str          # Clerk Organization ID, e.g. "org_2abc..."
    org_name: str              # Display name chosen during signup
    # Gap 133 (Checkpoint 3c): IGNORED for a real token -- the admin address is
    # taken from the caller's own verified `email` claim instead (see
    # provision_tenant). It stays on the schema because the website still sends
    # it and rejecting the field would break that caller for no benefit, and it
    # is still used on the ALLOW_MOCK_AUTH path (default off), which has no
    # token to read a claim from.
    admin_email: str
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


# --- Helpers ---

def _create_tenant_with_unique_domain(
    db_session: Session,
    body: TenantProvisionRequest,
    domain: str,
) -> Tenant:
    """
    Gap 133: insert the new tenant, surviving the unique constraint on
    `Tenant.domain`.

    Two organisations signing up from the same email domain (gmail.com, or any
    company where a second team creates its own workspace) both derive the same
    `domain` value. The first INSERT wins; the second used to raise
    IntegrityError out of the handler as a bare 500, leaving the Clerk user
    created but no tenant -- exactly the "signed up fine, no tenant anywhere"
    state Gap 133 was opened for.

    The retry keeps the tenants separate rather than merging them: the domain
    column is only an identity hint, and `.invalid` is the RFC 2606 reserved TLD
    for a name that must never resolve, which is what a synthetic value here is.
    A second IntegrityError means something other than the domain collided
    (realistically a concurrent request for the same `clerk_org_id`), which is a
    409 with a specific reason -- never a 500.
    """
    def _insert(tenant_domain: str) -> Tenant:
        tenant = Tenant(
            id=uuid4(),
            name=body.org_name,
            domain=tenant_domain,
            clerk_org_id=body.clerk_org_id,
            billing_plan="free",
            free_invoices_remaining=settings.DEFAULT_FREE_INVOICES_LIMIT,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db_session.add(tenant)
        db_session.commit()
        db_session.refresh(tenant)
        return tenant

    try:
        return _insert(domain)
    except IntegrityError:
        db_session.rollback()

    fallback_domain = f"org-{body.clerk_org_id}.invalid"
    try:
        return _insert(fallback_domain)
    except IntegrityError as e:
        db_session.rollback()
        # Re-read: the overwhelmingly likely cause is a concurrent request that
        # provisioned this same org between our first lookup and this INSERT,
        # in which case that row is the correct answer and this is not an error
        # for the caller at all.
        concurrent = db_session.exec(
            select(Tenant).where(Tenant.clerk_org_id == body.clerk_org_id)
        ).first()
        if concurrent:
            return concurrent
        # Gap 133 (Checkpoint 3c): the raw driver exception used to be
        # interpolated into the response body. On Postgres that string names the
        # table, the constraint and the colliding value -- i.e. it discloses
        # schema detail, and the domain of whoever already holds the row, to an
        # unauthenticated-until-a-moment-ago caller. It goes to stdout instead;
        # print(), not logger, for the same reason as dependencies.py's
        # [jwt-diag] lines (this container's log stream only captures stdout).
        print(
            f"[provision-diag] tenant insert conflict org_id={body.clerk_org_id!r} "
            f"domain={domain!r} fallback_domain={fallback_domain!r} error={e!r}",
            flush=True,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Could not create a workspace for this organisation: the tenant "
                f"record conflicts with an existing one (org id {body.clerk_org_id}). "
                "Please retry; if it keeps failing, contact support with that org id."
            ),
        )


# Gap 133 (Checkpoint 3c): every table that is scoped to a tenant and therefore
# means "this tenant holds real data". Used only by _tenant_adoption_blockers().
# ChatMessage is deliberately absent -- it is scoped by session_id, so it is
# covered transitively by ChatSession. If a new tenant-scoped table is added,
# add it here too: the failure mode of forgetting is that a tenant holding that
# data looks adoptable.
_TENANT_SCOPED_TABLES = (
    (Invoice, "invoices"),
    (TenantConnection, "connected accounts"),
    (AuditLog, "audit history"),
    (ExtractionTemplate, "extraction templates"),
    (ExtractionTemplateVersion, "extraction template history"),
    (ChatSession, "chat sessions"),
    (ChatFeedback, "chat feedback"),
    (TenantEmailSender, "authorized email senders"),
    (WebhookSubscription, "webhook subscriptions"),
)


def _tenant_adoption_blockers(db_session: Session, tenant: Tenant) -> list[str]:
    """
    Gap 133 (Checkpoint 3c): reasons this domain-matched tenant must NOT be
    adopted by the org currently provisioning.

    Checkpoint 3b required only "no clerk_org_id and no User rows". That is not
    the same thing as "empty": a legacy pre-Clerk-Organizations tenant can hold
    a paid billing plan, a PayU customer id, live OAuth connections and
    invoices while having zero `users` rows (users were deleted, or the rows
    predate the users table being populated at all). Adopting such a tenant
    hands whoever signs up next from that email domain everything it contains.

    Returns an empty list when the tenant is genuinely an unclaimed placeholder.
    Anything non-empty means the caller falls through to getting a fresh
    isolated tenant -- the same, safe outcome as the "has users" case. This is
    deliberately strict: adoption firing rarely (or never) costs nothing but a
    duplicate-looking row, while adoption firing wrongly is a tenant takeover.
    """
    blockers: list[str] = []

    if tenant.clerk_org_id:
        blockers.append("already linked to a Clerk organisation")
    if tenant.billing_plan and tenant.billing_plan != "free":
        blockers.append(f"non-default billing plan ({tenant.billing_plan})")
    if tenant.payu_customer_id or tenant.payu_subscription_id or tenant.paid_through:
        blockers.append("payment/subscription history")
    if db_session.exec(select(User).where(User.tenant_id == tenant.id)).first() is not None:
        blockers.append("users")

    for model, label in _TENANT_SCOPED_TABLES:
        if db_session.exec(select(model).where(model.tenant_id == tenant.id)).first() is not None:
            blockers.append(label)

    return blockers


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
    caller: AuthenticatedClerkIdentity = Depends(get_authenticated_clerk_identity),
    db_session: Session = Depends(get_db_session),
):
    """
    Called by the website after admin signup to register a Clerk Organization
    as a tenant in the backend database.

    Idempotent -- calling again with the same clerk_org_id returns the
    existing tenant without creating a duplicate.

    Gap 133 changed three things about this endpoint:

    1. **It is authenticated.** It used to take no auth dependency at all, so
       an anonymous caller who knew (or guessed) a clerk_org_id could rename or
       claim an existing tenant -- reproduced against the running dev backend in
       Checkpoint 3a. The website now mints a real Clerk session token after
       `setActive` and forwards it; the token's `sub` must equal the
       `clerk_user_id` in the body.
    2. **It never adopts a populated tenant.** The pre-Clerk-Organizations
       linking path stays, but only for a domain tenant that has no
       `clerk_org_id` AND no users at all. A domain tenant with real users
       belongs to somebody; a different org signing up from the same email
       domain must not silently rename it and take it over.
    3. **A domain collision is no longer a 500.** `Tenant.domain` is unique, so
       the second organisation to sign up from a shared email domain used to
       blow up on the INSERT. It now retries once with a disambiguated
       `org-<clerk_org_id>.invalid` domain, and only a genuinely unresolvable
       second failure (e.g. a concurrent duplicate `clerk_org_id`) becomes an
       explicit 409 -- never a bare 500.

    Checkpoint 3c then closed what (2) authenticated but never checked: *what*
    the authenticated caller is allowed to claim.

    4. **`clerk_org_id` is bound to the token's own `org_id`.** Checking only
       `sub` meant any signed-in user could POST somebody else's
       not-yet-provisioned org id and claim it -- and, via the idempotent early
       return below, read back that tenant's UUID, name, plan and remaining
       quota for any org id they could guess. The body must now name the org the
       caller is actually signed in to.
    5. **`admin_email` is taken from the token's `email` claim, not the body.**
       It was fully caller-controlled, and `User.email` is globally unique, so
       an attacker could provision with a stranger's real address -- squatting
       it and turning the real owner's later sign-up into an unhandled
       IntegrityError (a bare 500, which item 3's docstring claimed could no
       longer happen). The admin `User` insert is also IntegrityError-guarded
       now, as defence in depth.
    6. **Adoption requires the domain tenant to be genuinely empty**, not merely
       user-less -- see _tenant_adoption_blockers().
    """
    # `caller.is_mock` is only True on the mock-auth path
    # (settings.ALLOW_MOCK_AUTH, default False) -- see
    # dependencies.get_authenticated_clerk_identity. There is no token there to
    # bind anything to, so the body is taken at face value, exactly as every
    # other dependency treats mock auth.
    if not caller.is_mock:
        if caller.clerk_user_id != body.clerk_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "The authenticated user does not match clerk_user_id in the request "
                    "body. A tenant can only be provisioned by the user it is being "
                    "provisioned for."
                ),
            )
        # Checkpoint 3c, finding 1. Clerk puts `org_id` on the session token for
        # whichever organisation is active, so this is satisfied by the
        # website's own flow (it calls setActive for the org it just created
        # before minting the token) and cannot be satisfied for an org the
        # caller is not a member of.
        if caller.org_id != body.clerk_org_id:
            print(
                "[provision-diag] org-claim mismatch: "
                f"sub={caller.clerk_user_id!r} token_org_id={caller.org_id!r} "
                f"body_org_id={body.clerk_org_id!r}",
                flush=True,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "The authenticated session's active organisation does not match "
                    "clerk_org_id in the request body. A tenant can only be "
                    "provisioned for the organisation the caller is actually signed "
                    "in to."
                ),
            )

    # Checkpoint 3c, finding 3: the admin address is the caller's own verified
    # claim. `body.admin_email` is not trusted at all for a real token. The
    # `user_<id>@domain.com` fallback is the same one
    # get_tenant_context_allow_unpaid() uses when the Clerk JWT Template omits
    # the claim -- one pattern, not two.
    if caller.is_mock:
        admin_email = body.admin_email
        email_is_placeholder = False
    else:
        admin_email = caller.email or f"{caller.clerk_user_id}@domain.com"
        email_is_placeholder = caller.email is None

    domain = admin_email.split("@")[-1] if "@" in admin_email else "unknown.com"

    # Concurrency lock to serialize tenant creation and adoption, preventing TOCTOU races.
    # Uses Postgres transactional advisory locks; degrades gracefully on SQLite (testing).
    if db_session.bind.dialect.name == "postgresql":
        db_session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:org_key))"),
            {"org_key": body.clerk_org_id}
        )
        if not email_is_placeholder:
            db_session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:domain_key))"),
                {"domain_key": domain}
            )

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

    # A tenant may already exist for this domain from before Clerk Organizations
    # were wired in -- link it instead of creating a duplicate. Gap 133: only
    # when that tenant is genuinely unclaimed. `not clerk_org_id` alone was not
    # enough: a tenant created by the old request-time auto-provision path had
    # no clerk_org_id but did have real users and real invoices, and adopting it
    # here renamed somebody else's workspace.
    #
    # Checkpoint 3c: a placeholder address never matches on domain at all. When
    # the Clerk JWT Template omits `email` the synthetic domain is literally
    # "domain.com" for every such caller -- matching on it is the exact
    # mechanism that merged unrelated sign-ups into one workspace in the
    # original Gap 133 report, and here it would be an adoption, not a lookup.
    domain_tenant = None
    if not email_is_placeholder:
        domain_tenant = db_session.exec(
            select(Tenant).where(Tenant.domain == domain)
        ).first()

    if domain_tenant is not None:
        # Checkpoint 3c: "unclaimed" means empty of everything, not just of
        # users -- see _tenant_adoption_blockers().
        blockers = _tenant_adoption_blockers(db_session, domain_tenant)

        if blockers:
            print(
                "[provision-diag] refusing to adopt domain tenant "
                f"{domain_tenant.id} for org_id={body.clerk_org_id!r}: "
                f"holds {', '.join(blockers)}",
                flush=True,
            )
        else:
            domain_tenant.clerk_org_id = body.clerk_org_id
            domain_tenant.name = body.org_name
            domain_tenant.updated_at = datetime.utcnow()
            db_session.add(domain_tenant)
            try:
                db_session.commit()
                db_session.refresh(domain_tenant)
            except IntegrityError as e:
                # Only reachable if a concurrent request claimed this tenant (or
                # this org id) between the blocker check and the commit -- the
                # narrow TOCTOU window noted in the Checkpoint 3c report, which
                # is NOT otherwise addressed here. Failing over to a fresh
                # isolated tenant is the same safe outcome as "not adoptable",
                # and is at least not a bare 500.
                db_session.rollback()
                print(
                    "[provision-diag] domain-tenant adoption lost a race for "
                    f"org_id={body.clerk_org_id!r}: {e!r}",
                    flush=True,
                )
                domain_tenant = None

            if domain_tenant is not None:
                return TenantProvisionResponse(
                    tenant_id=str(domain_tenant.id),
                    clerk_org_id=domain_tenant.clerk_org_id,
                    org_name=domain_tenant.name,
                    billing_plan=domain_tenant.billing_plan,
                    free_invoices_remaining=domain_tenant.free_invoices_remaining,
                    is_new=False,
                )

    # -----------------------------------------------------------------------
    # BE Gap 133: Pre-check user conflicts BEFORE creating a new Tenant
    # -----------------------------------------------------------------------
    existing_user = db_session.exec(
        select(User).where(User.clerk_user_id == body.clerk_user_id)
    ).first()

    if existing_user and existing_user.tenant_id:
        print(
            f"[provision-diag] user {body.clerk_user_id!r} already belongs to "
            f"tenant {existing_user.tenant_id!r}, refusing second provision for "
            f"org_id={body.clerk_org_id!r}",
            flush=True,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This account is already provisioned to another workspace. "
                "A user cannot belong to multiple workspaces simultaneously. "
                "Contact support if you need to transfer your account."
            ),
        )

    # Pre-check email conflict to avoid creating an orphan tenant on duplicate email
    if not caller.is_mock:
        email_conflict = db_session.exec(
            select(User).where(
                User.email == admin_email,
                User.clerk_user_id != body.clerk_user_id,
            )
        ).first()
        if email_conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "The admin email address is already in use by another account. "
                    f"Contact support with org id {body.clerk_org_id}."
                ),
            )

    new_tenant = _create_tenant_with_unique_domain(db_session, body, domain)

    if not existing_user:
        admin_user = User(
            id=uuid4(),
            tenant_id=new_tenant.id,
            email=admin_email,
            first_name=body.first_name,
            last_name=body.last_name,
            role=RoleMapper.normalize_role("Admin"),
            clerk_user_id=body.clerk_user_id,
            created_at=datetime.utcnow(),
        )
        db_session.add(admin_user)
        # Checkpoint 3c: `User.email` and `User.clerk_user_id` are both globally
        # unique, so this INSERT can conflict -- previously as a bare 500 with
        # the tenant already committed. Binding admin_email to the token (above)
        # removes the deliberate way to trigger it; this handles the rest (a
        # concurrent duplicate sign-up, or an address already held by another
        # tenant's user row).
        try:
            db_session.commit()
        except IntegrityError as e:
            db_session.rollback()
            print(
                "[provision-diag] admin user insert conflict for "
                f"org_id={body.clerk_org_id!r} sub={body.clerk_user_id!r}: {e!r}",
                flush=True,
            )
            concurrent_user = db_session.exec(
                select(User).where(User.clerk_user_id == body.clerk_user_id)
            ).first()
            if concurrent_user is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Your workspace was created, but the admin account could not "
                        "be registered: that email address is already in use by "
                        "another account. Contact support with org id "
                        f"{body.clerk_org_id}."
                    ),
                )
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
