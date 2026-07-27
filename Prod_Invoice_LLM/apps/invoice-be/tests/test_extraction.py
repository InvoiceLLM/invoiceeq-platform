import pytest
from unittest.mock import patch
from uuid import uuid4
from datetime import date
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool

from main import app
from dependencies import get_db_session, MOCK_TENANT_ID
from models import Invoice
from queue_worker.handlers import handle_process_invoice

# Setup isolated in-memory test database session
sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)

@pytest.fixture(name="db_session")
def db_session_fixture():
    """Yields clean isolated test database session."""
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)

@pytest.fixture(autouse=True)
def override_db_session(db_session):
    """Overrides dependencies database session and worker database engine."""
    def get_db_session_override():
        yield db_session
    app.dependency_overrides[get_db_session] = get_db_session_override
    with patch("queue_worker.handlers.engine", engine):
        yield
    app.dependency_overrides.clear()

def test_verify_line_items_and_totals_math():
    """Verify that calculation check tools flag errors correctly."""
    from utils.verification_tools import verify_line_items_math, verify_totals_math
    
    # 1. Test line items mismatch
    items = [
        {"description": "Item 1", "amount": 10.0},
        {"description": "Item 2", "amount": 15.5}
    ]
    subtotal = 30.0  # Should be 25.5
    alert = verify_line_items_math(items, subtotal)
    assert alert is not None
    assert alert["type"] == "line_items_mismatch"
    assert "subtotal" in alert["field"]
    
    # 2. Test totals mismatch
    subtotal = 25.5
    tax = 2.5
    grand_total = 50.0  # Should be 28.0
    alert = verify_totals_math(subtotal, tax, grand_total)
    assert alert is not None
    assert alert["type"] == "tax_mismatch"
    assert "tax_amount" in alert["field"]

def test_token_guardrails_limit_exceeded(db_session):
    """Verify that exceeding token limits triggers pre-flight block and AUDIT_REQUIRED status."""
    # Pre-populate database with processing record
    invoice_id = uuid4()
    file_path = "mock/path/too_large.pdf"
    invoice = Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path=file_path,
        status="PROCESSING"
    )
    db_session.add(invoice)
    db_session.commit()
    
    # Mock check_token_guardrails to return False (limit exceeded)
    with patch("agents.extraction_agent.check_token_guardrails") as mock_check, \
         patch("queue_worker.handlers._run_ocr") as mock_ocr, \
         patch("queue_worker.handlers._publish_sse_events"):
        
        mock_check.return_value = (False, 150000, 128000) # (is_safe, input_tokens, limit)
        mock_ocr.return_value = "Extracted OCR text payload"
        
        # Invoke celery task sync for testing
        handle_process_invoice("mock-batch-id", file_path, str(MOCK_TENANT_ID))
        
        # Verify database record updated to AUDIT_REQUIRED and contains token_limit_exceeded alert
        db_session.refresh(invoice)
        assert invoice.status == "AUDIT_REQUIRED"
        assert len(invoice.sa_alerts) == 1
        assert invoice.sa_alerts[0]["type"] == "token_limit_exceeded"
        assert "context limit" in invoice.sa_alerts[0]["message"]

def test_successful_extraction_pipeline(db_session):
    """Verify standard extraction runs successfully, updating database columns and dates."""
    invoice_id = uuid4()
    file_path = "mock/path/clean.pdf"
    invoice = Invoice(
        id=invoice_id,
        tenant_id=MOCK_TENANT_ID,
        file_path=file_path,
        status="PROCESSING"
    )
    db_session.add(invoice)
    db_session.commit()
    
    with patch("agents.extraction_agent.check_token_guardrails") as mock_check, \
         patch("agents.extraction_agent.get_llm") as mock_get_llm, \
         patch("queue_worker.handlers._run_ocr") as mock_ocr, \
         patch("queue_worker.handlers._publish_sse_events"):
         
        mock_check.return_value = (True, 100, 128000)
        # Gap 46/56's verify_tax_amount_in_source_text() (and the sibling faithfulness
        # checks) now cross-check every extracted number against the raw OCR text, so
        # the mock OCR text must actually contain every number the schema below
        # extracts, verbatim, not just be a placeholder string.
        mock_ocr.return_value = (
            "INVOICE\nVendor: ACME Corp\nInvoice #: INV-2026\n"
            "Line 1   1   100.00   100.00\n"
            "Subtotal: 100.00\nTax: 10.00\nTotal: 110.00"
        )
        
        # Mock structured output schema model instance returned by LLM
        from agents.extraction_agent import InvoiceExtractionSchema, InvoiceLineItem
        mock_schema = InvoiceExtractionSchema(
            vendor_name="ACME Corp",
            invoice_number="INV-2026",
            invoice_date="2026-06-30",
            due_date="2026-07-31",
            subtotal=100.00,
            tax_amount=10.00,
            grand_total=110.00,
            po_number="PO-777",
            items=[InvoiceLineItem(description="Line 1", quantity=1.0, unit_price=100.00, amount=100.00)],
            tags=["it", "hardware"]
        )
        
        # Mock llm.with_structured_output().invoke()
        class MockStructuredLLM:
            def invoke(self, prompt):
                return mock_schema
                
        class MockLLM:
            def with_structured_output(self, schema):
                return MockStructuredLLM()
                
        mock_get_llm.return_value = MockLLM()
        
        # Execute Celery task
        handle_process_invoice("mock-batch-id", file_path, str(MOCK_TENANT_ID))
        
        # Assert database updates
        db_session.refresh(invoice)
        assert invoice.status == "COMPLETED"
        assert invoice.vendor_name == "ACME Corp"
        assert invoice.invoice_number == "INV-2026"
        assert invoice.invoice_date == date(2026, 6, 30)
        assert invoice.due_date == date(2026, 7, 31)
        assert invoice.grand_total == 110.00
        assert invoice.tax_amount == 10.00
        assert invoice.po_number == "PO-777"
        assert invoice.tags == ["it", "hardware"]
        assert len(invoice.items) == 1
        assert invoice.sa_alerts == []


def test_gap_46_tax_amount_source_text_verification():
    """Gap 46: Verify that tax_amount OCR source-text check catches silent auto-corrections."""
    from utils.verification_tools import verify_tax_amount_in_source_text

    # 1. Tax amount is printed on OCR text -> passes (returns None)
    ocr_text_with_tax = "Subtotal: $100.00  Tax: $15.00  Total: $115.00"
    alert = verify_tax_amount_in_source_text(15.00, ocr_text_with_tax)
    assert alert is None

    # 2. Zero tax amount -> passes (returns None)
    alert_zero = verify_tax_amount_in_source_text(0.00, "Subtotal: $100.00 Total: $100.00")
    assert alert_zero is None

    # 3. LLM auto-corrected tax_amount (10.00) not present in raw OCR text -> triggers alert
    ocr_text_flawed = "Subtotal: $100.00  Tax: $25.00  Total: $125.00"  # Vendor printed tax is 25.00, not 10.00
    alert_flawed = verify_tax_amount_in_source_text(10.00, ocr_text_flawed)
    assert alert_flawed is not None
    assert alert_flawed["type"] == "tax_amount_not_verified_in_source"
    assert "tax_amount" in alert_flawed["field"]

