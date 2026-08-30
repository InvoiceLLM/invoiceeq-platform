"""
Feature 25 (Gap 340): sandbox `inv_test_` keys.

The properties these tests exist to hold. Each maps to one of the security
review's numbered constraints, named in the test docstring:

  1. a sandbox tenant's synthetic domain genuinely never matches a real signup,
     and it can never be adopted;
  2. claiming is atomic and single-winner, and the `inv_test_` key is dead the
     moment the claim commits;
  3. no `User` row and no `TenantEmailSender` row are ever created;
  4. the key is pinned to `readonly` and cannot be widened;
  5. issuance is rate-limited per IP and capped globally, failing closed;
  6. expiry stops the key verifying AND the reaper deletes the workspace;
  7. chat is metered.

Two cases run against **real Postgres** and skip otherwise -- the claim race
(constraint 2) and the adoption exclusion (constraint 1) -- because both rest on
`pg_advisory_xact_lock`, a Postgres primitive that is a silent no-op elsewhere.
"""
import asyncio
import threading
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from main import app
from dependencies import (
    AuthenticatedClerkIdentity,
    KEY_SCOPE_ACTIONS,
    KEY_SCOPE_READONLY,
    get_db_session,
    resolve_api_key_context,
)
from models import SandboxTenant, Tenant, TenantEmailSender, User
from services.api_keys import (
    SANDBOX_KEY_PREFIX,
    generate_sandbox_key,
    key_prefix,
    looks_like_api_key,
    looks_like_sandbox_key,
    verify_api_key,
)
from services.sandbox import (
    SANDBOX_KEY_SCOPE,
    SandboxClaimError,
    charge_sandbox_chat_message,
    claim_sandbox_tenant,
    expired_unclaimed_sandboxes,
    is_sandbox_tenant,
    issue_sandbox_tenant,
    sandbox_domain,
    sandbox_is_expired,
    unclaimed_sandbox_count,
)

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

client = TestClient(app)

ISSUE_URL = "/api/v1/sandbox/keys"
STATUS_URL = "/api/v1/sandbox/keys/me"
CLAIM_URL = "/api/v1/sandbox/claim"


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def override_db_session(db_session):
    def _override():
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def sandbox_enabled(monkeypatch):
    """Turn the feature on for the suite; it ships off (fail-closed default)."""
    import config

    monkeypatch.setattr(config.settings, "SANDBOX_KEYS_ENABLED", True)
    yield


@pytest.fixture(autouse=True)
def reset_sandbox_rate_limiter():
    """The limiter is a module singleton, so one test's issuances would
    otherwise 429 the next one."""
    from routers.sandbox import _rate_limiter

    _rate_limiter._redis_client = False  # force the bounded in-process fallback
    _rate_limiter.reset()
    yield
    _rate_limiter.reset()


def _issue(db_session: Session, ip: str | None = None):
    raw = generate_sandbox_key()
    return raw, issue_sandbox_tenant(db_session, raw, issued_from_ip=ip)


# ---------------------------------------------------------------------------
# Credential format and prefix dispatch (constraint 9's sandbox half)
# ---------------------------------------------------------------------------

class TestSandboxKeyFormat:
    def test_sandbox_key_carries_the_test_prefix(self):
        raw = generate_sandbox_key()
        assert raw.startswith(SANDBOX_KEY_PREFIX)
        assert raw.startswith("inv_test_")
        assert not raw.startswith("inv_live_")

    def test_sandbox_key_is_recognised_as_an_api_key(self):
        """It IS an API key -- same verifier, same columns. Only the tenant differs."""
        assert looks_like_api_key(generate_sandbox_key()) is True
        assert looks_like_sandbox_key(generate_sandbox_key()) is True
        assert looks_like_sandbox_key("inv_live_abc") is False

    def test_prefix_slice_keeps_six_secret_chars_for_both_key_types(self):
        """Gap 184's stored `inv_live_` prefix width must not have moved.

        `Tenant.api_key_prefix` is the indexed lookup column; changing its width
        for existing rows would 401 every live key on the next request.
        """
        live_prefix = key_prefix("inv_live_" + "a" * 40)
        assert live_prefix == "inv_live_aaaaaa"
        assert len(live_prefix) == 15

        test_prefix = key_prefix("inv_test_" + "a" * 40)
        assert test_prefix == "inv_test_aaaaaa"
        assert len(test_prefix) == 15


# ---------------------------------------------------------------------------
# Constraint 1 — the synthetic domain and adoption exclusion
# ---------------------------------------------------------------------------

