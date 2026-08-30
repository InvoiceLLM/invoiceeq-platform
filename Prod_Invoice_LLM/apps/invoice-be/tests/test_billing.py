"""
Tests for Feature 11: PayU Billing API (routers/billing.py).

Scope note: nothing here touches PayU's network. `_verify_payment_with_payu`
is the single point where this router talks to PayU, and every test that
reaches it monkeypatches it. The rest is pure local logic -- hash
construction, hash verification, and the callback's branch table -- which is
exactly the part that has to be right before any real money moves.

Coverage
--------
Request-hash construction
1.  `_request_hash` matches an independently-built sha512 of the documented
    pipe sequence (10 udf slots, udf1 = tenant_id).
2.  The hash returned by create-checkout-session recomputes from its own
    returned fields.
3.  surl/furl are built from BACKEND_PUBLIC_URL and mirror the backend path.
4.  A non-Admin caller is refused (403).

Response-hash verification
5.  A tampered POST (amount rewritten after signing) is rejected as
    hash_mismatch and never reaches verify_payment.
6.  A correctly signed POST passes the hash check.

fail_redirect reason branches
7.  no txnid                          -> ?reason=malformed
8.  bad hash                          -> ?reason=hash_mismatch&txnid=
9.  verify_payment unreachable        -> ?reason=unverifiable&txnid=
10. verified, productinfo unmapped    -> ?reason=unknown_plan&txnid=
11. verified, udf1 not a UUID         -> ?reason=unknown_tenant&txnid=
12. verified, tenant row missing      -> ?reason=unknown_tenant&txnid=
13. plain decline (status != success) -> ?txnid= with no reason

Plan resolution / tenant resolution
14. productinfo "InvoiceAI-pro"          -> billing_plan "pro"
15. productinfo "InvoiceAI-pro_combined" -> billing_plan "pro_combined"
16. udf1 resolves the tenant that gets upgraded, not the caller's.

Non-success never mutates state
17. status=failure on surl leaves billing_plan untouched.
18. PayU's own verify says failure while the callback claims success ->
    no upgrade.
19. A hash-valid, verified-success POST to the *furl* endpoint still does not
    upgrade (is_surl=False short-circuits).

GET /billing/usage (Gap 143)
20. A free tenant's used/limit/remaining come from the tenant row and
    DEFAULT_FREE_INVOICES_LIMIT -- not the 25 the UI used to hard-code.
21. Spending quota moves `used` in step with the counter the ingestion gate
    reads, which is the whole point of the endpoint.
22. A paid plan reports metered=False with no numbers, rather than inventing
    the Pro tier's advertised-but-unimplemented cap (BE Gap 188).
23. A non-Admin may read usage (unlike checkout, which is Admin-only).
24. A counter outside [0, limit] is clamped instead of rendering negative.
"""
import hashlib
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import routers.billing as billing
from dependencies import MOCK_TENANT_ID, get_db_session
from main import app
from models import Tenant

TEST_KEY = "testmerchantkey"
TEST_SALT = "testmerchantsalt"

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

