"""Tests for the redesigned AI Trainer (Feature 10).

Covers the scope-based sessions (global / existing_vendor / new_vendor), the FE-shaped
session responses, commit + rule versioning + rollback, the vendors endpoint, and the
two-stage (Global + vendor) rule resolution in the ingestion pipeline.

The heavy pieces (OCR, the extraction agent, the trainer agent) are mocked at the router
and worker boundaries so these run fast and deterministically without an LLM or PDFs.
"""
import pytest
from unittest.mock import patch
from uuid import uuid4, UUID

from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import ExtractionTemplate, ExtractionTemplateVersion, Invoice
from services import trainer_sessions

# Isolated in-memory SQLite shared across the connection pool.
engine = create_engine(
    "sqlite:///:memory:",
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
def reset_trainer_sessions():
    # Force the in-process session store (no Redis in the test env) and keep tests isolated.
    trainer_sessions._redis_client = False
    trainer_sessions._memory_store.clear()
    yield
    trainer_sessions._memory_store.clear()
@pytest.fixture(autouse=True)
def mock_queue_client():
    with patch("routers.trainer.QueueClient") as mock_qc:
        yield mock_qc



@pytest.fixture
def trainer_mocks():
    """Mock OCR + both agents at the router boundary with sensible defaults."""
    with patch("routers.trainer._run_ocr", return_value="Mock OCR Text") as m_ocr, \
         patch("routers.trainer.run_extraction_agent") as m_extract, \
         patch("routers.trainer.run_trainer_agent") as m_trainer:
        m_extract.return_value = {
            "extracted_data": {"vendor_name": "ACME Corporation", "invoice_number": "INV-1", "grand_total": 110.0},
            "status": "COMPLETED",
            "alerts": [],
        }
        m_trainer.return_value = {
            "constraints": ["Parse dates as DD/MM/YYYY"],
            "extracted_data": {"vendor_name": "ACME Corporation", "invoice_number": "INV-1", "grand_total": 110.0},
            "status": "COMPLETED",
            "alerts": [],
        }
        yield {"ocr": m_ocr, "extract": m_extract, "trainer": m_trainer}


# ── Session entry points ─────────────────────────────────────────────────────

def test_new_vendor_upload_returns_session_shape(trainer_mocks, db_session):
    resp = client.post(
        "/api/v1/trainer/upload",
        files={"file": ("inv.pdf", b"%PDF-1.4 mock", "application/pdf")},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["scope"] == "new_vendor"
    assert data["sessionId"]
    assert data["vendorName"] == "ACME Corporation"
    assert isinstance(data["variables"], list)
    assert any(v["key"] == "invoice_number" for v in data["variables"])
    assert len(data["chatHistory"]) >= 1  # welcome message
    # Trainer sessions must not persist a real invoice.
    assert db_session.exec(select(Invoice)).all() == []


def test_global_session_and_chat(trainer_mocks):
    start = client.post("/api/v1/trainer/sessions/global", files={"placeholder": (None, "1")})
    assert start.status_code == 201
    started = start.json()
    assert started["scope"] == "global"
    assert started["variables"] == []  # chat-only, no grounding PDF
    sid = started["sessionId"]

    chat = client.post(f"/api/v1/trainer/sessions/{sid}/chat", json={"content": "Dates are DD/MM/YYYY"})
    assert chat.status_code == 200
    body = chat.json()
    assert body["newRuleCreated"] == "Parse dates as DD/MM/YYYY"
    assert "Parse dates as DD/MM/YYYY" in body["updatedSession"]["activeRules"]
    assert len(body["updatedSession"]["chatHistory"]) >= 3  # welcome + user + assistant


def test_from_production_session(trainer_mocks, db_session):
    inv = Invoice(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="blob/acme.pdf", status="COMPLETED",
        vendor_name="ACME Corporation", invoice_number="INV-9", grand_total=110.0, field_confidence={},
    )
    db_session.add(inv)
    db_session.commit()

    resp = client.post("/api/v1/trainer/sessions/from-production", params={"vendor_name": "ACME Corporation"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["scope"] == "existing_vendor"
    assert data["vendorName"] == "ACME Corporation"
    assert data["pdfUrl"] == f"/api/invoices/{inv.id}/pdf"
    assert any(v["key"] == "invoice_number" and v["value"] == "INV-9" for v in data["variables"])


def test_from_production_unknown_vendor_404(trainer_mocks):
    resp = client.post("/api/v1/trainer/sessions/from-production", params={"vendor_name": "Nope Inc"})
    assert resp.status_code == 404


def test_vendors_endpoint(db_session):
    db_session.add(Invoice(id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="a/x1.pdf", status="COMPLETED", vendor_name="Acme"))
    db_session.add(Invoice(id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="a/x2.pdf", status="PAID", vendor_name="Acme"))
    db_session.add(Invoice(id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="a/y1.pdf", status="COMPLETED", vendor_name="Beta"))
    db_session.commit()

    resp = client.get("/api/v1/trainer/vendors")
    assert resp.status_code == 200
    by_name = {v["name"]: v for v in resp.json()}
    assert by_name["Acme"]["invoiceCount"] == 2
    assert by_name["Beta"]["invoiceCount"] == 1
    assert by_name["Acme"]["samplePdfUrl"].startswith("/api/invoices/")


# ── Commit → scope-based template rows ───────────────────────────────────────

def test_commit_global_creates_null_vendor_template(trainer_mocks, db_session):
    sid = client.post("/api/v1/trainer/sessions/global", files={"placeholder": (None, "1")}).json()["sessionId"]
    client.post(f"/api/v1/trainer/sessions/{sid}/chat", json={"content": "VAT after discount"})

    commit = client.post(f"/api/v1/trainer/sessions/{sid}/commit")
    assert commit.status_code == 200
    body = commit.json()
    assert body["scope"] == "global"
    assert body["vendor_name"] is None
    assert body["version"] == 1

    templates = db_session.exec(select(ExtractionTemplate).where(ExtractionTemplate.tenant_id == MOCK_TENANT_ID)).all()
    assert len(templates) == 1
    assert templates[0].vendor_name is None  # the Global row
    assert "constraints" in templates[0].rules

    versions = db_session.exec(select(ExtractionTemplateVersion)).all()
    assert len(versions) == 1 and versions[0].version == 1

    # Session is consumed on commit.
    assert client.post(f"/api/v1/trainer/sessions/{sid}/chat", json={"content": "x"}).status_code == 404


def test_commit_new_vendor_creates_vendor_template(trainer_mocks, db_session):
    sid = client.post("/api/v1/trainer/upload", files={"file": ("i.pdf", b"%PDF mock", "application/pdf")}).json()["sessionId"]
    client.post(f"/api/v1/trainer/sessions/{sid}/chat", json={"content": "rule"})

    commit = client.post(f"/api/v1/trainer/sessions/{sid}/commit")
    assert commit.status_code == 200
    assert commit.json()["vendor_name"] == "ACME Corporation"

    templates = db_session.exec(
        select(ExtractionTemplate).where(ExtractionTemplate.vendor_name == "ACME Corporation")
    ).all()
    assert len(templates) == 1


# ── Versioning + history + rollback (Task 10.10) ─────────────────────────────

def test_versioning_history_and_rollback(trainer_mocks, db_session):
    # Commit v1 (rules = R1) for the vendor.
    trainer_mocks["trainer"].return_value = {
        "constraints": ["R1"], "extracted_data": {"vendor_name": "ACME Corporation"},
        "status": "COMPLETED", "alerts": [],
    }
    sid1 = client.post("/api/v1/trainer/upload", files={"file": ("i.pdf", b"x", "application/pdf")}).json()["sessionId"]
    client.post(f"/api/v1/trainer/sessions/{sid1}/chat", json={"content": "r1"})
    assert client.post(f"/api/v1/trainer/sessions/{sid1}/commit").json()["version"] == 1

    # Commit v2 (rules = R1, R2) for the same vendor.
    trainer_mocks["trainer"].return_value = {
        "constraints": ["R1", "R2"], "extracted_data": {"vendor_name": "ACME Corporation"},
        "status": "COMPLETED", "alerts": [],
    }
    sid2 = client.post("/api/v1/trainer/upload", files={"file": ("i.pdf", b"x", "application/pdf")}).json()["sessionId"]
    client.post(f"/api/v1/trainer/sessions/{sid2}/chat", json={"content": "r2"})
    assert client.post(f"/api/v1/trainer/sessions/{sid2}/commit").json()["version"] == 2

    # History reflects both versions, newest first, with the current one flagged.
    hist = client.get(
        "/api/v1/trainer/templates/history",
        params={"scope": "existing_vendor", "vendor_name": "ACME Corporation"},
    )
    assert hist.status_code == 200
    versions = hist.json()
    assert [v["version"] for v in versions] == [2, 1]
    current = next(v for v in versions if v["isCurrent"])
    assert current["version"] == 2 and current["rules"] == ["R1", "R2"]
    template_id = versions[0]["templateId"]

    # Roll back to v1 -> writes a new current version (v3) with v1's rules.
    rb = client.post(f"/api/v1/trainer/templates/{template_id}/rollback/1")
    assert rb.status_code == 200
    assert rb.json()["version"] == 3

    tpl = db_session.get(ExtractionTemplate, UUID(template_id))
    db_session.refresh(tpl)
    assert tpl.rules["constraints"] == ["R1"]


# ── Two-stage rule resolution in the pipeline (Task 10.8) ────────────────────

def test_two_stage_rule_resolution(db_session):
    from queue_worker import handlers

    db_session.add(ExtractionTemplate(id=uuid4(), tenant_id=MOCK_TENANT_ID, vendor_name=None, rules={"constraints": ["G1"]}, version=1))
    db_session.add(ExtractionTemplate(id=uuid4(), tenant_id=MOCK_TENANT_ID, vendor_name="ACME Corporation", rules={"constraints": ["V1"]}, version=1))
    db_session.add(Invoice(id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path="mock/acme.pdf", status="PROCESSING"))
    db_session.commit()

    with patch("queue_worker.handlers.engine", engine), \
         patch("queue_worker.handlers._run_ocr", return_value="Mock OCR Text"), \
         patch("queue_worker.handlers._publish_sse_events"), \
         patch("queue_worker.handlers.run_extraction_agent") as m_extract:
        m_extract.side_effect = [
            {"status": "AUDIT_REQUIRED", "alerts": [], "extracted_data": {"vendor_name": "ACME Corporation", "grand_total": 110.0}},
            {"status": "AUDIT_REQUIRED", "alerts": [], "extracted_data": {"vendor_name": "ACME Corporation", "grand_total": 110.0, "invoice_number": "INV-1"}},
        ]
        handlers.handle_process_invoice("batch-1", "mock/acme.pdf", str(MOCK_TENANT_ID))

        assert m_extract.call_count == 2
        # Stage 1 applies the Global template; Stage 2 applies the merged Global + vendor rules.
        assert m_extract.call_args_list[0].kwargs.get("rules") == {"constraints": ["G1"]}
        assert m_extract.call_args_list[1].kwargs.get("rules") == {"constraints": ["G1", "V1"]}


# ── Trainer agent scope prompt (Task 10.5) ───────────────────────────────────

def test_build_system_prompt_is_scope_aware():
    from agents.trainer_agent import _build_system_prompt

    global_prompt = _build_system_prompt("global", [])
    assert "GLOBAL" in global_prompt

    vendor_prompt = _build_system_prompt("existing_vendor", ["Global rule X"])
    assert "read-only context" in vendor_prompt.lower()
    assert "Global rule X" in vendor_prompt