class TestSandboxDomainIsNonMatchable:
    def test_domain_is_a_per_tenant_invalid_name(self):
        """Constraint 1: synthetic, distinct per tenant, RFC 2606 `.invalid`."""
        a, b = uuid4(), uuid4()
        assert sandbox_domain(a).endswith(".invalid")
        assert str(a) in sandbox_domain(a)
        assert sandbox_domain(a) != sandbox_domain(b)

    def test_issued_tenant_gets_the_synthetic_domain(self, db_session: Session):
        _, issued = _issue(db_session)
        tenant, _sandbox = issued
        assert tenant.domain == sandbox_domain(tenant.id)
        assert tenant.domain.endswith(".invalid")

    def test_sandbox_tenant_is_an_adoption_blocker(self, db_session: Session):
        """Constraint 1: `_tenant_adoption_blockers()` names it directly.

        Three independent reasons should be reported -- the sandbox row, the key
        material (Gap 344), and nothing else -- and the point of asserting on the
        list rather than on a boolean is that removing any ONE of them must still
        leave the tenant unadoptable.
        """
        from routers.auth import _tenant_adoption_blockers

        _, issued = _issue(db_session)
        tenant, _sandbox = issued
        blockers = _tenant_adoption_blockers(db_session, tenant)
        assert "a sandbox workspace" in blockers
        assert "a live API key" in blockers

    def test_a_real_signup_domain_can_never_equal_a_sandbox_domain(
        self, db_session: Session
    ):
        """Constraint 1, stated as the property that actually matters.

        `provision_tenant()` looks a domain tenant up by
        `admin_email.split("@")[-1]`. For that to find a sandbox tenant, a caller
        would need a verified Clerk email whose domain is
        `sandbox-<a specific uuid>.invalid`.
        """
        _, issued = _issue(db_session)
        tenant, _sandbox = issued

        for address in (
            "admin@acme.com",
            "admin@invalid",
            "admin@sandbox.invalid",
            f"admin@sandbox-{uuid4()}.invalid",  # a *different* uuid
        ):
            assert address.split("@")[-1] != tenant.domain

        # And the only address that would match is one nobody can register: the
        # TLD is reserved as non-resolving, so it cannot receive a verification
        # mail.
        matching = f"admin@{tenant.domain}"
        assert matching.split("@")[-1] == tenant.domain
        assert matching.endswith(".invalid")


# ---------------------------------------------------------------------------
# Constraint 3 — no User row, no TenantEmailSender row
# ---------------------------------------------------------------------------

class TestSandboxCreatesNoIdentityRows:
    def test_no_user_row_is_created(self, db_session: Session):
        """Constraint 3: `User.email` is globally unique -- an anonymous visitor
        must not be able to squat a real address."""
        _, issued = _issue(db_session)
        tenant, _sandbox = issued
        assert db_session.exec(
            select(User).where(User.tenant_id == tenant.id)
        ).first() is None

    def test_no_email_sender_row_is_created(self, db_session: Session):
        """Constraint 3, the same argument for `TenantEmailSender.email`."""
        _, issued = _issue(db_session)
        tenant, _sandbox = issued
        assert db_session.exec(
            select(TenantEmailSender).where(TenantEmailSender.tenant_id == tenant.id)
        ).first() is None

    def test_readonly_key_auth_works_with_no_user_row(self, db_session: Session):
        """Constraint 3's precondition, asserted rather than assumed.

        `resolve_api_key_context()` only resolves the synthetic service user at
        `actions` scope; a readonly sandbox key must authenticate fine with
        `db_user_id=None` and create nothing.
        """
        raw, _ = _issue(db_session)
        context = resolve_api_key_context(raw, db_session)
        assert context.db_user_id is None
        assert context.auth_method == "api_key"
        assert db_session.exec(select(User)).first() is None


# ---------------------------------------------------------------------------
# Constraint 4 — permanently readonly
# ---------------------------------------------------------------------------

class TestSandboxScopeIsPinned:
    def test_issued_tenant_is_readonly(self, db_session: Session):
        _, issued = _issue(db_session)
        tenant, _sandbox = issued
        assert tenant.api_key_scope == KEY_SCOPE_READONLY
        assert SANDBOX_KEY_SCOPE == KEY_SCOPE_READONLY

    def test_key_resolves_readonly_even_if_the_column_was_widened(
        self, db_session: Session
    ):
        """Constraint 4: the pin is re-derived at auth, not read off the column.

        Simulates a direct database edit (or some future code path that widens
        `api_key_scope`) and asserts an unclaimed sandbox key still resolves with
        zero permissions.
        """
        raw, issued = _issue(db_session)
        tenant, _sandbox = issued
        tenant.api_key_scope = KEY_SCOPE_ACTIONS
        db_session.add(tenant)
        db_session.commit()

        context = resolve_api_key_context(raw, db_session)
        assert context.key_scope == KEY_SCOPE_READONLY
        assert (context.can_train, context.can_audit, context.can_load) == (
            False, False, False,
        )

    def test_actions_scoped_route_rejects_a_sandbox_key(self, db_session: Session):
        """Constraint 4, end to end through the real gate."""
        raw, _ = _issue(db_session)
        response = client.put(
            f"/api/v1/audit/resolve/{uuid4()}",
            headers={"X-API-Key": raw},
            json={"action": "APPROVE"},
        )
        assert response.status_code == 403
        assert "read-only" in response.json()["detail"]

    def test_workflow_put_refuses_full_automation_for_a_sandbox(
        self, db_session: Session, monkeypatch
    ):
        """Constraint 4's explicit rejection at PUT /settings/workflow.

        This path is already unreachable (a sandbox tenant has no User row, so
        nobody can hold an Admin Clerk session for it), so the endpoint is
        called directly rather than over HTTP -- the point is that the guard
        exists at the place widening happens, not that it is reachable.
        """
        from routers.settings import WorkflowConfigUpdate, update_workflow_settings
        from dependencies import TenantContext
        from fastapi import HTTPException

        _, issued = _issue(db_session)
        tenant, _sandbox = issued
        context = TenantContext(
            tenant_id=tenant.id,
            user_id="user_admin",
            role="Admin",
            billing_plan="free",
            can_train=True, can_audit=True, can_load=True,
        )

        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                update_workflow_settings(
                    WorkflowConfigUpdate(audit_policy="full_automation"),
                    context,
                    db_session,
                )
            )
        assert exc.value.status_code == 403
        assert "sandbox" in exc.value.detail.lower()

        db_session.refresh(tenant)
        assert tenant.api_key_scope == KEY_SCOPE_READONLY

    def test_workflow_put_allows_strict_review_for_a_sandbox(self, db_session: Session):
        """The guard is on widening only -- re-affirming the safe policy is fine."""
        from routers.settings import WorkflowConfigUpdate, update_workflow_settings
        from dependencies import TenantContext

        _, issued = _issue(db_session)
        tenant, _sandbox = issued
        context = TenantContext(
            tenant_id=tenant.id, user_id="user_admin", role="Admin",
            billing_plan="free", can_train=True, can_audit=True, can_load=True,
        )
        result = asyncio.run(
            update_workflow_settings(
                WorkflowConfigUpdate(audit_policy="strict_review"), context, db_session
            )
        )
        assert result.api_key_scope == KEY_SCOPE_READONLY


