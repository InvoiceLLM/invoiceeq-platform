"""BE Gap 671: Filename-keyword test shims removed from production code.

Verifies:
1. Filenames containing "fail" (e.g. failover_invoice.pdf) do not crash handle_process_invoice with mock failure.
2. Filenames containing "audit" (e.g. annual_audit_report.pdf) do not force AUDIT_REQUIRED with a fake "Math mismatch" alert in verify_node.
3. _DirectionProfile and its instances no longer carry legacy_audit_path_shim.
"""
from unittest.mock import patch
from uuid import uuid4

from sqlmodel import Session, select

from dependencies import MOCK_TENANT_ID
from models import Invoice
from tests.pg_gap_fixtures import pg_engine, pg_only  # noqa: F401  (pytest fixture)
from agents.extraction_agent import _DIRECTION_PROFILES, verify_node


def test_direction_profiles_have_no_legacy_audit_path_shim():
    for name, profile in _DIRECTION_PROFILES.items():
        assert not hasattr(profile, "legacy_audit_path_shim"), (
            f"Profile {name} should not have legacy_audit_path_shim"
        )


def test_verify_node_does_not_shim_audit_filename():
    """A clean invoice with 'audit' in file_path should pass verification without fake Math mismatch."""
    state = {
        "file_path": "tenants/00000000-0000-0000-0000-000000000000/invoices/annual_audit_report.pdf",
        "flow_direction": "INBOUND",
        "doc_type": "INVOICE",
        "alerts": [],
        "extracted_data": {
            "vendor_name": "Audit Services Ltd",
            "invoice_number": "AUD-101",
            "invoice_date": "2026-09-15",
            "subtotal": 100.0,
            "tax_amount": 10.0,
            "grand_total": 110.0,
            "items": [
                {"description": "Audit service", "quantity": 1.0, "unit_price": 100.0, "amount": 100.0}
            ],
        },
    }
    result = verify_node(state)
    # Without the shim, the correct math (100 + 10 = 110) passes cleanly as COMPLETED with 0 alerts
    assert result.get("status") == "COMPLETED"
    assert "Math mismatch" not in result.get("alerts", [])


@pg_only
def test_handler_does_not_crash_on_fail_keyword(pg_engine):
    """A filename containing 'fail' (e.g. failover_systems_invoice.pdf) must not crash the worker."""
    from queue_worker.handlers import handle_process_invoice

    file_path = f"tenants/{MOCK_TENANT_ID}/invoices/failover_systems_{uuid4()}.pdf"
    with Session(pg_engine) as s:
        s.add(Invoice(id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path=file_path, status="PROCESSING"))
        s.commit()

    agent_result = {
        "status": "COMPLETED",
        "alerts": [],
        "extracted_data": {
            "vendor_name": "Failover Systems Inc",
            "invoice_number": "FS-1",
            "invoice_date": "2026-09-15",
            "grand_total": 500.0,
        },
    }

    with patch("queue_worker.handlers.engine", pg_engine), \
         patch("queue_worker.handlers._run_ocr", return_value="ocr text"), \
         patch("queue_worker.handlers._publish_sse_events"), \
         patch("queue_worker.handlers.run_extraction_agent", return_value=agent_result), \
         patch("queue_worker.handlers.track_extraction_pipeline_turn"), \
         patch("chroma_client.index_invoice_document"):
        # This must execute without raising "Mock processing failure triggered by file name keyword"
        res = handle_process_invoice(str(uuid4()), file_path, str(MOCK_TENANT_ID))

    assert res["status"] == "COMPLETED"
    assert res["vendor_name"] == "Failover Systems Inc"

    with Session(pg_engine) as s:
        row = s.exec(select(Invoice).where(Invoice.file_path == file_path)).one()
        assert row.status == "COMPLETED"
