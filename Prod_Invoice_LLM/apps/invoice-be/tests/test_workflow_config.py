"""Feature 25 / Gap 336: TenantWorkflowConfig and GET/PUT /settings/workflow.

The properties these tests exist to hold:

  * the wizard's `audit_policy` choice IS `Tenant.api_key_scope` (Gap 335) --
    one decision in one place, written in one transaction, never a second field
    that can drift from what the auth layer actually enforces;
  * an output destination that cannot actually deliver is **rejected**, not
    stored and silently ignored -- a tenant must never believe summaries are
    being emailed, or invoices filed to Drive, when nothing sends them. As of
    Gaps 339/338 every destination is built, so what is enforced is each one's
    per-tenant precondition: a registered email sender for `email_summary`, a
    connected **and write-scoped** Google Drive for `drive_archive`;
  * a rejected request writes nothing at all, including `api_key_scope`;
  * this is tenant-wide policy, so it is Admin-only on both verbs.

Setup conventions follow tests/test_api_keys.py: in-memory SQLite with a
StaticPool, `get_db_session` overridden onto that session, and conftest.py's
suite-wide ALLOW_MOCK_AUTH -- so a request with no Authorization header is the
mock Admin, and `Bearer test_viewer` is a permission-less non-Admin.
"""
import pytest
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from main import app
from dependencies import (
    get_db_session,
    KEY_SCOPE_ACTIONS,
    KEY_SCOPE_READONLY,
    MOCK_TENANT_ID,
)
from models import Tenant, TenantConnection, TenantEmailSender, TenantWorkflowConfig
import routers.settings as settings_router
from routers.settings import (
    AUDIT_POLICY_FULL_AUTOMATION,
    AUDIT_POLICY_STRICT_REVIEW,
    WORKFLOW_OUTPUT_DESTINATIONS_AVAILABLE,
    WORKFLOW_OUTPUT_DESTINATIONS_UNBUILT,
)
from utils.encryption import encrypt_token

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

client = TestClient(app)

WORKFLOW_URL = "/api/v1/settings/workflow"
NON_ADMIN = {"Authorization": "Bearer test_viewer"}


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


