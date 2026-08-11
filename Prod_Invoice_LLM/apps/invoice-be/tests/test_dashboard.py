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

def _totals(data, currency="USD"):
    """FE Gap 183: the endpoint no longer returns flat blended scalars, so
    every assertion below reads the one currency row it means. Raises rather
    than defaulting -- a missing currency row is a real failure, not a zero."""
    rows = [r for r in data["totals_by_currency"] if r["currency"] == currency]
    assert rows, f"no {currency} row in {data['totals_by_currency']}"
    return rows[0]


def test_aggregate_metrics(db_session):
    """Verify primary aggregate mathematics work correctly."""
    populate_mock_invoices(db_session)

    response = client.get("/api/v1/dashboard/metrics")
    assert response.status_code == 200
    data = response.json()

    # FE Gap 183: these fixtures carry no currency at all (a real historical
    # state -- the column is nullable and was never backfilled), so they must
    # all land in one COALESCE'd "USD" bucket rather than a null/"" one.
    assert len(data["totals_by_currency"]) == 1
    usd = _totals(data)
    # 1000 + 500 + 250 = 1750 (inv_other excluded due to tenant isolation)
    assert usd["total_invoiced"] == 1750.0
    assert usd["paid_amount"] == 1000.0
    assert usd["outstanding_amount"] == 750.0 # 500 + 250
    assert usd["at_risk_amount"] == 500.0
    assert data["active_alerts_count"] == 1
    assert isinstance(data["average_processing_time"], float)
    assert isinstance(data["extraction_accuracy"], float)

    # Check top vendors grouping
    top_vendors = data["top_vendors"]
    assert len(top_vendors) == 2
    assert top_vendors[0]["vendor_name"] == "ACME"
    assert top_vendors[0]["currency"] == "USD"
    assert top_vendors[0]["amount"] == 1250.0
    assert top_vendors[1]["vendor_name"] == "Globex"
    assert top_vendors[1]["currency"] == "USD"
    assert top_vendors[1]["amount"] == 500.0

    # Check trend timeline sorted order
    spend_over_time = data["spend_over_time"]
    assert len(spend_over_time) == 3
    assert spend_over_time[0]["date"] == "2026-06-20"
    assert spend_over_time[0]["currency"] == "USD"
    assert spend_over_time[0]["amount"] == 1000.0
    assert spend_over_time[2]["date"] == "2026-06-25"
    assert spend_over_time[2]["amount"] == 250.0


def test_blended_cross_currency_scalars_are_gone(db_session):
    """FE Gap 183: the old flat keys summed grand_total across every currency
    and the FE then stamped a "$" on the result. They are removed outright --
    not kept alongside totals_by_currency -- so nothing can render a blended
    figure by accident. This test is the guard against them creeping back."""
    populate_mock_invoices(db_session)

    data = client.get("/api/v1/dashboard/metrics").json()
    for forbidden in ("total_invoiced", "paid_amount", "outstanding_amount", "at_risk_amount"):
        assert forbidden not in data


def test_multi_currency_totals_are_broken_out_never_blended(db_session):
    """FE Gap 183, the bug this gap exists for: a tenant with a $500 invoice
    and a ₹40,000 one used to be reported as a single "40500". Each currency
    now gets its own row and no key anywhere holds their sum."""
    db_session.add(Invoice(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/usd.pdf",
        vendor_name="ACME", grand_total=500.0, currency="USD",
        invoice_date=date(2026, 6, 20), status="PAID", sa_alerts=[],
    ))
    db_session.add(Invoice(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/inr.pdf",
        vendor_name="ACME", grand_total=40000.0, currency="INR",
        invoice_date=date(2026, 6, 20), status="AUDIT_REQUIRED", sa_alerts=[],
    ))
    # Lower-case and blank codes must fold into the same buckets, not create
    # phantom currencies ("inr" is a real thing an LLM extraction returns).
    db_session.add(Invoice(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/inr2.pdf",
        vendor_name="Globex", grand_total=1000.0, currency="inr",
        invoice_date=date(2026, 6, 21), status="PAID", sa_alerts=[],
    ))
    db_session.add(Invoice(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/blank.pdf",
        vendor_name="Globex", grand_total=250.0, currency="   ",
        invoice_date=date(2026, 6, 21), status="PAID", sa_alerts=[],
    ))
    db_session.commit()

    data = client.get("/api/v1/dashboard/metrics").json()

    assert {r["currency"] for r in data["totals_by_currency"]} == {"USD", "INR"}
    usd = _totals(data, "USD")
    inr = _totals(data, "INR")
    assert usd["total_invoiced"] == 750.0     # 500 + the blank-currency 250
    assert usd["paid_amount"] == 750.0
    assert inr["total_invoiced"] == 41000.0   # 40000 + the lower-case 1000
    assert inr["paid_amount"] == 1000.0
    assert inr["at_risk_amount"] == 40000.0
    assert usd["at_risk_amount"] == 0.0

    # 40500 / 41750 -- the blended figures -- must not appear anywhere.
    assert not any(
        r["total_invoiced"] in (40500.0, 41750.0) for r in data["totals_by_currency"]
    )

    # ACME billed in both currencies: two rows, never one summed row.
    acme = {(v["currency"], v["amount"]) for v in data["top_vendors"] if v["vendor_name"] == "ACME"}
    assert acme == {("USD", 500.0), ("INR", 40000.0)}

    # Same day, two currencies -> two separate trend points.
    june20 = {(p["currency"], p["amount"]) for p in data["spend_over_time"] if p["date"] == "2026-06-20"}
    assert june20 == {("USD", 500.0), ("INR", 40000.0)}


