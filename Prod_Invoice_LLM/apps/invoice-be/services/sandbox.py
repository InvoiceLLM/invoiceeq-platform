"""
Feature 25 (Gap 340): sandbox `inv_test_` keys — issuance, claiming, expiry.

WHAT A SANDBOX KEY IS
---------------------
An `inv_test_...` credential handed to an **anonymous website visitor, with no
login**, that resolves to a **fresh, real `Tenant` row** — not a shared demo
tenant. That is the founder's decision, and it is what makes the sandbox worth
having: the visitor uploads their own invoice and sees their own extraction,
in a workspace that a real signup can later **claim** rather than throw away.

Everything else in this module exists because "hand a credential to a stranger"
is an unusually sharp thing for this codebase to do. The five containment
properties, and where each is enforced:

1. **A sandbox tenant can never be adopted.** `Tenant.domain` is the synthetic
   `sandbox-<tenant_id>.invalid` (`sandbox_domain()` below) — `.invalid` is RFC
   2606's reserved never-resolving TLD, the same device
   `routers/auth.py::_create_tenant_with_unique_domain()` already uses for a
   colliding org domain, and the tenant id inside it keeps every value distinct
   against `Tenant.domain`'s UNIQUE constraint. No real company's email domain
   can equal it, so `provision_tenant()`'s domain lookup cannot find one.
   Belt and braces: `_tenant_adoption_blockers()` also refuses any tenant with a
   `SandboxTenant` row, and (since Gap 344) any tenant holding key material at
   all — which a sandbox tenant always does.

2. **Claiming is an explicit, atomic, single-winner transaction** —
   `claim_sandbox_tenant()`, NOT a side effect of the adoption path. It uses the
   same concurrency mechanism `provision_tenant()` uses for ordinary signups:
   `pg_advisory_xact_lock`, re-read under the lock, compare-and-set on
   `claimed_at IS NULL`. The `inv_test_` key is **replaced with a fresh
   `inv_live_` key in that same transaction**, so there is no window in which a
   stranger's sandbox key and the new owner's real access both work.

3. **No `User` row and no `TenantEmailSender` row.** Both `User.email` and
   `TenantEmailSender.email` are *globally* unique columns. Giving a sandbox
   tenant either would let an anonymous visitor squat a real address and turn
   the real owner's later signup into a conflict.
   `dependencies.resolve_api_key_context()` runs fine with `db_user_id=None` at
   readonly scope (it only resolves a service user at `actions` scope, which a
   sandbox tenant can never reach — see 4), so nothing needs a user row.

4. **Permanently pinned to `readonly` scope.** Enforced in three places, on
   purpose: written as `readonly` at creation, re-pinned defensively on every
   authentication in `resolve_api_key_context()`, and refused at
   `PUT /settings/workflow` (which is also structurally unreachable — it is
   Admin-gated on a Clerk session, and property 3 means no user exists who could
   hold one).

5. **A real TTL, and a real reaper.** `expires_at` is checked live at
   authentication, so an expired key stops verifying immediately; and
   `scripts/sweep_sandbox_tenants.py` deletes the workspace outright. Both, not
   either — a soft flag nobody reads is not an expiry.

Issuance is additionally rate-limited per IP and capped globally; see
`routers/sandbox.py` and `unclaimed_sandbox_count()`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select, text

from config import get_settings
from models import SandboxTenant, Tenant
from services.api_keys import (
    generate_api_key,
    generate_salt,
    hash_api_key,
    key_prefix,
)

logger = logging.getLogger(__name__)

# The `Tenant.api_key_scope` a sandbox tenant is pinned to. Imported as a
# literal rather than from dependencies.py to keep this module free of the
# request layer (scripts/sweep_sandbox_tenants.py imports it from a bare
# process); a test asserts the two agree.
SANDBOX_KEY_SCOPE = "readonly"

# Name shown in the product for a sandbox workspace. Deliberately obvious: a
# visitor who later claims it should recognise what they are claiming.
SANDBOX_TENANT_NAME = "Sandbox Workspace"

# Advisory-lock key for the global unclaimed cap. A constant string (hashed by
# Postgres' `hashtext`) so every concurrent issuance serialises on the same
# lock -- otherwise two requests can both read count == cap - 1 and both create.
_SANDBOX_CAP_LOCK_KEY = "sandbox:global-cap"


def sandbox_domain(tenant_id: UUID) -> str:
    """The synthetic, non-matchable `Tenant.domain` for a sandbox tenant.

    `.invalid` is RFC 2606's reserved TLD for a name that must never resolve.
    The tenant id is inside the value because `Tenant.domain` is
    `unique=True, nullable=False`, so every sandbox tenant needs a distinct one.

    This is the single reason a sandbox tenant can never collide with a real
    company's domain-matched signup: `routers/auth.py::provision_tenant()` looks
    a domain tenant up by `admin_email.split("@")[-1]`, and no deliverable
    address a real signup can verify ends in a per-tenant `.invalid` name.
    """
    return f"sandbox-{tenant_id}.invalid"


def is_sandbox_tenant(db_session: Session, tenant_id: UUID) -> SandboxTenant | None:
    """The tenant's sandbox row, or None if it is an ordinary tenant.

    Row existence is the marker. A claimed row still returns here -- callers
    that care about the difference check `claimed_at`, because "was a sandbox"
    and "is an unclaimed sandbox" are different questions and collapsing them
    would either re-lock a claimed workspace or leave an unclaimed one open.
    """
    return db_session.exec(
        select(SandboxTenant).where(SandboxTenant.tenant_id == tenant_id)
    ).first()


def unclaimed_sandbox_count(db_session: Session) -> int:
    """How many sandbox workspaces are currently outstanding and unclaimed.

    The number the global cap is compared against. Counts unclaimed rows
    regardless of expiry: an expired-but-unreaped row still holds a `Tenant`
    row, so counting only live ones would let a reaper outage quietly lift the
    cap.
    """
    return int(
        db_session.exec(
            select(func.count()).select_from(SandboxTenant).where(
                SandboxTenant.claimed_at.is_(None)  # type: ignore[union-attr]
            )
        ).one()
    )


def sandbox_is_expired(sandbox: SandboxTenant, now: datetime | None = None) -> bool:
    """True when this sandbox has passed its TTL and must stop authenticating.

    A **claimed** sandbox is never expired: claiming makes it an ordinary
    workspace with a real owner and a real `inv_live_` key, and the row that
    remains is history. Expiring a claimed workspace would delete a paying
    customer's data, which is the one failure this predicate must not have.
    """
    if sandbox.claimed_at is not None:
        return False
    return sandbox.expires_at <= (now or datetime.utcnow())


def issue_sandbox_tenant(
    db_session: Session,
    raw_key: str,
    issued_from_ip: str | None = None,
) -> tuple[Tenant, SandboxTenant] | None:
    """Create one sandbox workspace and attach `raw_key` to it. Fails closed.

    Returns None when the global unclaimed cap is already reached -- the caller
    turns that into a 503 "temporarily unavailable" rather than issuing past the
    cap. Failing closed here is deliberate: the alternative on an unauthenticated
    endpoint is unbounded tenant creation by whoever is holding the button down.

    THE CAP CHECK IS UNDER AN ADVISORY LOCK, and that is not decoration. Two
    concurrent issuances both reading `count == cap - 1` and both creating is
    exactly the TOCTOU the lock exists to remove; `pg_advisory_xact_lock` is the
    same primitive `provision_tenant()` already relies on, held for the rest of
    the transaction so the count and the insert are one decision. On SQLite the
    lock is a no-op (there is no such function), which is why the cap's
    concurrency behaviour is only claimable against real Postgres.

    Deliberately writes NO `User` row and NO `TenantEmailSender` row -- see the
    module docstring, property 3.
    """
    settings = get_settings()

    if db_session.bind.dialect.name == "postgresql":
        db_session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:cap_key))"),
            {"cap_key": _SANDBOX_CAP_LOCK_KEY},
        )

    if unclaimed_sandbox_count(db_session) >= settings.SANDBOX_MAX_UNCLAIMED_TENANTS:
        logger.warning(
            "sandbox: refusing to issue -- global unclaimed cap of %s reached.",
            settings.SANDBOX_MAX_UNCLAIMED_TENANTS,
        )
        return None

    now = datetime.utcnow()
    tenant_id = uuid4()
    salt = generate_salt()

    tenant = Tenant(
        id=tenant_id,
        name=SANDBOX_TENANT_NAME,
        # The whole adoption-exclusion mechanism. See sandbox_domain().
        domain=sandbox_domain(tenant_id),
        # No Clerk organisation exists for a sandbox -- nobody signed in to
        # create it. Claiming is what attaches one.
        clerk_org_id=None,
        billing_plan="free",
        # Its own limit, not DEFAULT_FREE_INVOICES_LIMIT: a stranger's
        # throwaway workspace and a real free-tier customer are not the same
        # allowance, and tightening one must not tighten the other.
        free_invoices_remaining=settings.SANDBOX_INVOICE_LIMIT,
        api_key_hash=hash_api_key(raw_key, salt),
        api_key_salt=salt,
        api_key_prefix=key_prefix(raw_key),
        api_key_rotated_at=now,
        api_key_last_used_at=None,
        # Written explicitly, not left to the model default -- pinning is a
        # decision this feature makes, not one it inherits.
        api_key_scope=SANDBOX_KEY_SCOPE,
        created_at=now,
        updated_at=now,
    )
    db_session.add(tenant)
    # Flushed before the sandbox row is added, and this is not tidiness.
    # `SandboxTenant.tenant_id` is a real FK to `tenant.id`, and on Postgres the
    # constraint is enforced: without an explicit flush here the two INSERTs went
    # out in the order they were added to the identity map and the sandbox row
    # landed first, producing a ForeignKeyViolation and -- because this function
    # swallows IntegrityError -- a silent `None` return that looked exactly like
    # hitting the global cap. SQLite does not enforce foreign keys by default, so
    # the whole path passed there; it was real Postgres that surfaced it.
    db_session.flush()

    sandbox = SandboxTenant(
        id=uuid4(),
        tenant_id=tenant_id,
        expires_at=now + timedelta(hours=settings.SANDBOX_KEY_TTL_HOURS),
        issued_from_ip=issued_from_ip,
        created_at=now,
    )
    db_session.add(sandbox)

    try:
        db_session.commit()
    except IntegrityError as exc:
        db_session.rollback()
        # Realistically unreachable -- the domain carries a fresh UUID -- so if
        # this fires it is something structural, and refusing is the right
        # answer on an anonymous endpoint.
        logger.error("sandbox: issuance insert conflict: %r", exc)
        return None

    db_session.refresh(tenant)
    db_session.refresh(sandbox)
    logger.info(
        "sandbox: issued tenant=%s prefix=%s expires_at=%s",
        tenant.id, tenant.api_key_prefix, sandbox.expires_at,
    )
    return tenant, sandbox


def locked_sandbox_select(tenant_id: UUID):
    """Statement used by `charge_sandbox_chat_message` — exposed so tests can
    assert `FOR UPDATE`.

    Deliberately the same shape and the same name-ending as
    `services/billing_quota.py::locked_tenant_select()`: this repo already has
    one working, tested idiom for "read-check-write an allowance under
    concurrency", and a second spelling of it would be a second thing to get
    wrong.
    """
    return (
        select(SandboxTenant)
        .where(SandboxTenant.tenant_id == tenant_id)
        .with_for_update()
    )


def charge_sandbox_chat_message(db_session: Session, tenant_id: UUID) -> dict | None:
    """Gap 340 requirement 7: meter one chat turn for a sandbox tenant.

    Returns None for an ordinary tenant (nothing to meter) or a claimed sandbox
    (it is an ordinary tenant now). Otherwise returns
    `{"used": int, "limit": int, "allowed": bool}`; the caller turns
    `allowed=False` into a 402.

    ------------------------------------------------------------------------
    THE ROW LOCK, AND WHY THE ARGUMENT AGAINST IT WAS WRONG (Gap 352)
    ------------------------------------------------------------------------
    This function shipped with a comment arguing it did not need
    `charge_free_quota()`'s `SELECT ... FOR UPDATE`, because "the worst case of
    a lost update is one extra chat turn — not money". That reasoning holds for
    exactly **two** racers. For N concurrent requests all reading the counter
    before any of them writes it back, the loss is **N-1 turns**, and N is the
    caller's choice, not a fixed small number. A visitor holding one
    `inv_test_` key can fire as many concurrent requests as they like.

    Measured against real Postgres before the lock was added: limit 5, 24
    concurrent requests off one key -> **22 turns allowed**, counter left at 5.
    The 25-message allowance — the single control that stops an anonymous
    stranger reaching unmetered Azure OpenAI spend — bounded nothing.

    So this now does what `services/billing_quota.py::charge_free_quota()` does,
    with the same idiom rather than a new one:

      1. an unlocked pre-check, purely to return early for an ordinary tenant
         (which is every tenant on every chat turn) without taking a lock;
      2. `SELECT ... FOR UPDATE` on the `SandboxTenant` row —
         `locked_sandbox_select()`;
      3. a **re-read under the lock** with `populate_existing=True`, which is
         load-bearing for the same reason it is in `charge_free_quota()` and
         `claim_sandbox_tenant()`: without it SQLAlchemy hands back the instance
         already in the identity map with its pre-lock attribute values, so the
         lock would hold while the limit check read stale state;
      4. the limit check and the increment, both under that lock, committed
         together.

    The increment is still computed in Python rather than as `SET col = col + 1`
    on purpose: the check and the write must be one decision, and an atomic
    increment alone would still let a request past a spent allowance. The lock
    is what makes them one decision.

    AND THE VALUE RETURNED IS CAPTURED UNDER THAT LOCK TOO (Gap 353). `commit()`
    releases the lock, so a read taken after it — which is what the original
    `db_session.refresh(sandbox)` was — is an ordinary unlocked read that another
    request's commit may already have moved. The bound never broke (that is
    steps 2–4's job), but two concurrent callers could each be handed the same
    `used` position while a position in between was reported to nobody. The
    reported number now comes from a local captured between the increment and
    the commit, which is this request's position by construction.

    On SQLite `with_for_update()` renders nothing, so the ordering guarantee is
    only claimable against real Postgres — see
    `tests/test_sandbox_keys.py::test_concurrent_chat_charges_cannot_exceed_the_allowance_on_postgres`.

    The increment happens BEFORE the answer is generated, on purpose: metering
    after the model call means a caller who disconnects mid-turn has spent real
    Azure OpenAI money and been charged nothing.
    """
    # (1) Unlocked pre-check. Only ever *narrows*: an ordinary tenant cannot
    # become a sandbox, and a claimed sandbox cannot become unclaimed, so a
    # None here can never be a missed charge. Its whole purpose is to keep the
    # common path (every non-sandbox chat turn in the product) lock-free.
    if (pre := is_sandbox_tenant(db_session, tenant_id)) is None or pre.claimed_at is not None:
        return None

    # (2)+(3) Lock the row, then re-read it under that lock.
    sandbox = db_session.exec(
        locked_sandbox_select(tenant_id).execution_options(populate_existing=True)
    ).first()
    # Both re-checked under the lock rather than trusted from the pre-check: a
    # concurrent claim or a reaper delete can land in between.
    if sandbox is None or sandbox.claimed_at is not None:
        return None

    # (4) Check and increment, together, under the lock.
    limit = get_settings().SANDBOX_CHAT_MESSAGE_LIMIT
    if sandbox.chat_messages_used >= limit:
        # No rollback here, deliberately: this returns into a caller that raises
        # 402 immediately, and the lock is released when the request's session
        # closes. Byte-for-byte the same behaviour `charge_free_quota()` has on
        # its own 402 branch. Rolling back would make this function able to
        # discard a future caller's uncommitted work, which is a worse trade
        # than holding one row for the rest of a request that is already over.
        return {"used": sandbox.chat_messages_used, "limit": limit, "allowed": False}

    sandbox.chat_messages_used += 1
    # Gap 353: capture the number to REPORT here, while the lock is still held.
    # `commit()` is what releases the `FOR UPDATE` lock, so anything read after
    # it is a fresh, unlocked read of a row another request may already have
    # advanced. The previous version returned `sandbox.chat_messages_used` after
    # a post-commit `db_session.refresh(sandbox)`, and under concurrency two
    # callers could land in each other's commit/refresh window and both be told
    # the same position (observed: five granted turns reporting 1, 2, 3, 5, 5 --
    # nobody was told 4). The counter itself was always correct and the limit was
    # always bounded, because the check and the increment are one decision under
    # the lock; only the number handed back to the caller was unreliable.
    # This local IS this request's position in the allowance by construction: it
    # is computed from the value re-read under this lock, so no other transaction
    # can have incremented in between.
    charged_used = sandbox.chat_messages_used
    db_session.add(sandbox)
    db_session.commit()
    # No `refresh()` -- deliberately. It is the read that caused Gap 353, and
    # there is nothing left to refresh for: `charged_used` is already the value
    # this request wrote, and the ORM instance is not used again after this
    # return. (`charge_free_quota()` refreshes because it returns the live Tenant
    # instance itself for the caller to keep using; this function returns a plain
    # dict, so it has no such obligation.)
    return {"used": charged_used, "limit": limit, "allowed": True}


class SandboxClaimError(Exception):
    """A claim that cannot proceed, with a caller-safe reason.

    `code` is the machine-readable half (`not_found`, `expired`,
    `already_claimed`) so the router can pick a status without parsing prose.
    """

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def claim_sandbox_tenant(
    db_session: Session,
    sandbox: SandboxTenant,
    clerk_org_id: str,
    org_name: str,
) -> tuple[Tenant, str]:
    """Promote a sandbox workspace into a real one. Atomic, single-winner.

    Returns `(tenant, raw_live_key)`. Raises `SandboxClaimError` when the
    sandbox cannot be claimed.

    ------------------------------------------------------------------------
    WHY THIS IS ITS OWN TRANSACTION AND NOT PART OF THE ADOPTION PATH
    ------------------------------------------------------------------------
    `routers/auth.py`'s domain-adoption branch is a *heuristic*: it guesses that
    an empty domain-matched tenant probably belongs to whoever is signing up.
    Gap 133 and Gap 344 are both records of that guess being dangerous, and
    `_tenant_adoption_blockers()` is deliberately strict as a result. Claiming a
    sandbox is the opposite kind of act — the caller is *proving possession of
    the sandbox key*, which is a specific claim on one specific workspace. Those
    two must not share a code path: widening adoption to admit sandboxes would
    reintroduce exactly the takeover surface Gap 344 just closed.

    THE CONCURRENCY MECHANISM, which is the whole point of the function.
    Same shape `provision_tenant()` already uses:

      1. `pg_advisory_xact_lock(hashtext(<sandbox tenant id>))` serialises every
         claim attempt for THIS sandbox (a no-op on SQLite, which is why the
         race can only be proven against real Postgres);
      2. the row is **re-read under the lock**, so a decision is never made on
         state read before the lock was held;
      3. the write is a **compare-and-set on `claimed_at IS NULL`** — the
         explicit "unclaimed" predicate — so the loser sees `already_claimed`
         rather than silently overwriting the winner.

    THE KEY SWAP IS IN THE SAME TRANSACTION, and that is a requirement, not an
    optimisation. Attaching the real Clerk org in one commit and rotating the
    key in another leaves a window in which a stranger's `inv_test_` key and the
    new owner's workspace coexist. `services/api_keys.py` is one-key-per-tenant
    by design, so overwriting hash+salt+prefix IS the revocation — there is
    nothing left to verify the sandbox digest against from the next request on.
    """
    tenant_id = sandbox.tenant_id

    if db_session.bind.dialect.name == "postgresql":
        db_session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:sandbox_key))"),
            {"sandbox_key": f"sandbox:claim:{tenant_id}"},
        )

    # (2) Re-read under the lock. `populate_existing` for the same reason
    # services/billing_quota.py needs it: without it SQLAlchemy hands back the
    # instance already in the identity map with its pre-lock attribute values,
    # so the lock would hold while the predicate below was evaluated against
    # stale state.
    fresh = db_session.exec(
        select(SandboxTenant)
        .where(SandboxTenant.tenant_id == tenant_id)
        .execution_options(populate_existing=True)
    ).first()
    if fresh is None:
        raise SandboxClaimError("not_found", "This sandbox workspace no longer exists.")

    # (3) The compare-and-set predicate.
    if fresh.claimed_at is not None:
        raise SandboxClaimError(
            "already_claimed",
            "This sandbox workspace has already been claimed by another account.",
        )
    if sandbox_is_expired(fresh):
        raise SandboxClaimError(
            "expired",
            "This sandbox workspace has expired. Start a new sandbox or sign up "
            "normally -- a fresh workspace will be created for you.",
        )

    tenant = db_session.exec(
        select(Tenant)
        .where(Tenant.id == tenant_id)
        .execution_options(populate_existing=True)
    ).first()
    if tenant is None:
        raise SandboxClaimError("not_found", "This sandbox workspace no longer exists.")

    now = datetime.utcnow()
    raw_live_key = generate_api_key()
    salt = generate_salt()

    tenant.clerk_org_id = clerk_org_id
    tenant.name = org_name
    # The domain stays synthetic, and stays a `.invalid` name. Rewriting it to
    # the claimer's real email domain would (a) risk colliding with
    # `Tenant.domain`'s UNIQUE constraint against a tenant that already holds it,
    # turning a successful claim into a 500, and (b) make this workspace a
    # domain-adoption target for the *next* signup from that domain -- which is
    # the takeover surface Gap 133/344 exist to close. `org-<org_id>.invalid` is
    # the same fallback shape `_create_tenant_with_unique_domain()` already uses.
    tenant.domain = f"org-{clerk_org_id}.invalid"
    # THE KEY SWAP -- same commit as everything above. This is what revokes the
    # `inv_test_` key.
    tenant.api_key_hash = hash_api_key(raw_live_key, salt)
    tenant.api_key_salt = salt
    tenant.api_key_prefix = key_prefix(raw_live_key)
    tenant.api_key_rotated_at = now
    tenant.api_key_last_used_at = None
    # Still fail-closed on claim: a workspace does not acquire `actions` scope
    # by being claimed. Widening stays an explicit act via PUT /settings/workflow.
    tenant.api_key_scope = SANDBOX_KEY_SCOPE
    tenant.updated_at = now

    fresh.claimed_at = now
    fresh.claimed_by_clerk_org_id = clerk_org_id

    db_session.add(tenant)
    db_session.add(fresh)
    try:
        db_session.commit()
    except IntegrityError as exc:
        db_session.rollback()
        # The realistic cause is `clerk_org_id`'s UNIQUE constraint: this org
        # already has a workspace, so claiming a second one is not something to
        # resolve by picking a winner.
        logger.warning(
            "sandbox: claim conflict for tenant=%s org=%s: %r", tenant_id, clerk_org_id, exc
        )
        raise SandboxClaimError(
            "already_claimed",
            "This organisation already has a workspace, so the sandbox was not "
            "claimed. Sign in to the existing workspace instead.",
        ) from exc

    db_session.refresh(tenant)
    logger.info(
        "sandbox: tenant=%s claimed by org=%s; sandbox key replaced (new prefix=%s)",
        tenant_id, clerk_org_id, tenant.api_key_prefix,
    )
    return tenant, raw_live_key


def expired_unclaimed_sandboxes(
    db_session: Session, now: datetime | None = None
) -> list[SandboxTenant]:
    """Every unclaimed sandbox past its TTL — the reaper's work list."""
    cutoff = now or datetime.utcnow()
    return list(
        db_session.exec(
            select(SandboxTenant).where(
                SandboxTenant.claimed_at.is_(None),  # type: ignore[union-attr]
                SandboxTenant.expires_at <= cutoff,
            )
        ).all()
    )