def _seed_tenant(db_session: Session, tenant_id=None, billing_plan: str = "pro") -> Tenant:
    tenant = Tenant(
        id=tenant_id or MOCK_TENANT_ID,
        name="Test Workspace",
        domain=f"test-{uuid4().hex[:8]}.example.com",
        billing_plan=billing_plan,
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _seed_sender(db_session: Session, tenant_id=None, email: str | None = None) -> TenantEmailSender:
    """Gap 339: `email_summary` may only be selected when the tenant already has
    a registered address for it to deliver to."""
    sender = TenantEmailSender(
        tenant_id=tenant_id or MOCK_TENANT_ID,
        email=email or f"ap-{uuid4().hex[:8]}@example.com",
        email_set="inbound",
    )
    db_session.add(sender)
    db_session.commit()
    return sender


def _seed_drive_connection(db_session: Session, tenant_id=None) -> TenantConnection:
    """Gap 338: `drive_archive` may only be selected when Google Drive is
    connected -- and, separately, when that connection can write."""
    connection = TenantConnection(
        tenant_id=tenant_id or MOCK_TENANT_ID,
        provider="google_drive",
        encrypted_access_token=encrypt_token("drive-access-token"),
        encrypted_refresh_token=encrypt_token("drive-refresh-token"),
        token_expiry=datetime.utcnow() + timedelta(hours=1),
        status="active",
    )
    db_session.add(connection)
    db_session.commit()
    return connection


@contextmanager
def _writable_drive(write_scope: bool = True):
    """Stand in for the two calls that reach Google: the real-credentials check
    and the tokeninfo scope probe. Everything else -- the connection row, the
    token decryption, the readiness logic -- runs for real."""
    with ExitStack() as stack:
        stack.enter_context(
            patch("services.workflow_outputs.has_real_credentials", return_value=True)
        )
        stack.enter_context(
            patch(
                "services.workflow_outputs.token_has_drive_write_scope",
                return_value=write_scope,
            )
        )
        yield


def _config_rows(db_session: Session, tenant_id=None):
    return db_session.exec(
        select(TenantWorkflowConfig).where(
            TenantWorkflowConfig.tenant_id == (tenant_id or MOCK_TENANT_ID)
        )
    ).all()


# --- defaults for a tenant that has never run the wizard -------------------


def test_get_returns_fail_closed_defaults_and_writes_no_row(db_session):
    tenant = _seed_tenant(db_session)

    response = client.get(WORKFLOW_URL)
    assert response.status_code == 200
    data = response.json()

    assert data["input_channels"] == []
    assert data["output_destinations"] == []
    assert data["chat_access"] == "dashboard"
    assert data["completed_at"] is None
    # The fail-closed pair: a tenant that has chosen nothing is on Strict Review,
    # which is exactly what Gap 335's readonly default already enforced.
    assert data["audit_policy"] == AUDIT_POLICY_STRICT_REVIEW
    assert data["api_key_scope"] == KEY_SCOPE_READONLY
    assert tenant.api_key_scope == KEY_SCOPE_READONLY

    # A read must not have a side effect.
    assert _config_rows(db_session) == []


# --- persistence round-trip -------------------------------------------------


def test_put_then_get_round_trips_every_field(db_session):
    _seed_tenant(db_session)

    put = client.put(
        WORKFLOW_URL,
        json={
            "input_channels": ["email", "api"],
            "audit_policy": AUDIT_POLICY_FULL_AUTOMATION,
            "output_destinations": ["webhook", "dashboard_only"],
            "chat_access": "api",
        },
    )
    assert put.status_code == 200, put.text
    assert put.json()["completed_at"] is not None

    got = client.get(WORKFLOW_URL).json()
    assert got["input_channels"] == ["email", "api"]
    assert got["audit_policy"] == AUDIT_POLICY_FULL_AUTOMATION
    assert got["output_destinations"] == ["webhook", "dashboard_only"]
    assert got["chat_access"] == "api"

    rows = _config_rows(db_session)
    assert len(rows) == 1
    assert rows[0].input_channels == ["email", "api"]


def test_repeated_put_updates_the_same_single_row(db_session):
    _seed_tenant(db_session)

    client.put(WORKFLOW_URL, json={"input_channels": ["email"]})
    first_completed = client.get(WORKFLOW_URL).json()["completed_at"]

    client.put(WORKFLOW_URL, json={"input_channels": ["manual", "drive"]})

    rows = _config_rows(db_session)
    assert len(rows) == 1, "one row per tenant -- UNIQUE(tenant_id)"
    assert rows[0].input_channels == ["manual", "drive"]
    # completed_at records that onboarding happened, not when the row last
    # changed, so a later edit must not move it.
    assert client.get(WORKFLOW_URL).json()["completed_at"] == first_completed


def test_omitted_fields_keep_their_current_values(db_session):
    _seed_tenant(db_session)
    client.put(
        WORKFLOW_URL,
        json={
            "input_channels": ["email"],
            "output_destinations": ["webhook"],
            "chat_access": "widget",
            "audit_policy": AUDIT_POLICY_FULL_AUTOMATION,
        },
    )

    # A single-field edit must not blank the rest.
    client.put(WORKFLOW_URL, json={"chat_access": "dashboard"})

    got = client.get(WORKFLOW_URL).json()
    assert got["input_channels"] == ["email"]
    assert got["output_destinations"] == ["webhook"]
    assert got["chat_access"] == "dashboard"
    assert got["audit_policy"] == AUDIT_POLICY_FULL_AUTOMATION


def test_duplicate_values_are_de_duplicated_in_order(db_session):
    _seed_tenant(db_session)
    response = client.put(
        WORKFLOW_URL,
        json={
            "input_channels": ["email", "api", "email"],
            "output_destinations": ["webhook", "webhook"],
        },
    )
    assert response.status_code == 200
    assert response.json()["input_channels"] == ["email", "api"]
    assert response.json()["output_destinations"] == ["webhook"]


# --- the write-through: audit_policy IS Tenant.api_key_scope ---------------


def test_full_automation_writes_actions_scope_onto_the_tenant(db_session):
    tenant = _seed_tenant(db_session)
    assert tenant.api_key_scope == KEY_SCOPE_READONLY

    response = client.put(
        WORKFLOW_URL, json={"audit_policy": AUDIT_POLICY_FULL_AUTOMATION}
    )
    assert response.status_code == 200
    assert response.json()["api_key_scope"] == KEY_SCOPE_ACTIONS

    db_session.refresh(tenant)
    # This is the column dependencies.require_key_scope() actually enforces.
    assert tenant.api_key_scope == KEY_SCOPE_ACTIONS


def test_strict_review_writes_readonly_scope_onto_the_tenant(db_session):
    tenant = _seed_tenant(db_session)
    tenant.api_key_scope = KEY_SCOPE_ACTIONS
    db_session.add(tenant)
    db_session.commit()

    response = client.put(
        WORKFLOW_URL, json={"audit_policy": AUDIT_POLICY_STRICT_REVIEW}
    )
    assert response.status_code == 200
    assert response.json()["api_key_scope"] == KEY_SCOPE_READONLY

    db_session.refresh(tenant)
    assert tenant.api_key_scope == KEY_SCOPE_READONLY


def test_get_derives_policy_from_the_tenant_column_not_the_stored_row(db_session):
    """If the two ever disagree, the API reports what is actually enforced.

    Simulates an Admin (or a future code path) setting `Tenant.api_key_scope`
    directly, leaving the wizard row saying something else. The endpoint must
    not report the stale wizard answer -- that is the whole reason the policy is
    derived rather than read back.
    """
    tenant = _seed_tenant(db_session)
    client.put(WORKFLOW_URL, json={"audit_policy": AUDIT_POLICY_FULL_AUTOMATION})

    stored = _config_rows(db_session)[0]
    assert stored.audit_policy == AUDIT_POLICY_FULL_AUTOMATION

    tenant.api_key_scope = KEY_SCOPE_READONLY
    db_session.add(tenant)
    db_session.commit()

    got = client.get(WORKFLOW_URL).json()
    assert got["api_key_scope"] == KEY_SCOPE_READONLY
    assert got["audit_policy"] == AUDIT_POLICY_STRICT_REVIEW


def test_policy_survives_a_put_that_does_not_mention_it(db_session):
    tenant = _seed_tenant(db_session)
    client.put(WORKFLOW_URL, json={"audit_policy": AUDIT_POLICY_FULL_AUTOMATION})

    client.put(WORKFLOW_URL, json={"input_channels": ["manual"]})

    db_session.refresh(tenant)
    assert tenant.api_key_scope == KEY_SCOPE_ACTIONS
    assert client.get(WORKFLOW_URL).json()["audit_policy"] == AUDIT_POLICY_FULL_AUTOMATION


# --- validation: unbuilt destinations are rejected, never silently stored ---


def test_no_wizard_destination_is_unbuilt_any_more(db_session):
    """Gap 336 rejected the destinations nothing delivered to; Gap 339 built
    `email_summary` and Gap 338 built `drive_archive`, so the unbuilt set is now
    empty.

    The *mechanism* is asserted rather than deleted: an entry added to
    WORKFLOW_OUTPUT_DESTINATIONS_UNBUILT must still be rejected with a message
    naming the gap, so a future destination cannot be accepted-and-ignored.
    """
    _seed_tenant(db_session)
    assert WORKFLOW_OUTPUT_DESTINATIONS_UNBUILT == {}

    with patch.dict(
        "routers.settings.WORKFLOW_OUTPUT_DESTINATIONS_UNBUILT",
        {"telepathy": "BE Gap 999 (mind-reading)"},
        clear=False,
    ), patch.object(
        settings_router, "WORKFLOW_OUTPUT_DESTINATIONS_AVAILABLE",
        WORKFLOW_OUTPUT_DESTINATIONS_AVAILABLE + ("telepathy",),
    ):
        response = client.put(
            WORKFLOW_URL, json={"output_destinations": ["webhook", "telepathy"]}
        )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "telepathy" in detail
    assert "Gap 999" in detail
    assert "not available yet" in detail

    # Nothing was stored -- not even the valid half of the request.
    assert _config_rows(db_session) == []


def test_drive_archive_is_no_longer_rejected(db_session):
    """Gap 338: the destination this file used to assert a 422 for.

    It is storable now -- provided the tenant's Google Drive connection can
    actually be written to, which is asserted separately below.
    """
    _seed_tenant(db_session)
    _seed_drive_connection(db_session)

    with _writable_drive():
        response = client.put(
            WORKFLOW_URL, json={"output_destinations": ["webhook", "drive_archive"]}
        )
    assert response.status_code == 200, response.text
    assert response.json()["output_destinations"] == ["webhook", "drive_archive"]

    rows = _config_rows(db_session)
    assert len(rows) == 1
    assert rows[0].output_destinations == ["webhook", "drive_archive"]


def test_drive_archive_requires_a_connected_drive(db_session):
    tenant = _seed_tenant(db_session)

    response = client.put(WORKFLOW_URL, json={"output_destinations": ["drive_archive"]})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "drive_archive" in detail
    assert "not connected" in detail

    db_session.refresh(tenant)
    assert tenant.api_key_scope == KEY_SCOPE_READONLY
    assert _config_rows(db_session) == []


def test_drive_archive_requires_a_write_scoped_grant(db_session):
    """Gap 338's migration case, at the point a tenant selects the destination.

    A Drive connected before 2026-08-30 holds a `drive.readonly` token, and
    Google does not widen an existing grant. "Connected" is therefore not the
    same question as "writable", and storing the destination on a read-only
    grant would be exactly the silent no-op Gap 336's rejection exists to
    prevent -- so it is a 422 telling the Admin to reconnect.
    """
    tenant = _seed_tenant(db_session)
    _seed_drive_connection(db_session)

    with _writable_drive(write_scope=False):
        response = client.put(
            WORKFLOW_URL,
            json={
                "audit_policy": AUDIT_POLICY_FULL_AUTOMATION,
                "output_destinations": ["drive_archive"],
            },
        )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "drive_archive" in detail
    assert "Reconnect Google Drive" in detail

    # Validation still runs before any write, so nothing changed -- including
    # the api_key_scope the same request tried to widen.
    db_session.refresh(tenant)
    assert tenant.api_key_scope == KEY_SCOPE_READONLY
    assert _config_rows(db_session) == []


def test_email_summary_is_no_longer_rejected(db_session):
    """Gap 339: the destination this test file used to assert a 422 for.

    Gap 336 rejected `email_summary` because nothing delivered to it. Gap 339
    built the delivery (services/workflow_outputs.py, fired from the audit
    resolve handler on approval), so it is now storable -- provided the tenant
    has a registered sender to send to, which is asserted separately below.
    """
    _seed_tenant(db_session)
    _seed_sender(db_session)

    response = client.put(
        WORKFLOW_URL, json={"output_destinations": ["webhook", "email_summary"]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["output_destinations"] == ["webhook", "email_summary"]

    rows = _config_rows(db_session)
    assert len(rows) == 1
    assert rows[0].output_destinations == ["webhook", "email_summary"]


def test_email_summary_requires_a_registered_sender(db_session):
    """The founder's rule: summary recipients are pre-registered, never typed in.

    So selecting the destination with an empty TenantEmailSender allowlist would
    store a setting that can never deliver anything -- the exact silent no-op
    Gap 336's rejection of unbuilt destinations exists to prevent. It is a 422
    naming the fix, not a stored-and-ignored value.
    """
    tenant = _seed_tenant(db_session)

    response = client.put(
        WORKFLOW_URL,
        json={
            "audit_policy": AUDIT_POLICY_FULL_AUTOMATION,
            "output_destinations": ["email_summary"],
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "registered" in detail
    assert "email_summary" in detail

    # Validation still runs before any write, so nothing changed -- including
    # the api_key_scope the same request tried to widen.
    db_session.refresh(tenant)
    assert tenant.api_key_scope == KEY_SCOPE_READONLY
    assert _config_rows(db_session) == []


def test_rejected_request_does_not_touch_api_key_scope(db_session):
    """Validation runs before any write, so a bad request changes nothing.

    Re-pointed at an unknown destination by Gap 338: `drive_archive`, which this
    test used to use, is a valid value now -- its rejection depends on tenant
    state and is asserted by test_drive_archive_requires_* above. The property
    under test here is the ordering, so it wants a value that is rejected
    unconditionally.
    """
    tenant = _seed_tenant(db_session)

    response = client.put(
        WORKFLOW_URL,
        json={
            "audit_policy": AUDIT_POLICY_FULL_AUTOMATION,
            "output_destinations": ["carrier_pigeon"],
        },
    )
    assert response.status_code == 422

    db_session.refresh(tenant)
    assert tenant.api_key_scope == KEY_SCOPE_READONLY
    assert _config_rows(db_session) == []


def test_unknown_output_destination_is_rejected(db_session):
    _seed_tenant(db_session)
    response = client.put(WORKFLOW_URL, json={"output_destinations": ["carrier_pigeon"]})
    assert response.status_code == 422
    assert "carrier_pigeon" in response.json()["detail"]


def test_unknown_input_channel_is_rejected(db_session):
    _seed_tenant(db_session)
    response = client.put(WORKFLOW_URL, json={"input_channels": ["fax"]})
    assert response.status_code == 422
    assert "fax" in response.json()["detail"]


@pytest.mark.parametrize("channel", ["email", "drive", "api", "manual"])
def test_every_input_channel_is_accepted(db_session, channel):
    """All four work today -- `api` because Gap 335 built the key auth for it."""
    _seed_tenant(db_session)
    response = client.put(WORKFLOW_URL, json={"input_channels": [channel]})
    assert response.status_code == 200
    assert response.json()["input_channels"] == [channel]


def test_unknown_audit_policy_is_rejected(db_session):
    _seed_tenant(db_session)
    response = client.put(WORKFLOW_URL, json={"audit_policy": "yolo"})
    assert response.status_code == 422
    assert "yolo" in response.json()["detail"]


def test_unknown_chat_access_is_rejected(db_session):
    _seed_tenant(db_session)
    response = client.put(WORKFLOW_URL, json={"chat_access": "carrier_pigeon"})
    assert response.status_code == 422


# --- Admin gate and tenant isolation ---------------------------------------


def test_put_is_admin_only(db_session):
    tenant = _seed_tenant(db_session)
    response = client.put(
        WORKFLOW_URL,
        headers=NON_ADMIN,
        json={"audit_policy": AUDIT_POLICY_FULL_AUTOMATION},
    )
    assert response.status_code == 403
    db_session.refresh(tenant)
    assert tenant.api_key_scope == KEY_SCOPE_READONLY


def test_get_is_admin_only(db_session):
    """Unlike GET /vendor-flow, this one is Admin-gated too: it reports
    api_key_scope, which is security configuration, and its only consumer is the
    Admin-only Settings wizard."""
    _seed_tenant(db_session)
    assert client.get(WORKFLOW_URL, headers=NON_ADMIN).status_code == 403


def test_another_tenants_config_is_never_returned(db_session):
    _seed_tenant(db_session)
    other_tenant = _seed_tenant(db_session, tenant_id=uuid4())
    db_session.add(
        TenantWorkflowConfig(
            tenant_id=other_tenant.id,
            input_channels=["drive"],
            output_destinations=["webhook"],
            chat_access="widget",
            audit_policy=AUDIT_POLICY_FULL_AUTOMATION,
        )
    )
    db_session.commit()

    got = client.get(WORKFLOW_URL).json()
    assert got["input_channels"] == []
    assert got["chat_access"] == "dashboard"
    assert got["audit_policy"] == AUDIT_POLICY_STRICT_REVIEW