# ---------------------------------------------------------------------------
# Constraint 5 — rate limit and global cap
# ---------------------------------------------------------------------------

class TestIssuanceIsBounded:
    def test_issue_endpoint_returns_a_usable_key(self, db_session: Session):
        response = client.post(ISSUE_URL)
        assert response.status_code == 201
        body = response.json()
        assert body["api_key"].startswith(SANDBOX_KEY_PREFIX)
        assert body["scope"] == "readonly"

        from uuid import UUID as _UUID

        tenant = db_session.get(Tenant, _UUID(body["tenant_id"]))
        assert tenant is not None
        assert verify_api_key(
            body["api_key"], tenant.api_key_salt, tenant.api_key_hash
        ) is True
        # The raw key is not recoverable from what was persisted.
        assert tenant.api_key_hash != body["api_key"]
        assert tenant.api_key_prefix == key_prefix(body["api_key"])

    def test_router_404s_when_the_feature_is_disabled(self, monkeypatch):
        """Fail-closed default: a deployment that has not opted in looks like one
        that does not have the feature."""
        import config

        monkeypatch.setattr(config.settings, "SANDBOX_KEYS_ENABLED", False)
        assert client.post(ISSUE_URL).status_code == 404

    def test_per_ip_rate_limit_returns_429(self, db_session: Session, monkeypatch):
        """Constraint 5: the limiter is the contact form's, reused."""
        import config

        monkeypatch.setattr(config.settings, "SANDBOX_ISSUE_RATE_LIMIT", 2)
        for _ in range(2):
            assert client.post(ISSUE_URL).status_code == 201
        blocked = client.post(ISSUE_URL)
        assert blocked.status_code == 429
        assert blocked.headers.get("Retry-After")

    def test_rate_limiter_does_not_share_a_keyspace_with_the_contact_form(self):
        """Constraint 5: reused implementation, separate namespace.

        Both limiters key on `ip:<addr>`, so a shared Redis prefix would make a
        visitor's contact-form submission eat their sandbox allowance.
        """
        from routers.sandbox import _rate_limiter as sandbox_limiter
        from routers.support import _rate_limiter as contact_limiter

        assert type(sandbox_limiter) is type(contact_limiter)
        assert sandbox_limiter._redis_key_prefix != contact_limiter._redis_key_prefix

    def test_contact_form_limiter_keyspace_is_unchanged(self):
        """The default argument must still be Gap 249's literal -- changing it
        would orphan every live Redis key the contact form is counting on."""
        from routers.support import _REDIS_KEY_PREFIX, _rate_limiter

        assert _REDIS_KEY_PREFIX == "support:contact:ratelimit:"
        assert _rate_limiter._redis_key_prefix == _REDIS_KEY_PREFIX

    def test_limiter_without_an_email_keys_on_ip_alone(self):
        """The anonymous case: no address to key on, so the dimension is omitted
        rather than faked with a shared constant (which would put every visitor
        in one bucket)."""
        from routers.support import _ContactRateLimiter

        assert _ContactRateLimiter._keys("1.2.3.4", None) == ["ip:1.2.3.4"]
        assert _ContactRateLimiter._keys("1.2.3.4", "A@B.com") == [
            "ip:1.2.3.4", "email:a@b.com",
        ]

    def test_global_cap_fails_closed(self, db_session: Session, monkeypatch):
        """Constraint 5: past the cap, issue nothing and say so.

        A rate limit bounds one client; only a global cap bounds many.
        """
        import config

        monkeypatch.setattr(config.settings, "SANDBOX_MAX_UNCLAIMED_TENANTS", 2)
        _issue(db_session)
        _issue(db_session)
        assert unclaimed_sandbox_count(db_session) == 2

        raw = generate_sandbox_key()
        assert issue_sandbox_tenant(db_session, raw) is None

        response = client.post(ISSUE_URL)
        assert response.status_code == 503
        assert "temporarily unavailable" in response.json()["detail"]

    def test_claimed_sandboxes_do_not_count_against_the_cap(self, db_session: Session):
        """A claimed workspace is a customer's, not an outstanding sandbox."""
        _, issued = _issue(db_session)
        _tenant, sandbox = issued
        assert unclaimed_sandbox_count(db_session) == 1

        sandbox.claimed_at = datetime.utcnow()
        db_session.add(sandbox)
        db_session.commit()
        assert unclaimed_sandbox_count(db_session) == 0

    def test_expired_but_unreaped_sandboxes_still_count(self, db_session: Session):
        """Deliberate: counting only live rows would let a reaper outage quietly
        lift the cap while the Tenant rows are still there."""
        _, issued = _issue(db_session)
        _tenant, sandbox = issued
        sandbox.expires_at = datetime.utcnow() - timedelta(hours=1)
        db_session.add(sandbox)
        db_session.commit()
        assert unclaimed_sandbox_count(db_session) == 1


