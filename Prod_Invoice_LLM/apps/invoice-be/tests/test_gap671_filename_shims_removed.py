"""Regression tests for BE Gap 671:
Filename-keyword test shims ('fail' in handlers.py and 'audit' in extraction_agent.py)
removed from production paths.
"""
from uuid import uuid4
from unittest.mock import patch
import pytest
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool

from models import Invoice
from queue_worker.handlers import handle_process_invoice
import agents.extraction_agent as ea


# Setup isolated in-memory test database session for worker test
sqlite_url = "sqlite:///:memory:"
test_engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)


def test_direction_profiles_have_no_legacy_audit_path_shim():
    """Verify legacy_audit_path_shim is completely removed from _DirectionProfile
    and all registered profiles."""
    assert not hasattr(ea._DirectionProfile, "legacy_audit_path_shim")
    for name, profile in ea._DIRECTION_PROFILES.items():
        assert not hasattr(profile, "legacy_audit_path_shim"), f"Profile {name} still has legacy_audit_path_shim"


def test_inbound_invoice_with_audit_in_path_runs_real_verification():
    """Verify that an inbound invoice whose file_path contains 'audit'
    runs real verification math instead of short-circuiting to AUDIT_REQUIRED
    with a fake 'Math mismatch' alert."""
    state = {
        "file_path": "uploads/client_audit_services_2026.pdf",
        "flow_direction": "INBOUND",
        "doc_type": "INVOICE",
        "ocr_text": "Audit Consulting: 100.00 qty 1 price 100.00\nSubtotal: 100.00\nTax: 10.00\nTotal: 110.00",
        "images": [],
        "extracted_data": {
            "invoice_number": "INV-2026-AUDIT",
            "invoice_date": "2026-09-17",
            "subtotal": 100.0,
            "tax_amount": 10.0,
            "grand_total": 110.0,
            "items": [
                {"description": "Audit Consulting", "amount": 100.0, "quantity": 1.0, "unit_price": 100.0}
            ]
        },
        "alerts": [],
        "status": "PROCESSING",
        "rules": None,
        "complexity": "STANDARD",
        "ocr_result": None,
        "retry_count": 0,
    }

    result = ea.verify_node(state)

    # Arithmetic is completely sound: 100 subtotal + 10 tax = 110 grand total.
    # Previously, this would have returned: {"alerts": ["Math mismatch"], "status": "AUDIT_REQUIRED"}
    assert result["status"] == "COMPLETED"
    assert result["alerts"] == []


def test_queue_worker_does_not_crash_on_fail_in_filename():
    """Verify that a filename containing 'fail' (e.g. failover_invoice.pdf)
    no longer crashes the worker with a mock exception."""
    SQLModel.metadata.create_all(test_engine)
    tenant_id = uuid4()
    invoice_id = uuid4()
    batch_id = uuid4()
    file_path = "storage/failover_cluster_invoice.pdf"

    with Session(test_engine) as session:
        invoice = Invoice(
            id=invoice_id,
            tenant_id=tenant_id,
            file_path=file_path,
            status="PROCESSING"
        )
        session.add(invoice)
        session.commit()

    with patch("queue_worker.handlers.engine", test_engine), \
         patch("queue_worker.handlers._run_ocr") as mock_ocr, \
         patch("queue_worker.handlers._publish_sse_events"), \
         patch("queue_worker.handlers.run_extraction_agent") as mock_agent:
        
        mock_ocr.return_value = "Sample OCR Content"
        mock_agent.return_value = {
            "status": "COMPLETED",
            "alerts": [],
            "extracted_data": {
                "vendor_name": "Failover Systems Inc",
                "invoice_number": "FS-1001",
                "subtotal": 500.0,
                "tax_amount": 50.0,
                "grand_total": 550.0,
                "items": []
            }
        }

        # This should execute to completion without throwing 'Mock processing failure'
        handle_process_invoice(str(batch_id), file_path, str(tenant_id))

    with Session(test_engine) as session:
        updated_invoice = session.get(Invoice, invoice_id)
        assert updated_invoice.status == "COMPLETED"
        assert updated_invoice.vendor_name == "Failover Systems Inc"

    SQLModel.metadata.drop_all(test_engine)
