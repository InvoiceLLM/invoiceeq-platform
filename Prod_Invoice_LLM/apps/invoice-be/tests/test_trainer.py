import pytest
from unittest.mock import patch, MagicMock
import json
import os
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, create_engine, Session, select
from sqlalchemy.pool import StaticPool

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import ExtractionTemplate, Invoice
from workers.tasks import process_invoice_task
from agents.extraction_agent import InvoiceExtractionSchema, InvoiceLineItem
from agents.trainer_agent import ConstraintList

# Setup isolated in-memory test database session
sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)

@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)

@pytest.fixture(autouse=True)
def override_db_session(db_session):
    def get_db_session_override():
        yield db_session
    app.dependency_overrides[get_db_session] = get_db_session_override
    with patch("workers.tasks.engine", engine):
        yield
    app.dependency_overrides.clear()

@pytest.fixture(autouse=True)
def mock_default_templates_path(tmp_path):
    temp_json_path = tmp_path / "default_templates.json"
    temp_json_path.write_text(json.dumps({
        "ACME Corporation": {
            "constraints": [
                "Ensure vendor name is always ACME Corporation",
                "Field invoice_number is always prefixed with INV-"
            ]
        }
    }))
    with patch("routers.trainer.DEFAULT_TEMPLATES_PATH", str(temp_json_path)):
        yield temp_json_path


class MockStructuredLLM:
    def __init__(self, schema):
        self.schema = schema
        
    def invoke(self, messages_or_prompt):
        if self.schema == ConstraintList:
            return ConstraintList(constraints=["The invoice date is 2026-06-25, not 2026-05-25"])
        
        return InvoiceExtractionSchema(
            vendor_name="ACME Corporation",
            invoice_number="INV-12345",
            invoice_date="2026-06-25",
            due_date="2026-07-25",
            subtotal=100.0,
            tax_amount=10.0,
            grand_total=110.0,
            items=[InvoiceLineItem(description="Item A", quantity=1.0, unit_price=100.0, amount=100.0)],
            tags=["mock"]
        )

class MockLLM:
    def with_structured_output(self, schema):
        return MockStructuredLLM(schema)

client = TestClient(app)

@patch("agents.extraction_agent.get_llm")
@patch("agents.trainer_agent.get_llm")
@patch("workers.tasks._run_ocr")
@patch("routers.trainer._run_ocr")
def test_trainer_flow(mock_trainer_ocr, mock_tasks_ocr, mock_trainer_llm, mock_extraction_llm, db_session):
    mock_trainer_ocr.return_value = "Mock OCR Text"
    mock_tasks_ocr.return_value = "Mock OCR Text"
    mock_trainer_llm.return_value = MockLLM()
    mock_extraction_llm.return_value = MockLLM()

    # 1. Test upload
    pdf_content = b"%PDF-1.4 Mock PDF Content"
    response = client.post(
        "/api/v1/trainer/upload",
        files={"file": ("test_invoice.pdf", pdf_content, "application/pdf")}
    )
    assert response.status_code == 201
    data = response.json()
    assert "session_id" in data
    assert data["extracted_data"]["vendor_name"] == "ACME Corporation"
    session_id = data["session_id"]

    # Verify no persistent invoice was created
    invoices = db_session.exec(select(Invoice)).all()
    assert len(invoices) == 0

    # 2. Test chat correction
    chat_response = client.post(
        f"/api/v1/trainer/sessions/{session_id}/chat",
        json={"content": "Change date to 2026-06-25"}
    )
    assert chat_response.status_code == 200
    chat_data = chat_response.json()
    assert "constraints" in chat_data
    assert len(chat_data["constraints"]) > 0
    assert "2026-06-25" in chat_data["constraints"][0]

    # 3. Test commit global mode
    commit_response = client.post(
        f"/api/v1/trainer/sessions/{session_id}/commit",
        json={"global_mode": True}
    )
    assert commit_response.status_code == 200
    
    # 4. Try loading session again (should be deleted after commit)
    chat_response_deleted = client.post(
        f"/api/v1/trainer/sessions/{session_id}/chat",
        json={"content": "Another message"}
    )
    assert chat_response_deleted.status_code == 404

@patch("agents.extraction_agent.get_llm")
@patch("agents.trainer_agent.get_llm")
@patch("workers.tasks._run_ocr")
@patch("routers.trainer._run_ocr")
def test_trainer_commit_db(mock_trainer_ocr, mock_tasks_ocr, mock_trainer_llm, mock_extraction_llm, db_session):
    mock_trainer_ocr.return_value = "Mock OCR Text"
    mock_tasks_ocr.return_value = "Mock OCR Text"
    mock_trainer_llm.return_value = MockLLM()
    mock_extraction_llm.return_value = MockLLM()

    # Upload
    response = client.post(
        "/api/v1/trainer/upload",
        files={"file": ("test_invoice.pdf", b"pdf content", "application/pdf")}
    )
    session_id = response.json()["session_id"]

    # Chat correction
    client.post(
        f"/api/v1/trainer/sessions/{session_id}/chat",
        json={"content": "Custom template rule"}
    )

    # Commit DB
    commit_response = client.post(
        f"/api/v1/trainer/sessions/{session_id}/commit",
        json={"global_mode": False}
    )
    assert commit_response.status_code == 200

    # Query extraction_templates table
    stmt = select(ExtractionTemplate).where(ExtractionTemplate.tenant_id == MOCK_TENANT_ID)
    templates = db_session.exec(stmt).all()
    assert len(templates) == 1
    assert templates[0].vendor_name == "ACME Corporation"
    assert "constraints" in templates[0].rules
    assert len(templates[0].rules["constraints"]) > 0

@patch("agents.extraction_agent.get_llm")
@patch("workers.tasks._run_ocr")
@patch("workers.tasks._publish_sse_events")
def test_ingestion_pipeline_with_fallback(mock_sse, mock_ocr, mock_llm, db_session):
    mock_ocr.return_value = "Mock OCR Text"
    mock_llm.return_value = MockLLM()

    # Pre-populate database with Invoice processing record
    invoice_id = uuid4()
    file_path = "mock/path/fallback_test.pdf"
    invoice = Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path=file_path,
        status="PROCESSING"
    )
    db_session.add(invoice)
    db_session.commit()

    # Execute celery task
    with patch("workers.tasks.run_extraction_agent") as mock_extract_agent:
        # Mock first and second pass return values
        mock_extract_agent.side_effect = [
            # first pass
            {
                "status": "COMPLETED",
                "alerts": [],
                "extracted_data": {
                    "vendor_name": "ACME Corporation",
                    "grand_total": 110.0
                }
            },
            # second pass (after fallback match)
            {
                "status": "COMPLETED",
                "alerts": [],
                "extracted_data": {
                    "vendor_name": "ACME Corporation",
                    "grand_total": 110.0,
                    "invoice_number": "INV-12345"
                }
            }
        ]

        process_invoice_task("mock-batch-id", file_path, str(MOCK_TENANT_ID))

        # Assert extraction agent was called twice (first pass, then second pass with rules)
        assert mock_extract_agent.call_count == 2
        first_call_args = mock_extract_agent.call_args_list[0]
        second_call_args = mock_extract_agent.call_args_list[1]
        
        # Verify first call had no rules
        assert first_call_args[1].get("rules") is None
        # Verify second call had rules from fallback
        rules = second_call_args[1].get("rules")
        assert rules is not None
        assert "Ensure vendor name is always ACME Corporation" in rules["constraints"]