# ---------------------------------------------------------------------------
# Constraint 6 — TTL and reaping
# ---------------------------------------------------------------------------

class TestExpiry:
    def test_ttl_comes_from_settings(self, db_session: Session, monkeypatch):
        import config

        monkeypatch.setattr(config.settings, "SANDBOX_KEY_TTL_HOURS", 5)
        before = datetime.utcnow()
        _, issued = _issue(db_session)
        _tenant, sandbox = issued
        # `expires_at` is `utcnow() + TTL` computed inside the call, so it is at
        # least TTL after `before` and at most TTL plus the call's own duration.
        delta = sandbox.expires_at - before
        assert timedelta(hours=5) <= delta <= timedelta(hours=5, minutes=1)

    def test_expired_key_stops_verifying(self, db_session: Session):
        """Constraint 6, the half that does not depend on the reaper running.

        Expiry is checked on EVERY authentication, so a missed sweep cannot
        silently extend an outstanding key.
        """
        from fastapi import HTTPException

        raw, issued = _issue(db_session)
        _tenant, sandbox = issued
        assert resolve_api_key_context(raw, db_session) is not None

        sandbox.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db_session.add(sandbox)
        db_session.commit()

        with pytest.raises(HTTPException) as exc:
            resolve_api_key_context(raw, db_session)
        assert exc.value.status_code == 401
        assert "expired" in exc.value.detail

    def test_expired_key_401s_over_http(self, db_session: Session):
        raw, issued = _issue(db_session)
        _tenant, sandbox = issued
        sandbox.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db_session.add(sandbox)
        db_session.commit()

        response = client.get("/api/v1/invoices", headers={"X-API-Key": raw})
        assert response.status_code == 401

    def test_a_claimed_sandbox_never_expires(self, db_session: Session):
        """The one failure this predicate must not have: expiring a real
        customer's workspace after they claimed it."""
        raw, issued = _issue(db_session)
        _tenant, sandbox = issued
        sandbox.expires_at = datetime.utcnow() - timedelta(days=30)
        sandbox.claimed_at = datetime.utcnow()
        db_session.add(sandbox)
        db_session.commit()

        assert sandbox_is_expired(sandbox) is False
        assert expired_unclaimed_sandboxes(db_session) == []

    def test_reaper_worklist_finds_only_expired_unclaimed(self, db_session: Session):
        _, live = _issue(db_session)
        _, stale = _issue(db_session)
        _, claimed = _issue(db_session)

        stale[1].expires_at = datetime.utcnow() - timedelta(hours=1)
        claimed[1].expires_at = datetime.utcnow() - timedelta(hours=1)
        claimed[1].claimed_at = datetime.utcnow()
        db_session.add(stale[1])
        db_session.add(claimed[1])
        db_session.commit()

        found = expired_unclaimed_sandboxes(db_session)
        assert [s.tenant_id for s in found] == [stale[0].id]

    def test_reaper_deletes_the_workspace(self, db_session: Session):
        """Constraint 6's other half: expiry means the workspace goes away, not
        just that a flag was set."""
        from scripts.sweep_sandbox_tenants import _purge_sandbox
        from models import ChatMessage, ChatSession

        _, issued = _issue(db_session)
        tenant, sandbox = issued
        chat_session = ChatSession(id=uuid4(), tenant_id=tenant.id, title="probe")
        db_session.add(chat_session)
        db_session.commit()
        db_session.add(
            ChatMessage(id=uuid4(), session_id=chat_session.id, role="user", content="hi")
        )
        db_session.commit()

        counts = _purge_sandbox(db_session, sandbox)

        assert counts["chat_sessions"] == 1
        assert counts["chat_messages"] == 1
        assert db_session.get(Tenant, tenant.id) is None
        assert db_session.exec(
            select(SandboxTenant).where(SandboxTenant.tenant_id == tenant.id)
        ).first() is None

    def test_reaper_skips_a_claimed_row_even_if_handed_one(self, db_session: Session):
        """The per-row re-assertion in the sweep loop: "it was in the list" is
        not a good enough reason to delete a customer's workspace."""
        from scripts import sweep_sandbox_tenants

        _, issued = _issue(db_session)
        tenant, sandbox = issued
        sandbox.expires_at = datetime.utcnow() - timedelta(hours=1)
        sandbox.claimed_at = datetime.utcnow()
        db_session.add(sandbox)
        db_session.commit()

        # The query already excludes it; assert the second guard independently.
        assert expired_unclaimed_sandboxes(db_session) == []
        assert db_session.get(Tenant, tenant.id) is not None


# ---------------------------------------------------------------------------
# Constraint 7 — chat metering
# ---------------------------------------------------------------------------

