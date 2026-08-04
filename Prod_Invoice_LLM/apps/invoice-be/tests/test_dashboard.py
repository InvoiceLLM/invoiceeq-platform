import pytest
from unittest.mock import patch
from uuid import uuid4
from datetime import date, datetime
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Invoice, ExtractionTemplate

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)

client = TestClient(app)

@pytest.fixture(name="db_session")
def db_session_fixture():
    """Yields clean isolated test database session."""
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)

@pytest.fixture(autouse=True)
def override_db_session(db_session):
    """Overrides dependencies database session."""
    def get_db_session_override():
        yield db_session
    app.dependency_overrides[get_db_session] = get_db_session_override
    yield
    app.dependency_overrides.clear()

def populate_mock_invoices(db_session):
    """Utility to load a diverse set of invoices."""
    inv1 = Invoice(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/invoice1.pdf",
        vendor_name="ACME",
        grand_total=1000.0,
        invoice_date=date(2026, 6, 20),
        status="PAID",
        po_number="PO-100",
        sa_alerts=[]
    )
    inv2 = Invoice(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/invoice2.pdf",
        vendor_name="Globex",
        grand_total=500.0,
        invoice_date=date(2026, 6, 22),
        status="AUDIT_REQUIRED",
        po_number="PO-200",
        sa_alerts=["Math mismatch"]
    )
    inv3 = Invoice(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/invoice3.pdf",
        vendor_name="ACME",
        grand_total=250.0,
        invoice_date=date(2026, 6, 25),
        status="COMPLETED",
        po_number="PO-100",
        sa_alerts=[]
    )
    # Other tenant invoice
    inv_other = Invoice(
        id=uuid4(),
        tenant_id=uuid4(),
        file_path="mock/invoice_other.pdf",
        vendor_name="Globex",
        grand_total=9999.0,
        invoice_date=date(2026, 6, 22),
        status="PAID",
        po_number="PO-200",
        sa_alerts=[]
    )
    db_session.add(inv1)
    db_session.add(inv2)
    db_session.add(inv3)
    db_session.add(inv_other)
    db_session.commit()

def test_aggregate_metrics(db_session):
    """Verify primary aggregate mathematics work correctly."""
    populate_mock_invoices(db_session)
    
    response = client.get("/api/v1/dashboard/metrics")
    assert response.status_code == 200
    data = response.json()
    
    # 1000 + 500 + 250 = 1750 (inv_other excluded due to tenant isolation)
    assert data["total_invoiced"] == 1750.0
    assert data["paid_amount"] == 1000.0
    assert data["outstanding_amount"] == 750.0 # 500 + 250
    assert data["at_risk_amount"] == 500.0
    assert data["active_alerts_count"] == 1
    assert isinstance(data["average_processing_time"], float)
    assert isinstance(data["extraction_accuracy"], float)
    
    # Check top vendors grouping
    top_vendors = data["top_vendors"]
    assert len(top_vendors) == 2
    assert top_vendors[0]["vendor_name"] == "ACME"
    assert top_vendors[0]["amount"] == 1250.0
    assert top_vendors[1]["vendor_name"] == "Globex"
    assert top_vendors[1]["amount"] == 500.0
    
    # Check trend timeline sorted order
    spend_over_time = data["spend_over_time"]
    assert len(spend_over_time) == 3
    assert spend_over_time[0]["date"] == "2026-06-20"
    assert spend_over_time[0]["amount"] == 1000.0
    assert spend_over_time[2]["date"] == "2026-06-25"
    assert spend_over_time[2]["amount"] == 250.0

def test_metrics_filters(db_session):
    """Verify filters apply correctly to limit data scope."""
    populate_mock_invoices(db_session)

    # 1. Filter by vendor
    response = client.get("/api/v1/dashboard/metrics?vendor_name=ACME")
    assert response.status_code == 200
    data = response.json()
    assert data["total_invoiced"] == 1250.0
    assert len(data["top_vendors"]) == 1

    # 2. Filter by date range
    response = client.get("/api/v1/dashboard/metrics?start_date=2026-06-21&end_date=2026-06-24")
    assert response.status_code == 200
    data = response.json()
    assert data["total_invoiced"] == 500.0
    assert data["outstanding_amount"] == 500.0

    # 3. Filter by PO Number
    response = client.get("/api/v1/dashboard/metrics?po_number=PO-100")
    assert response.status_code == 200
    data = response.json()
    assert data["total_invoiced"] == 1250.0

    # 4. Filter by status
    response = client.get("/api/v1/dashboard/metrics?status=PAID")
    assert response.status_code == 200
    data = response.json()
    assert data["total_invoiced"] == 1000.0


