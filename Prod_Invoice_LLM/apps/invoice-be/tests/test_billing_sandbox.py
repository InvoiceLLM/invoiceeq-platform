"""
Gap 355: Payment Gateway Sandbox Integration & Simulation Test Suite.
Mapped to Category 2 Defects: B-01, B-03, B-05, B-06, B-07.

This test suite simulates complete end-to-end payment gateway lifecycles against
the PayU sandbox contract without real money debit:
1. End-to-End Success flows for Pro and Pro Combined plans (checkout -> hash -> callback -> DB upgrade -> paid_through extension).
2. Failure & Security branches (declines, SHA-512 hash tampering, timeouts, malformed payloads).
3. Lapsed tenant recovery (unpaid tenant unlocking via new checkout).
4. Idempotency under duplicate webhook/callback delivery.
"""
import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

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
def payu_sandbox_credentials(monkeypatch):
    """Set test credentials and mock endpoints for sandbox simulation."""
    monkeypatch.setattr(billing.settings, "PAYU_MERCHANT_KEY", TEST_KEY)
    monkeypatch.setattr(billing.settings, "PAYU_MERCHANT_SALT", TEST_SALT)
    monkeypatch.setattr(billing.settings, "PAYU_MODE", "test")
    monkeypatch.setattr(billing.settings, "BACKEND_PUBLIC_URL", "https://website.example.com")
    monkeypatch.setattr(billing.settings, "PUBLIC_APP_URL", "https://website.example.com")
    yield