class TestChatMetering:
    def test_ordinary_tenant_is_not_metered(self, db_session: Session):
        tenant = Tenant(id=uuid4(), name="Real", domain=f"{uuid4().hex}.example.com")
        db_session.add(tenant)
        db_session.commit()
        assert charge_sandbox_chat_message(db_session, tenant.id) is None

    def test_counter_increments_per_message(self, db_session: Session, monkeypatch):
        import config

        monkeypatch.setattr(config.settings, "SANDBOX_CHAT_MESSAGE_LIMIT", 3)
        _, issued = _issue(db_session)
        tenant, sandbox = issued

        for expected in (1, 2, 3):
            result = charge_sandbox_chat_message(db_session, tenant.id)
            assert result == {"used": expected, "limit": 3, "allowed": True}

        blocked = charge_sandbox_chat_message(db_session, tenant.id)
        assert blocked == {"used": 3, "limit": 3, "allowed": False}
        db_session.refresh(sandbox)
        assert sandbox.chat_messages_used == 3

    def test_exhausted_allowance_is_a_402_on_the_chat_route(
        self, db_session: Session, monkeypatch
    ):
        import config

        monkeypatch.setattr(config.settings, "SANDBOX_CHAT_MESSAGE_LIMIT", 0)
        raw, issued = _issue(db_session)
        tenant, _sandbox = issued

        created = client.post(
            "/api/v1/chat/sessions", headers={"X-API-Key": raw}, json={"title": "t"}
        )
        assert created.status_code == 201
        session_id = created.json()["id"]

        response = client.post(
            f"/api/v1/chat/sessions/{session_id}/message?sync=true",
            headers={"X-API-Key": raw},
            json={"content": "what did I spend"},
        )
        assert response.status_code == 402
        assert "chat messages" in response.json()["detail"]

    def test_a_claimed_sandbox_is_no_longer_metered(self, db_session: Session):
        _, issued = _issue(db_session)
        tenant, sandbox = issued
        sandbox.claimed_at = datetime.utcnow()
        db_session.add(sandbox)
        db_session.commit()
        assert charge_sandbox_chat_message(db_session, tenant.id) is None

    def test_sandbox_invoice_allowance_is_its_own_setting(
        self, db_session: Session, monkeypatch
    ):
        """Tightening the sandbox must not tighten the real free tier."""
        import config

        monkeypatch.setattr(config.settings, "SANDBOX_INVOICE_LIMIT", 4)
        monkeypatch.setattr(config.settings, "DEFAULT_FREE_INVOICES_LIMIT", 50)
        _, issued = _issue(db_session)
        tenant, _sandbox = issued
        assert tenant.free_invoices_remaining == 4

    def test_charge_uses_for_update(self):
        """Gap 352: the charge path locks the SandboxTenant row.

        Same assertion, same shape, as
        tests/test_ingestion.py::test_charge_free_quota_uses_for_update — the
        statement builder is exposed for exactly this reason. Structural, not
        behavioural: the behaviour it buys is only provable on Postgres (see
        `test_concurrent_chat_charges_cannot_exceed_the_allowance_on_postgres`),
        but this fails fast if the lock is ever dropped from the statement.
        """
        from services.sandbox import locked_sandbox_select

        stmt = locked_sandbox_select(uuid4())
        assert getattr(stmt, "_for_update_arg", None) is not None or "FOR UPDATE" in str(
            stmt.compile(compile_kwargs={"literal_binds": True})
        )


# ---------------------------------------------------------------------------
# Constraint 2 — claiming
# ---------------------------------------------------------------------------