def test_trainer_impact(db_session):
    """Gap 28: rules-trained count, audit-rate trend, vendors still needing a rule."""
    # Globex has 2 flagged invoices and no rule yet -> should surface as needing one.
    # ACME has a rule already, so even if flagged it should be excluded.
    db_session.add(ExtractionTemplate(
        tenant_id=MOCK_TENANT_ID, vendor_name="ACME", rules={"constraints": ["some rule"]}
    ))
    db_session.add(ExtractionTemplate(
        tenant_id=MOCK_TENANT_ID, vendor_name=None, rules={"constraints": ["a global rule"]}
    ))
    db_session.add(Invoice(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/a1.pdf",
        vendor_name="ACME", status="AUDIT_REQUIRED", sa_alerts=[{"type": "x", "message": "m"}]
    ))
    db_session.add(Invoice(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/g1.pdf",
        vendor_name="Globex", status="AUDIT_REQUIRED", sa_alerts=[{"type": "x", "message": "m"}]
    ))
    db_session.add(Invoice(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/g2.pdf",
        vendor_name="Globex", status="AUDIT_REQUIRED", sa_alerts=[{"type": "x", "message": "m"}]
    ))
    # A one-off flagged vendor (only 1 flagged invoice) should NOT surface - below threshold.
    db_session.add(Invoice(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/o1.pdf",
        vendor_name="OneOff Co", status="AUDIT_REQUIRED", sa_alerts=[{"type": "x", "message": "m"}]
    ))
    db_session.commit()

    response = client.get("/api/v1/dashboard/trainer-impact")
    assert response.status_code == 200
    data = response.json()

    assert data["rules_trained"] == {"global": 1, "vendor_specific": 1, "total": 2}

    vendors = {v["vendor_name"]: v["flagged_invoice_count"] for v in data["vendors_needing_rules"]}
    assert vendors == {"Globex": 2}
    assert "ACME" not in vendors
    assert "OneOff Co" not in vendors

    assert isinstance(data["audit_rate_trend"], list)
    assert len(data["audit_rate_trend"]) >= 1
    week = data["audit_rate_trend"][0]
    assert set(week.keys()) == {"week", "audit_rate", "total_processed"}


@pytest.fixture(autouse=True)
def _clear_insights_cache():
    """Gap 30's endpoint caches in real Redis keyed only on tenant_id, and every
    test here shares MOCK_TENANT_ID -- without clearing it, one test's cached
    LLM response leaks into the next and hides real failures."""
    from routers.dashboard import _get_redis_client, _insights_cache_key
    try:
        _get_redis_client().delete(_insights_cache_key(MOCK_TENANT_ID))
    except Exception:
        pass
    yield
    try:
        _get_redis_client().delete(_insights_cache_key(MOCK_TENANT_ID))
    except Exception:
        pass


def test_dashboard_insights_empty(db_session):
    """Gap 30: no invoices at all -> no LLM call, empty insights list."""
    with patch("routers.dashboard.get_llm") as mock_get_llm:
        response = client.get("/api/v1/dashboard/insights")
        assert response.status_code == 200
        assert response.json() == {"insights": []}
        mock_get_llm.assert_not_called()


def test_dashboard_insights_grounded(db_session):
    """Gap 30: the LLM call happens and its structured output is returned verbatim;
    also confirms the prompt context actually carries real computed numbers, not
    placeholders, since that's the entire point of grounding this in real data."""
    populate_mock_invoices(db_session)

    from routers.dashboard import DashboardInsightsSchema, DashboardInsight

    mock_schema = DashboardInsightsSchema(insights=[
        DashboardInsight(title="Concentration risk", detail="ACME accounts for most spend.", severity="warning")
    ])

    captured_prompt = {}

    class MockStructuredLLM:
        def invoke(self, prompt):
            captured_prompt["text"] = prompt
            return mock_schema

    class MockLLM:
        def with_structured_output(self, schema):
            return MockStructuredLLM()

    with patch("routers.dashboard.get_llm") as mock_get_llm:
        mock_get_llm.return_value = MockLLM()
        response = client.get("/api/v1/dashboard/insights")
        assert response.status_code == 200
        data = response.json()
        assert data == {"insights": [
            {"title": "Concentration risk", "detail": "ACME accounts for most spend.", "severity": "warning"}
        ]}

    # ACME's real combined spend (1000 + 250 = 1250) must actually be in what
    # the LLM was shown, not a placeholder -- this is the grounding guarantee.
    assert "1250" in captured_prompt["text"]
    assert "ACME" in captured_prompt["text"]