def test_metrics_filters(db_session):
    """Verify filters apply correctly to limit data scope."""
    populate_mock_invoices(db_session)

    # 1. Filter by vendor
    response = client.get("/api/v1/dashboard/metrics?vendor_name=ACME")
    assert response.status_code == 200
    data = response.json()
    assert _totals(data)["total_invoiced"] == 1250.0
    assert len(data["top_vendors"]) == 1

    # 2. Filter by date range
    response = client.get("/api/v1/dashboard/metrics?start_date=2026-06-21&end_date=2026-06-24")
    assert response.status_code == 200
    data = response.json()
    assert _totals(data)["total_invoiced"] == 500.0
    assert _totals(data)["outstanding_amount"] == 500.0

    # 3. Filter by PO Number
    response = client.get("/api/v1/dashboard/metrics?po_number=PO-100")
    assert response.status_code == 200
    data = response.json()
    assert _totals(data)["total_invoiced"] == 1250.0

    # 4. Filter by status
    response = client.get("/api/v1/dashboard/metrics?status=PAID")
    assert response.status_code == 200
    data = response.json()
    assert _totals(data)["total_invoiced"] == 1000.0


def test_empty_tenant_returns_empty_currency_list(db_session):
    """FE Gap 183: no invoices -> no currency rows at all, rather than a
    fabricated USD zero row. The FE renders its own zero placeholder."""
    data = client.get("/api/v1/dashboard/metrics").json()
    assert data["totals_by_currency"] == []
    assert data["top_vendors"] == []
    assert data["spend_over_time"] == []


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

    # FE Gap 183: the money facts handed to the model are keyed by currency and
    # the model is told never to combine across currencies.
    assert "totals_by_currency" in captured_prompt["text"]
    assert '"currency": "USD"' in captured_prompt["text"]
    assert "Never add, subtract, average or otherwise combine amounts in different currencies" in captured_prompt["text"]


def test_dashboard_insights_prompt_never_blends_currencies(db_session):
    """FE Gap 183: with two currencies present, the prompt must carry two
    separate totals and never their sum -- the "grounding" fact the model was
    previously given was arithmetic across incomparable units."""
    db_session.add(Invoice(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/usd.pdf",
        vendor_name="ACME", grand_total=500.0, currency="USD", status="PAID", sa_alerts=[],
    ))
    db_session.add(Invoice(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/inr.pdf",
        vendor_name="ACME", grand_total=40000.0, currency="INR", status="PAID", sa_alerts=[],
    ))
    db_session.commit()

    from routers.dashboard import DashboardInsightsSchema

    captured_prompt = {}

    class MockStructuredLLM:
        def invoke(self, prompt):
            captured_prompt["text"] = prompt
            return DashboardInsightsSchema(insights=[])

    class MockLLM:
        def with_structured_output(self, schema):
            return MockStructuredLLM()

    with patch("routers.dashboard.get_llm") as mock_get_llm:
        mock_get_llm.return_value = MockLLM()
        assert client.get("/api/v1/dashboard/insights").status_code == 200

    text = captured_prompt["text"]
    assert '"currency": "USD"' in text
    assert '"currency": "INR"' in text
    assert "500.0" in text
    assert "40000.0" in text
    # The blended total the old code produced.
    assert "40500" not in text


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

    # 2. Create another resolved invoice with 2 error-level alerts, 1 dismissed, 1 not dismissed.
    # Gap 123: only error-severity alerts count for the AI Alert Response metric.
    # Dismissed = False alarm (1), Not dismissed = Correct alert (1).
    # Alert accuracy = 1 / 2 = 50.0%
    inv2_id = uuid4()
    inv2 = Invoice(
        id=inv2_id,
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/invoice2.pdf",
        status="AUDIT_REQUIRED",
        sa_alerts=[
            {"type": "tax_mismatch", "message": "Math mismatch"},
            {"type": "missing_required_field", "message": "Invalid vendor"}
        ]
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