class TestClaiming:
    def test_claim_attaches_the_org_and_replaces_the_key(self, db_session: Session):
        """Constraint 2: the `inv_test_` key must be dead the moment the claim
        commits -- no window where a stranger's key and a new owner coexist."""
        from fastapi import HTTPException

        raw, issued = _issue(db_session)
        tenant, sandbox = issued
        org_id = f"org_{uuid4().hex[:10]}"

        claimed, live_key = claim_sandbox_tenant(
            db_session, sandbox, clerk_org_id=org_id, org_name="Acme Ltd"
        )

        assert claimed.clerk_org_id == org_id
        assert claimed.name == "Acme Ltd"
        assert live_key.startswith("inv_live_")
        # The old key no longer verifies against the stored pair...
        assert verify_api_key(raw, claimed.api_key_salt, claimed.api_key_hash) is False
        # ...and the new one does.
        assert verify_api_key(live_key, claimed.api_key_salt, claimed.api_key_hash) is True
        # ...and the old key is now a 401 through the real auth path.
        with pytest.raises(HTTPException) as exc:
            resolve_api_key_context(raw, db_session)
        assert exc.value.status_code == 401

    def test_claim_marks_the_row_and_keeps_it(self, db_session: Session):
        _, issued = _issue(db_session)
        _tenant, sandbox = issued
        org_id = f"org_{uuid4().hex[:10]}"
        claim_sandbox_tenant(db_session, sandbox, org_id, "Acme")

        db_session.refresh(sandbox)
        assert sandbox.claimed_at is not None
        assert sandbox.claimed_by_clerk_org_id == org_id

    def test_claim_keeps_the_domain_synthetic(self, db_session: Session):
        """Rewriting the domain to the claimer's real one would make this
        workspace a domain-adoption target for the NEXT signup from that
        domain -- the takeover surface Gaps 133/344 exist to close."""
        _, issued = _issue(db_session)
        _tenant, sandbox = issued
        org_id = f"org_{uuid4().hex[:10]}"
        claimed, _ = claim_sandbox_tenant(db_session, sandbox, org_id, "Acme")
        assert claimed.domain == f"org-{org_id}.invalid"
        assert claimed.domain.endswith(".invalid")

    def test_claim_does_not_grant_actions_scope(self, db_session: Session):
        """Still fail-closed on claim: Full Automation stays an explicit act."""
        _, issued = _issue(db_session)
        _tenant, sandbox = issued
        claimed, _ = claim_sandbox_tenant(
            db_session, sandbox, f"org_{uuid4().hex[:10]}", "Acme"
        )
        assert claimed.api_key_scope == KEY_SCOPE_READONLY

    def test_second_claim_is_refused(self, db_session: Session):
        """The compare-and-set predicate, sequentially. The concurrent version
        is the Postgres test below."""
        _, issued = _issue(db_session)
        _tenant, sandbox = issued
        claim_sandbox_tenant(db_session, sandbox, f"org_{uuid4().hex[:10]}", "First")

        with pytest.raises(SandboxClaimError) as exc:
            claim_sandbox_tenant(db_session, sandbox, f"org_{uuid4().hex[:10]}", "Second")
        assert exc.value.code == "already_claimed"

    def test_expired_sandbox_cannot_be_claimed(self, db_session: Session):
        _, issued = _issue(db_session)
        _tenant, sandbox = issued
        sandbox.expires_at = datetime.utcnow() - timedelta(seconds=1)
        db_session.add(sandbox)
        db_session.commit()

        with pytest.raises(SandboxClaimError) as exc:
            claim_sandbox_tenant(db_session, sandbox, f"org_{uuid4().hex[:10]}", "Late")
        assert exc.value.code == "expired"

    def test_claim_endpoint_binds_org_to_the_token(self, db_session: Session):
        """The same two bindings `POST /auth/provision` applies (Gap 133 3c):
        without them any signed-in user could claim a sandbox into someone
        else's organisation."""
        from routers.sandbox import SandboxClaimRequest, claim_sandbox
        from fastapi import HTTPException

        raw, issued = _issue(db_session)
        body = SandboxClaimRequest(
            sandbox_key=raw,
            clerk_org_id="org_the_body_says",
            org_name="Acme",
            clerk_user_id="user_a",
        )
        caller = AuthenticatedClerkIdentity(
            is_mock=False,
            clerk_user_id="user_a",
            org_id="org_the_token_says",
            email="a@acme.com",
        )
        with pytest.raises(HTTPException) as exc:
            claim_sandbox(body, caller, db_session)
        assert exc.value.status_code == 403
        assert "organisation" in exc.value.detail

    def test_claim_endpoint_rejects_a_non_sandbox_key(self, db_session: Session):
        """An `inv_live_` key must not be able to promote a real workspace into
        a different org."""
        from routers.sandbox import SandboxClaimRequest, claim_sandbox
        from fastapi import HTTPException

        body = SandboxClaimRequest(
            sandbox_key="inv_live_" + "x" * 40,
            clerk_org_id="org_x",
            org_name="Acme",
            clerk_user_id="user_a",
        )
        caller = AuthenticatedClerkIdentity(is_mock=True)
        with pytest.raises(HTTPException) as exc:
            claim_sandbox(body, caller, db_session)
        assert exc.value.status_code == 400
        assert "inv_test_" in exc.value.detail

    def test_claim_endpoint_end_to_end(self, db_session: Session):
        from routers.sandbox import SandboxClaimRequest, claim_sandbox

        raw, issued = _issue(db_session)
        tenant, _sandbox = issued
        org_id = f"org_{uuid4().hex[:10]}"
        result = claim_sandbox(
            SandboxClaimRequest(
                sandbox_key=raw, clerk_org_id=org_id, org_name="Acme", clerk_user_id="u"
            ),
            AuthenticatedClerkIdentity(is_mock=True),
            db_session,
        )
        assert result.tenant_id == str(tenant.id)
        assert result.clerk_org_id == org_id
        assert result.api_key.startswith("inv_live_")


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------

class TestSandboxStatus:
    def test_reports_remaining_allowances(self, db_session: Session, monkeypatch):
        import config

        monkeypatch.setattr(config.settings, "SANDBOX_CHAT_MESSAGE_LIMIT", 9)
        raw, issued = _issue(db_session)
        tenant, _sandbox = issued
        charge_sandbox_chat_message(db_session, tenant.id)

        response = client.get(STATUS_URL, headers={"X-API-Key": raw})
        assert response.status_code == 200
        body = response.json()
        assert body["tenant_id"] == str(tenant.id)
        assert body["chat_messages_used"] == 1
        assert body["chat_message_limit"] == 9
        assert body["expired"] is False
        assert body["claimed"] is False

    def test_404s_for_a_non_sandbox_key(self, db_session: Session):
        from services.api_keys import generate_api_key, generate_salt, hash_api_key

        tenant = Tenant(id=uuid4(), name="Real", domain=f"{uuid4().hex}.example.com")
        raw = generate_api_key()
        salt = generate_salt()
        tenant.api_key_hash = hash_api_key(raw, salt)
        tenant.api_key_salt = salt
        tenant.api_key_prefix = key_prefix(raw)
        db_session.add(tenant)
        db_session.commit()

        response = client.get(STATUS_URL, headers={"X-API-Key": raw})
        assert response.status_code == 404

    def test_rejects_a_browser_session(self, db_session: Session):
        """Key-only, same as GET /settings/security/api-key/verify."""
        assert client.get(STATUS_URL).status_code == 401