def test_dashboard_insights_llm_failure_returns_empty(db_session):
    """Gap 30: an LLM/schema failure degrades to an empty list, not a 500."""
    populate_mock_invoices(db_session)

    class MockLLM:
        def with_structured_output(self, schema):
            raise RuntimeError("simulated LLM failure")

    with patch("routers.dashboard.get_llm") as mock_get_llm:
        mock_get_llm.return_value = MockLLM()
        response = client.get("/api/v1/dashboard/insights")
        assert response.status_code == 200
        assert response.json() == {"insights": []}


def test_ai_score_metrics(db_session):
    """Verify AI extraction accuracy, alert response accuracy, and missed alerts escape rate."""
    # 1. Create a resolved invoice with 1 field correction.
    # Total fields = 7. Corrected = 1. Field extraction = 6 / 7 = 85.7%
    inv1_id = uuid4()
    inv1 = Invoice(
        id=inv1_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/invoice1.pdf",
        status="AUDIT_REQUIRED",
        grand_total=100.0,
        sa_alerts=[]
    )
    db_session.add(inv1)
    db_session.commit()

    # Resolve it as PAID with corrections
    payload1 = {
        "status": "PAID",
        "corrections": {"grand_total": 90.0}
    }
    res = client.put(f"/api/v1/audit/resolve/{inv1_id}", json=payload1)
    assert res.status_code == 200

    # 2. Create another resolved invoice with 2 alerts, 1 dismissed, 1 not dismissed.
    # Dismissed = False alarm (1), Not dismissed = Correct alert (1).
    # Alert accuracy = 1 / 2 = 50.0%
    inv2_id = uuid4()
    inv2 = Invoice(
        id=inv2_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/invoice2.pdf",
        status="AUDIT_REQUIRED",
        sa_alerts=["Math mismatch", "Invalid vendor"]
    )
    db_session.add(inv2)
    db_session.commit()

    payload2 = {
        "status": "PAID",
        "dismissed_alerts": ["Math mismatch"]
    }
    res = client.put(f"/api/v1/audit/resolve/{inv2_id}", json=payload2)
    assert res.status_code == 200

    # 3. Create a rejected invoice with AI Extraction Error reason.
    # Rejections with AI error = 1. Total rejections = 1. Escape rate = 100.0%
    inv3_id = uuid4()
    inv3 = Invoice(
        id=inv3_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/invoice3.pdf",
        status="AUDIT_REQUIRED",
        sa_alerts=[]
    )
    db_session.add(inv3)
    db_session.commit()

    payload3 = {
        "status": "REJECTED",
        "reject_reason": "AI Extraction Error"
    }
    res = client.put(f"/api/v1/audit/resolve/{inv3_id}", json=payload3)
    assert res.status_code == 200

    # Retrieve metrics
    response = client.get("/api/v1/dashboard/metrics")
    assert response.status_code == 200
    data = response.json()

    assert "ai_field_extraction" in data
    assert "ai_alert_response" in data
    assert "ai_alerts_missed" in data

    # Expected field extraction:
    # Invoice 1: 1 correction out of 7 fields -> 6 correct.
    # Invoice 2: 0 corrections -> 7 correct.
    # Invoice 3: 0 corrections -> 7 correct.
    # Total fields = 21. Total correct = 20. Accuracy = 20 / 21 = 95.2% (approx 95.238%)
    assert abs(data["ai_field_extraction"] - 95.238) < 0.1

    # Expected alert response:
    # Invoice 2 has 2 alerts. 1 is dismissed (false alarm). 1 remains (correct alert).
    # Alert accuracy = 1 / 2 = 50.0%
    assert data["ai_alert_response"] == 50.0

    # Expected escape rate:
    # 1 rejection with reject_reason="AI Extraction Error" out of 3 total processed.
    # Escape rate = 33.3%
    assert data["ai_alerts_missed"] == 33.3