def _seed_sandbox_tenant(
    db_session: Session,
    tenant_id: UUID = MOCK_TENANT_ID,
    plan: str = "free",
    paid_through: datetime | None = None,
) -> Tenant:
    tenant = Tenant(
        id=tenant_id,
        name="Sandbox Acme Corp",
        domain=f"{tenant_id}.example.com",
        billing_plan=plan,
        paid_through=paid_through,
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.refresh(tenant)
    return tenant


def _calculate_payu_response_hash(status_str, txnid, amount, productinfo, firstname, email, udf1):
    parts = [
        TEST_SALT, status_str,
        "", "", "", "", "", "", "", "", "", udf1,  # udf10..udf1
        email, firstname, productinfo, amount, txnid, TEST_KEY,
    ]
    return hashlib.sha512("|".join(parts).encode("utf-8")).hexdigest()


def _redirect_query(response):
    assert response.status_code == 303, response.text
    parsed = urlparse(response.headers["location"])
    flat = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    return parsed.path, flat


# ---------------------------------------------------------------------------
# Gap 355 Tests
# ---------------------------------------------------------------------------

class TestPayUSandboxLifecycle:
    """End-to-end sandbox payment simulation test cases (B-01, B-03, B-05, B-06, B-07)."""

    def test_sandbox_pro_checkout_and_success_flow(self, db_session, monkeypatch):
        """B-01 & B-03: Simulate complete checkout, hash verification, and DB promotion for Pro plan."""
        tenant = _seed_sandbox_tenant(db_session, plan="free")
        assert tenant.billing_plan == "free"
        assert tenant.paid_through is None

        # 1. Create Checkout Session
        checkout_res = client.post("/api/v1/billing/create-checkout-session", json={"plan": "pro"})
        assert checkout_res.status_code == 200
        payload = checkout_res.json()

        assert payload["action_url"] == "https://test.payu.in/_payment"
        assert payload["key"] == TEST_KEY
        assert payload["amount"] == "4999.00"
        assert payload["productinfo"] == "InvoiceAI-pro"
        assert payload["udf1"] == str(MOCK_TENANT_ID)
        assert "hash" in payload
        assert payload["surl"] == "https://website.example.com/api/v1/billing/payu/success"
        assert payload["furl"] == "https://website.example.com/api/v1/billing/payu/failure"

        txnid = payload["txnid"]

        # 2. Mock PayU verify_payment server-to-server check
        async def _mock_verify(tx):
            assert tx == txnid
            return "success"
        monkeypatch.setattr(billing, "_verify_payment_with_payu", _mock_verify)

        # 3. Simulate PayU SURL Callback
        form_data = {
            "status": "success",
            "txnid": txnid,
            "amount": "4999.00",
            "productinfo": "InvoiceAI-pro",
            "firstname": "Test",
            "email": "admin@example.com",
            "udf1": str(MOCK_TENANT_ID),
            "hash": _calculate_payu_response_hash(
                "success", txnid, "4999.00", "InvoiceAI-pro", "Test", "admin@example.com", str(MOCK_TENANT_ID)
            ),
        }
        callback_res = client.post("/api/v1/billing/payu/success", data=form_data, follow_redirects=False)
        path, params = _redirect_query(callback_res)

        # 4. Assert Success Redirect
        assert path == "/billing/success"
        assert params["plan"] == "pro"
        assert params["txnid"] == txnid

        # 5. Assert Database Updates
        db_session.refresh(tenant)
        assert tenant.billing_plan == "pro"
        assert tenant.paid_through is not None
        # Normalize naive/aware for SQLite
        pt = tenant.paid_through.replace(tzinfo=timezone.utc) if tenant.paid_through.tzinfo is None else tenant.paid_through
        now = datetime.now(timezone.utc)
        diff = (pt - now).total_seconds()
        assert 28 * 86400 <= diff <= 32 * 86400

    def test_sandbox_pro_combined_checkout_and_success_flow(self, db_session, monkeypatch):
        """B-01 & B-03: Simulate complete checkout and promotion for Pro Combined plan (₹8,999)."""
        tenant = _seed_sandbox_tenant(db_session, plan="free")

        checkout_res = client.post("/api/v1/billing/create-checkout-session", json={"plan": "pro_combined"})
        assert checkout_res.status_code == 200
        payload = checkout_res.json()
        assert payload["amount"] == "8999.00"
        assert payload["productinfo"] == "InvoiceAI-pro_combined"

        txnid = payload["txnid"]

        async def _mock_verify(tx):
            return "success"
        monkeypatch.setattr(billing, "_verify_payment_with_payu", _mock_verify)

        form_data = {
            "status": "success",
            "txnid": txnid,
            "amount": "8999.00",
            "productinfo": "InvoiceAI-pro_combined",
            "firstname": "Test",
            "email": "admin@example.com",
            "udf1": str(MOCK_TENANT_ID),
            "hash": _calculate_payu_response_hash(
                "success", txnid, "8999.00", "InvoiceAI-pro_combined", "Test", "admin@example.com", str(MOCK_TENANT_ID)
            ),
        }
        callback_res = client.post("/api/v1/billing/payu/success", data=form_data, follow_redirects=False)
        path, params = _redirect_query(callback_res)

        assert path == "/billing/success"
        assert params["plan"] == "pro_combined"
        assert params["txnid"] == txnid

        db_session.refresh(tenant)
        assert tenant.billing_plan == "pro_combined"
        assert tenant.paid_through is not None

    def test_sandbox_card_declined_failure_flow(self, db_session, monkeypatch):
        """B-05: Simulate card decline / bank payment failure and verify clean failure routing."""
        tenant = _seed_sandbox_tenant(db_session, plan="free")
        txnid = f"txn_declined_{uuid4().hex[:8]}"

        async def _mock_verify(tx):
            return "failure"
        monkeypatch.setattr(billing, "_verify_payment_with_payu", _mock_verify)

        form_data = {
            "status": "failure",
            "txnid": txnid,
            "amount": "4999.00",
            "productinfo": "InvoiceAI-pro",
            "firstname": "Test",
            "email": "admin@example.com",
            "udf1": str(MOCK_TENANT_ID),
            "hash": _calculate_payu_response_hash(
                "failure", txnid, "4999.00", "InvoiceAI-pro", "Test", "admin@example.com", str(MOCK_TENANT_ID)
            ),
        }
        callback_res = client.post("/api/v1/billing/payu/failure", data=form_data, follow_redirects=False)
        path, params = _redirect_query(callback_res)

        assert path == "/billing/failed"
        assert params["txnid"] == txnid
        assert "reason" not in params  # Normal user decline allows retry CTA

        db_session.refresh(tenant)
        assert tenant.billing_plan == "free"

    def test_sandbox_hash_tampering_attack_rejected(self, db_session, monkeypatch):
        """B-03 & B-05: Security test — payload tampering produces hash_mismatch."""
        tenant = _seed_sandbox_tenant(db_session, plan="free")
        txnid = f"txn_tampered_{uuid4().hex[:8]}"

        # Attacker tries to pay ₹1.00 instead of ₹4999.00
        form_data = {
            "status": "success",
            "txnid": txnid,
            "amount": "1.00",
            "productinfo": "InvoiceAI-pro",
            "firstname": "Test",
            "email": "admin@example.com",
            "udf1": str(MOCK_TENANT_ID),
            "hash": "bad_hash_signature_00000000000000000000",
        }
        callback_res = client.post("/api/v1/billing/payu/success", data=form_data, follow_redirects=False)
        path, params = _redirect_query(callback_res)

        assert path == "/billing/failed"
        assert params["reason"] == "hash_mismatch"
        assert params["txnid"] == txnid

        db_session.refresh(tenant)
        assert tenant.billing_plan == "free"

    def test_sandbox_downstream_timeout_graceful_recovery(self, db_session, monkeypatch):
        """B-05: Graceful error handling when PayU verify_payment endpoint is unreachable."""
        tenant = _seed_sandbox_tenant(db_session, plan="free")
        txnid = f"txn_timeout_{uuid4().hex[:8]}"

        async def _mock_timeout(tx):
            return None  # Unverifiable network timeout
        monkeypatch.setattr(billing, "_verify_payment_with_payu", _mock_timeout)

        form_data = {
            "status": "success",
            "txnid": txnid,
            "amount": "4999.00",
            "productinfo": "InvoiceAI-pro",
            "firstname": "Test",
            "email": "admin@example.com",
            "udf1": str(MOCK_TENANT_ID),
            "hash": _calculate_payu_response_hash(
                "success", txnid, "4999.00", "InvoiceAI-pro", "Test", "admin@example.com", str(MOCK_TENANT_ID)
            ),
        }
        callback_res = client.post("/api/v1/billing/payu/success", data=form_data, follow_redirects=False)
        path, params = _redirect_query(callback_res)

        assert path == "/billing/failed"
        assert params["reason"] == "unverifiable"
        assert params["txnid"] == txnid

        db_session.refresh(tenant)
        assert tenant.billing_plan == "free"

    def test_sandbox_lapsed_unpaid_tenant_recovery(self, db_session, monkeypatch):
        """B-06: A tenant locked out as 'unpaid' can initiate checkout and successfully recover."""
        expired_date = datetime.now(timezone.utc) - timedelta(days=5)
        tenant = _seed_sandbox_tenant(db_session, plan="unpaid", paid_through=expired_date)
        assert tenant.billing_plan == "unpaid"

        # 1. Initiate checkout as unpaid tenant (must be permitted via get_tenant_context_allow_unpaid)
        checkout_res = client.post("/api/v1/billing/create-checkout-session", json={"plan": "pro"})
        assert checkout_res.status_code == 200
        payload = checkout_res.json()
        txnid = payload["txnid"]

        # 2. Mock payment confirmation
        async def _mock_verify(tx):
            return "success"
        monkeypatch.setattr(billing, "_verify_payment_with_payu", _mock_verify)

        # 3. Deliver success callback
        form_data = {
            "status": "success",
            "txnid": txnid,
            "amount": "4999.00",
            "productinfo": "InvoiceAI-pro",
            "firstname": "Recovering",
            "email": "admin@example.com",
            "udf1": str(MOCK_TENANT_ID),
            "hash": _calculate_payu_response_hash(
                "success", txnid, "4999.00", "InvoiceAI-pro", "Recovering", "admin@example.com", str(MOCK_TENANT_ID)
            ),
        }
        callback_res = client.post("/api/v1/billing/payu/success", data=form_data, follow_redirects=False)
        path, params = _redirect_query(callback_res)

        assert path == "/billing/success"
        assert params["plan"] == "pro"

        # 4. Verify tenant is unlocked and paid_through extended
        db_session.refresh(tenant)
        assert tenant.billing_plan == "pro"
        pt = tenant.paid_through.replace(tzinfo=timezone.utc) if tenant.paid_through.tzinfo is None else tenant.paid_through
        assert pt > datetime.now(timezone.utc)

    def test_sandbox_idempotent_duplicate_callback(self, db_session, monkeypatch):
        """B-07: Verify duplicate webhook/callback delivery does not crash or corrupt state."""
        tenant = _seed_sandbox_tenant(db_session, plan="free")
        txnid = f"txn_dup_{uuid4().hex[:8]}"

        async def _mock_verify(tx):
            return "success"
        monkeypatch.setattr(billing, "_verify_payment_with_payu", _mock_verify)

        form_data = {
            "status": "success",
            "txnid": txnid,
            "amount": "4999.00",
            "productinfo": "InvoiceAI-pro",
            "firstname": "Test",
            "email": "admin@example.com",
            "udf1": str(MOCK_TENANT_ID),
            "hash": _calculate_payu_response_hash(
                "success", txnid, "4999.00", "InvoiceAI-pro", "Test", "admin@example.com", str(MOCK_TENANT_ID)
            ),
        }

        # First callback
        res1 = client.post("/api/v1/billing/payu/success", data=form_data, follow_redirects=False)
        assert res1.status_code == 303
        db_session.refresh(tenant)
        assert tenant.billing_plan == "pro"

        # Second identical callback
        res2 = client.post("/api/v1/billing/payu/success", data=form_data, follow_redirects=False)
        assert res2.status_code == 303
        db_session.refresh(tenant)
        assert tenant.billing_plan == "pro"