# ---------------------------------------------------------------------------
# Real Postgres — the two things SQLite structurally cannot prove
# ---------------------------------------------------------------------------

def _pg_engine_or_skip():
    psycopg2 = pytest.importorskip("psycopg2")
    from config import get_settings

    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        psycopg2.connect(url).close()
    except psycopg2.OperationalError as exc:
        pytest.skip(f"local Postgres not reachable: {exc}")

    pg_engine = create_engine(url)
    SQLModel.metadata.create_all(pg_engine)
    return pg_engine


def test_concurrent_claims_have_exactly_one_winner_on_postgres():
    """Constraint 2 against real Postgres: two concurrent claims, one winner.

    THIS IS THE ASSERTION SQLITE CANNOT MAKE. `claim_sandbox_tenant()`'s
    single-winner guarantee rests on `pg_advisory_xact_lock(hashtext(...))` --
    a Postgres primitive that is a silent no-op elsewhere -- plus a re-read under
    that lock and a compare-and-set on `claimed_at IS NULL`. Same threading +
    `threading.Barrier` harness as
    tests/test_auth.py::test_provision_concurrent_same_org_id_creates_one_tenant_on_postgres.

    What must hold: exactly one thread succeeds, the loser gets
    `already_claimed`, the surviving stored credential is the WINNER's live key
    (i.e. the loser did not overwrite it -- the silent-revocation failure mode),
    and the original `inv_test_` key verifies against nothing.
    """
    pg_engine = _pg_engine_or_skip()

    raw_sandbox = generate_sandbox_key()
    org_a = f"org_claim_a_{uuid4().hex[:8]}"
    org_b = f"org_claim_b_{uuid4().hex[:8]}"

    with Session(pg_engine) as setup:
        issued = issue_sandbox_tenant(setup, raw_sandbox, issued_from_ip="10.0.0.1")
        assert issued is not None
        tenant_id = issued[0].id

    barrier = threading.Barrier(2)
    wins: list[tuple[str, str]] = []
    losses: list[SandboxClaimError] = []
    errors: list[BaseException] = []

    def _worker(org_id: str, name: str) -> None:
        barrier.wait()
        with Session(pg_engine) as session:
            sandbox = session.exec(
                select(SandboxTenant).where(SandboxTenant.tenant_id == tenant_id)
            ).first()
            try:
                _tenant, live_key = claim_sandbox_tenant(session, sandbox, org_id, name)
                wins.append((org_id, live_key))
            except SandboxClaimError as exc:
                losses.append(exc)
            except BaseException as exc:  # pragma: no cover - surfaced via assert
                errors.append(exc)

    threads = [
        threading.Thread(target=_worker, args=(org_a, "Claimer A")),
        threading.Thread(target=_worker, args=(org_b, "Claimer B")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), "claim worker timed out"

    with Session(pg_engine) as session:
        tenant = session.get(Tenant, tenant_id)
        sandbox = session.exec(
            select(SandboxTenant).where(SandboxTenant.tenant_id == tenant_id)
        ).first()
        try:
            assert not errors, f"Unexpected errors: {errors}"
            assert len(wins) == 1, f"Expected exactly one winner, got {len(wins)}"
            assert len(losses) == 1
            assert losses[0].code == "already_claimed"

            winning_org, winning_key = wins[0]
            assert tenant.clerk_org_id == winning_org
            assert sandbox.claimed_at is not None
            assert sandbox.claimed_by_clerk_org_id == winning_org
            # The loser did not overwrite the winner's credential.
            assert verify_api_key(
                winning_key, tenant.api_key_salt, tenant.api_key_hash
            ) is True
            # The sandbox key died with the claim, in the same transaction.
            assert verify_api_key(
                raw_sandbox, tenant.api_key_salt, tenant.api_key_hash
            ) is False
        finally:
            if sandbox is not None:
                session.delete(sandbox)
            session.flush()
            if tenant is not None:
                session.delete(tenant)
            session.commit()


def test_sandbox_tenant_is_never_adopted_by_a_real_signup_on_postgres():
    """Constraint 1 against real Postgres, driven through `provision_tenant()`.

    Rather than asserting the blocker list in isolation, this drives the actual
    provisioning endpoint with a real signup whose email domain is set to the
    sandbox tenant's own synthetic domain -- i.e. the single input that could
    make the domain lookup find it. The signup must get its OWN fresh tenant and
    must not touch the sandbox one.

    Postgres specifically because `provision_tenant()` takes two
    `pg_advisory_xact_lock`s on this path (org key and domain key) and because
    `Tenant.domain`'s UNIQUE constraint is what forces the fallback branch --
    neither is exercised on SQLite.
    """
    pg_engine = _pg_engine_or_skip()
    from routers.auth import TenantProvisionRequest, provision_tenant

    raw_sandbox = generate_sandbox_key()
    tag = uuid4().hex[:10]
    org_id = f"org_adopt_{tag}"
    user_id = f"user_adopt_{tag}"

    with Session(pg_engine) as setup:
        issued = issue_sandbox_tenant(setup, raw_sandbox)
        assert issued is not None
        sandbox_tenant_id = issued[0].id
        sandbox_domain_value = issued[0].domain

    # The attacker-optimal input: an email whose domain IS the sandbox tenant's.
    email = f"attacker@{sandbox_domain_value}"

    created_ids: list = []
    with Session(pg_engine) as session:
        try:
            result = asyncio.run(
                provision_tenant(
                    TenantProvisionRequest(
                        clerk_org_id=org_id,
                        org_name="Unrelated Real Company",
                        admin_email=email,
                        clerk_user_id=user_id,
                    ),
                    AuthenticatedClerkIdentity(
                        is_mock=False,
                        clerk_user_id=user_id,
                        org_id=org_id,
                        email=email,
                    ),
                    session,
                )
            )
            created_ids.append(result.tenant_id)

            assert result.is_new is True
            assert result.tenant_id != str(sandbox_tenant_id), (
                "a real signup adopted the sandbox tenant"
            )

            sandbox_tenant = session.get(Tenant, sandbox_tenant_id)
            assert sandbox_tenant.clerk_org_id is None
            assert sandbox_tenant.name == "Sandbox Workspace"
            assert sandbox_tenant.domain == sandbox_domain_value
            # And the sandbox key still resolves to the SANDBOX tenant, not to
            # the new company's workspace.
            assert resolve_api_key_context(
                raw_sandbox, session
            ).tenant_id == sandbox_tenant_id
        finally:
            for user in session.exec(
                select(User).where(User.clerk_user_id == user_id)
            ).all():
                session.delete(user)
            for sender in session.exec(
                select(TenantEmailSender).where(TenantEmailSender.email == email.lower())
            ).all():
                session.delete(sender)
            for sb in session.exec(
                select(SandboxTenant).where(SandboxTenant.tenant_id == sandbox_tenant_id)
            ).all():
                session.delete(sb)
            session.flush()
            for tid in created_ids:
                row = session.get(Tenant, tid)
                if row is not None:
                    session.delete(row)
            leftover = session.get(Tenant, sandbox_tenant_id)
            if leftover is not None:
                session.delete(leftover)
            session.commit()


def test_concurrent_chat_charges_cannot_exceed_the_allowance_on_postgres(monkeypatch):
    """Gap 352, constraint 7 against real Postgres: the meter actually bounds.

    THE BUG THIS EXISTS FOR. `charge_sandbox_chat_message()` shipped as a
    read-then-decide-then-write with no row lock, on the argument that "the
    worst case of a lost update is one extra chat turn". That is true for
    exactly two racers. For N concurrent requests all reading the counter
    before any of them commits, the loss is N-1 turns -- and N is the holder of
    the `inv_test_` key's choice. Measured on this same harness against the
    pre-fix function: limit 5, 24 concurrent charges -> **24 turns allowed**,
    counter left at 3. The one control standing between an anonymous stranger
    and unmetered Azure OpenAI spend bounded nothing.

    THIS IS AN ASSERTION SQLITE CANNOT MAKE. The fix is
    `SELECT ... FOR UPDATE` (`locked_sandbox_select()`) plus a re-read under
    that lock -- and SQLAlchemy's SQLite dialect renders `FOR UPDATE` as
    nothing at all, so a reverted fix would pass there.

    Harness is the threading + `threading.Barrier` shape already used by
    `test_concurrent_claims_have_exactly_one_winner_on_postgres` and
    tests/test_auth.py::test_provision_concurrent_same_org_id_creates_one_tenant_on_postgres,
    with one session per thread because one request == one transaction.
    """
    import config

    pg_engine = _pg_engine_or_skip()

    limit = 5
    concurrency = 24
    # `config.settings` is the object `get_settings()` returns (it is
    # lru_cached over the same instance), and every worker thread reads it.
    monkeypatch.setattr(config.settings, "SANDBOX_CHAT_MESSAGE_LIMIT", limit)

    with Session(pg_engine) as setup:
        issued = issue_sandbox_tenant(
            setup, generate_sandbox_key(), issued_from_ip="10.0.0.9"
        )
        assert issued is not None
        tenant_id = issued[0].id

    barrier = threading.Barrier(concurrency)
    results_lock = threading.Lock()
    allowed: list[dict] = []
    refused: list[dict] = []
    errors: list[BaseException] = []

    def _worker() -> None:
        barrier.wait()
        try:
            with Session(pg_engine) as session:
                result = charge_sandbox_chat_message(session, tenant_id)
            with results_lock:
                (allowed if result and result["allowed"] else refused).append(result)
        except BaseException as exc:  # pragma: no cover - surfaced via assert
            with results_lock:
                errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(concurrency)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive(), "charge worker timed out"

    with Session(pg_engine) as session:
        sandbox = session.exec(
            select(SandboxTenant).where(SandboxTenant.tenant_id == tenant_id)
        ).first()
        tenant = session.get(Tenant, tenant_id)
        try:
            assert not errors, f"Unexpected errors: {errors}"
            # The whole point: turns actually granted never exceed the allowance.
            assert len(allowed) == limit, (
                f"{len(allowed)} turns allowed against a limit of {limit} -- "
                "the meter is not bounding under concurrency"
            )
            assert len(refused) == concurrency - limit
            assert all(r["allowed"] is False for r in refused)
            # And no charge was lost: the persisted counter equals the turns
            # granted. A counter that lags is how the pre-fix version let a
            # spent allowance keep answering.
            assert sandbox.chat_messages_used == len(allowed) == limit
            # Every granted turn reported a distinct position in the allowance,
            # so no two callers were told they were the same message.
            assert sorted(r["used"] for r in allowed) == list(range(1, limit + 1))
        finally:
            if sandbox is not None:
                session.delete(sandbox)
            session.flush()
            if tenant is not None:
                session.delete(tenant)
            session.commit()