client = TestClient(app)


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
def payu_credentials(monkeypatch):
    """Pin key/salt/mode so hashes don't depend on the developer's .env."""
    monkeypatch.setattr(billing.settings, "PAYU_MERCHANT_KEY", TEST_KEY)
    monkeypatch.setattr(billing.settings, "PAYU_MERCHANT_SALT", TEST_SALT)
    monkeypatch.setattr(billing.settings, "PAYU_MODE", "test")
    monkeypatch.setattr(billing.settings, "BACKEND_PUBLIC_URL", "https://website.example.com")
    monkeypatch.setattr(billing.settings, "PUBLIC_APP_URL", "https://website.example.com")
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_tenant(
    db_session: Session,
    tenant_id: UUID = MOCK_TENANT_ID,
    plan: str = "free",
    remaining: int | None = None,
) -> Tenant:
    tenant = Tenant(
        id=tenant_id,
        name="Test Workspace",
        domain=f"{tenant_id}.example.com",
        billing_plan=plan,
        **({} if remaining is None else {"free_invoices_remaining": remaining}),
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _expected_request_hash(txnid, amount, productinfo, firstname, email, udf1):
    """Independently rebuilt from PayU's documented sequence -- deliberately
    NOT calling billing._request_hash, so a change to that function's field
    order fails this test instead of silently agreeing with itself."""
    parts = [
        TEST_KEY, txnid, amount, productinfo, firstname, email,
        udf1, "", "", "", "", "", "", "", "", "",  # udf1..udf10
        TEST_SALT,
    ]
    return hashlib.sha512("|".join(parts).encode("utf-8")).hexdigest()


def _expected_response_hash(status_str, txnid, amount, productinfo, firstname, email, udf1):
    parts = [
        TEST_SALT, status_str,
        "", "", "", "", "", "", "", "", "", udf1,  # udf10..udf1
        email, firstname, productinfo, amount, txnid, TEST_KEY,
    ]
    return hashlib.sha512("|".join(parts).encode("utf-8")).hexdigest()


def _callback_form(
    *,
    status_str="success",
    txnid="txn_abc123",
    amount="4999.00",
    productinfo="InvoiceAI-pro",
    firstname="Test",
    email="test@example.com",
    udf1=str(MOCK_TENANT_ID),
    hash_override=None,
):
    return {
        "status": status_str,
        "txnid": txnid,
        "amount": amount,
        "productinfo": productinfo,
        "firstname": firstname,
        "email": email,
        "udf1": udf1,
        "hash": hash_override
        or _expected_response_hash(status_str, txnid, amount, productinfo, firstname, email, udf1),
    }


def _post_callback(path, form):
    return client.post(f"/api/v1/billing/payu/{path}", data=form, follow_redirects=False)


def _redirect_query(response):
    """(path, {param: value}) for a 303 redirect."""
    assert response.status_code == 303, response.text
    parsed = urlparse(response.headers["location"])
    flat = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    return parsed.path, flat


@pytest.fixture
def verify_success(monkeypatch):
    """PayU's server-to-server check agrees the payment succeeded."""
    async def _fake(txnid):
        return "success"

    monkeypatch.setattr(billing, "_verify_payment_with_payu", _fake)
    yield


@pytest.fixture
def verify_failure(monkeypatch):
    async def _fake(txnid):
        return "failure"

    monkeypatch.setattr(billing, "_verify_payment_with_payu", _fake)
    yield


@pytest.fixture
def verify_unreachable(monkeypatch):
    async def _fake(txnid):
        return None

    monkeypatch.setattr(billing, "_verify_payment_with_payu", _fake)
    yield


@pytest.fixture
def verify_must_not_be_called(monkeypatch):
    """Asserts the hash check short-circuits before PayU is ever contacted."""
    async def _fake(txnid):
        raise AssertionError("verify_payment was called despite a failed hash check")

    monkeypatch.setattr(billing, "_verify_payment_with_payu", _fake)
    yield


# ---------------------------------------------------------------------------
# 1-4: request hash + checkout session
# ---------------------------------------------------------------------------

def test_request_hash_matches_documented_sequence():
    """_request_hash follows key|txnid|amount|productinfo|firstname|email|udf1..udf10|salt."""
    udf1 = str(uuid4())
    produced = billing._request_hash("txn_1", "4999.00", "InvoiceAI-pro", "Test", "t@e.com", udf1)
    assert produced == _expected_request_hash("txn_1", "4999.00", "InvoiceAI-pro", "Test", "t@e.com", udf1)


def test_checkout_session_hash_recomputes_from_returned_fields(db_session):
    """The signed field set the browser posts to PayU is self-consistent."""
    _seed_tenant(db_session)
    response = client.post("/api/v1/billing/create-checkout-session", json={"plan": "pro"})
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["amount"] == billing.PLAN_AMOUNTS["pro"]
    assert data["productinfo"] == "InvoiceAI-pro"
    assert data["udf1"] == str(MOCK_TENANT_ID)
    assert data["hash"] == _expected_request_hash(
        data["txnid"], data["amount"], data["productinfo"],
        data["firstname"], data["email"], data["udf1"],
    )


def test_checkout_session_surl_furl_use_backend_public_url(db_session):
    """surl/furl point at the public origin, at the same path shape the
    backend itself serves -- that pairing is what makes the website
    pass-through (app/api/v1/billing/payu/*) work with no URL rewriting."""
    _seed_tenant(db_session)
    response = client.post("/api/v1/billing/create-checkout-session", json={"plan": "pro_combined"})
    assert response.status_code == 200
    data = response.json()

    assert data["surl"] == "https://website.example.com/api/v1/billing/payu/success"
    assert data["furl"] == "https://website.example.com/api/v1/billing/payu/failure"
    assert data["action_url"] == billing.PAYU_ACTION_URL["test"]
    assert data["amount"] == billing.PLAN_AMOUNTS["pro_combined"]


def test_checkout_session_non_admin_is_forbidden(db_session):
    """Only an Admin can start a checkout (test_viewer -> RoleMapper.NO_ROLE)."""
    _seed_tenant(db_session)
    response = client.post(
        "/api/v1/billing/create-checkout-session",
        json={"plan": "pro"},
        headers={"Authorization": "Bearer test_viewer"},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# 5-6: response-hash verification
# ---------------------------------------------------------------------------

def test_tampered_callback_is_rejected_before_contacting_payu(db_session, verify_must_not_be_called):
    """Amount rewritten after signing: the hash no longer matches, so the
    callback is refused and verify_payment is never reached."""
    tenant = _seed_tenant(db_session)
    form = _callback_form()
    form["amount"] = "1.00"  # tampered post-signature

    response = _post_callback("success", form)
    path, params = _redirect_query(response)
    assert path == "/billing/failed"
    assert params["reason"] == "hash_mismatch"

    db_session.refresh(tenant)
    assert tenant.billing_plan == "free"


def test_valid_response_hash_passes_the_signature_check(db_session, verify_success):
    """A correctly signed callback gets past step 1 and is acted on."""
    tenant = _seed_tenant(db_session)
    response = _post_callback("success", _callback_form())
    path, params = _redirect_query(response)
    assert path == "/billing/success"

    db_session.refresh(tenant)
    assert tenant.billing_plan == "pro"


# ---------------------------------------------------------------------------
# 7-13: fail_redirect reason branches
# ---------------------------------------------------------------------------

def test_callback_without_txnid_redirects_malformed(db_session):
    _seed_tenant(db_session)
    response = _post_callback("success", {"status": "success", "hash": "whatever"})
    path, params = _redirect_query(response)
    assert path == "/billing/failed"
    assert params["reason"] == "malformed"
    # Nothing to reference -- this is the one branch with no txnid to surface.
    assert "txnid" not in params


def test_hash_mismatch_branch_carries_txnid(db_session, verify_must_not_be_called):
    _seed_tenant(db_session)
    form = _callback_form(txnid="txn_mismatch", hash_override="deadbeef")
    _, params = _redirect_query(_post_callback("success", form))
    assert params["reason"] == "hash_mismatch"
    assert params["txnid"] == "txn_mismatch"


def test_unverifiable_branch_when_payu_cannot_be_reached(db_session, verify_unreachable):
    """Hash is valid but PayU's own servers can't confirm -- refuse to upgrade."""
    tenant = _seed_tenant(db_session)
    _, params = _redirect_query(_post_callback("success", _callback_form(txnid="txn_unreach")))
    assert params["reason"] == "unverifiable"
    assert params["txnid"] == "txn_unreach"

    db_session.refresh(tenant)
    assert tenant.billing_plan == "free"


def test_unknown_plan_branch_when_productinfo_unmapped(db_session, verify_success):
    """Verified success whose productinfo doesn't map to a known plan: the
    money moved, so this must not be reported as a plain decline."""
    tenant = _seed_tenant(db_session)
    form = _callback_form(txnid="txn_plan", productinfo="InvoiceAI-enterprise")
    _, params = _redirect_query(_post_callback("success", form))
    assert params["reason"] == "unknown_plan"
    assert params["txnid"] == "txn_plan"

    db_session.refresh(tenant)
    assert tenant.billing_plan == "free"


def test_unknown_plan_branch_when_productinfo_has_no_prefix(db_session, verify_success):
    """A productinfo that isn't ours at all also lands on unknown_plan."""
    form = _callback_form(productinfo="something-else")
    _, params = _redirect_query(_post_callback("success", form))
    assert params["reason"] == "unknown_plan"


def test_unknown_tenant_branch_when_udf1_is_not_a_uuid(db_session, verify_success):
    _seed_tenant(db_session)
    form = _callback_form(txnid="txn_baduuid", udf1="not-a-uuid")
    _, params = _redirect_query(_post_callback("success", form))
    assert params["reason"] == "unknown_tenant"
    assert params["txnid"] == "txn_baduuid"


def test_unknown_tenant_branch_when_tenant_row_is_missing(db_session, verify_success):
    """Well-formed tenant_id that no longer exists in the DB."""
    _seed_tenant(db_session)
    ghost = uuid4()
    form = _callback_form(txnid="txn_ghost", udf1=str(ghost))
    _, params = _redirect_query(_post_callback("success", form))
    assert params["reason"] == "unknown_tenant"
    assert params["txnid"] == "txn_ghost"


def test_plain_decline_redirects_with_txnid_and_no_reason(db_session, verify_failure):
    """PayU says the transaction failed: an honest decline, safe to retry --
    distinguished from the reason= branches by carrying no reason at all."""
    tenant = _seed_tenant(db_session)
    form = _callback_form(status_str="failure", txnid="txn_declined")
    path, params = _redirect_query(_post_callback("failure", form))
    assert path == "/billing/failed"
    assert params["txnid"] == "txn_declined"
    assert "reason" not in params

    db_session.refresh(tenant)
    assert tenant.billing_plan == "free"


# ---------------------------------------------------------------------------
# 14-16: plan + tenant resolution on the happy path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "productinfo,amount,expected_plan",
    [
        ("InvoiceAI-pro", "4999.00", "pro"),
        ("InvoiceAI-pro_combined", "8999.00", "pro_combined"),
    ],
)
def test_productinfo_maps_to_billing_plan(db_session, verify_success, productinfo, amount, expected_plan):
    tenant = _seed_tenant(db_session)
    form = _callback_form(productinfo=productinfo, amount=amount, txnid="txn_ok")
    path, params = _redirect_query(_post_callback("success", form))

    assert path == "/billing/success"
    assert params["plan"] == expected_plan
    assert params["txnid"] == "txn_ok"

    db_session.refresh(tenant)
    assert tenant.billing_plan == expected_plan
    assert tenant.payu_subscription_id == "txn_ok"


def test_udf1_selects_which_tenant_is_upgraded(db_session, verify_success):
    """The callback is unauthenticated -- udf1 is the only tenant identifier,
    so it must be what decides which row moves, and only that row."""
    paying = _seed_tenant(db_session, tenant_id=uuid4())
    bystander = _seed_tenant(db_session, tenant_id=uuid4())

    form = _callback_form(udf1=str(paying.id), txnid="txn_scoped")
    _redirect_query(_post_callback("success", form))

    db_session.refresh(paying)
    db_session.refresh(bystander)
    assert paying.billing_plan == "pro"
    assert bystander.billing_plan == "free"


# ---------------------------------------------------------------------------
# 17-19: a non-success status never mutates billing_plan
# ---------------------------------------------------------------------------

def test_callback_status_failure_never_upgrades(db_session, verify_success):
    """Even if PayU's verify API says success, a callback whose own status
    isn't success is not treated as a payment."""
    tenant = _seed_tenant(db_session)
    form = _callback_form(status_str="failure")
    _, params = _redirect_query(_post_callback("success", form))
    assert "reason" not in params

    db_session.refresh(tenant)
    assert tenant.billing_plan == "free"
    assert tenant.payu_subscription_id is None


def test_verified_status_failure_never_upgrades(db_session, verify_failure):
    """The inverse: the POST claims success, PayU's own records disagree."""
    tenant = _seed_tenant(db_session)
    _redirect_query(_post_callback("success", _callback_form(status_str="success")))

    db_session.refresh(tenant)
    assert tenant.billing_plan == "free"
    assert tenant.payu_subscription_id is None


def test_furl_endpoint_never_upgrades_even_on_a_verified_success(db_session, verify_success):
    """is_surl=False short-circuits: the failure URL can never grant a plan,
    regardless of what the POST or PayU claim."""
    tenant = _seed_tenant(db_session)
    path, params = _redirect_query(_post_callback("failure", _callback_form(status_str="success")))
    assert path == "/billing/failed"

    db_session.refresh(tenant)
    assert tenant.billing_plan == "free"
    assert tenant.payu_subscription_id is None


# ---------------------------------------------------------------------------
# 20-24: GET /billing/usage (Gap 143)
#
# The point of this endpoint is that the number rendered on the billing screen
# and the number the ingestion gate enforces are the *same* number, so these
# assert against `free_invoices_remaining` and settings.DEFAULT_FREE_INVOICES_
# LIMIT rather than against any literal the UI might carry.
# ---------------------------------------------------------------------------

def test_usage_reports_the_backend_limit_not_a_ui_literal(db_session):
    """A fresh free tenant: full allowance, nothing used, limit straight from
    config. The UI used to hard-code 25 against a real limit of 50."""
    _seed_tenant(db_session)
    response = client.get("/api/v1/billing/usage")
    assert response.status_code == 200, response.text
    data = response.json()

    limit = billing.settings.DEFAULT_FREE_INVOICES_LIMIT
    assert data["plan"] == "free"
    assert data["metered"] is True
    assert data["limit"] == limit
    assert data["remaining"] == limit
    assert data["used"] == 0
    # Gap 118's cycle clock is seeded on first contact by refresh_free_quota(),
    # so the screen always has a real reset date to show.
    assert data["resets_at"] is not None


def test_usage_tracks_the_same_counter_the_ingestion_gate_reads(db_session):
    """Spending quota is immediately visible as `used` -- this is the property
    that client-side invoice counting could never have."""
    limit = billing.settings.DEFAULT_FREE_INVOICES_LIMIT
    _seed_tenant(db_session, remaining=limit - 13)

    data = client.get("/api/v1/billing/usage").json()
    assert data["used"] == 13
    assert data["remaining"] == limit - 13
    assert data["limit"] == limit


@pytest.mark.parametrize("plan", ["pro", "pro_combined", "unpaid"])
def test_usage_on_a_non_free_plan_reports_no_metered_allowance(db_session, plan):
    """routers/invoices.py only enforces free_invoices_remaining on the free
    plan, so every other plan reports metered=False with no numbers at all --
    deliberately not the Pro tier's advertised 1,000 cap, which does not exist
    in the software (BE Gap 188)."""
    _seed_tenant(db_session, plan=plan)
    response = client.get("/api/v1/billing/usage")
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["plan"] == plan
    assert data["metered"] is False
    assert data["used"] is None
    assert data["limit"] is None
    assert data["remaining"] is None
    assert data["resets_at"] is None


def test_usage_is_readable_by_a_non_admin(db_session):
    """Unlike create-checkout-session (403 for a permission-less user above), reading your own
    workspace's allowance is not an Admin action -- a non-Admin who can ingest
    is exactly who hits the 402 this number predicts."""
    _seed_tenant(db_session)
    response = client.get(
        "/api/v1/billing/usage",
        headers={"Authorization": "Bearer test_viewer"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["metered"] is True


@pytest.mark.parametrize("stored,expected_remaining", [(-3, 0), (10_000, None)])
def test_usage_clamps_a_counter_outside_the_allowance(db_session, stored, expected_remaining):
    """BE Gap 189 can drive the counter negative, and a row seeded before the
    limit last changed can exceed it. Neither may render as a negative bar."""
    limit = billing.settings.DEFAULT_FREE_INVOICES_LIMIT
    _seed_tenant(db_session, remaining=stored)

    data = client.get("/api/v1/billing/usage").json()
    assert data["remaining"] == (limit if expected_remaining is None else expected_remaining)
    assert data["used"] == limit - data["remaining"]
    assert data["used"] >= 0
