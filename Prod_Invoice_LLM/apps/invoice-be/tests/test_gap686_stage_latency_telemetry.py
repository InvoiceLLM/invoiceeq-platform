"""
Unit tests for BE Gap 686 (Stage latency telemetry for handle_process_invoice)
and BE Gap 678 (Postgres session closed before Chroma RAG indexing).

Pure mock unit tests — DB-free, network-free.
"""
from unittest.mock import patch, MagicMock, ANY
import pytest
from uuid import uuid4


def test_gap686_stage_latency_telemetry_success():
    """Verify handle_process_invoice records OCR, LLM, DB and Chroma latencies

    and emits extraction_pipeline_turn telemetry on success.
    """
    batch_id = "test-batch-686-01"
    file_path = "tenants/t1/invoices/test.pdf"
    tenant_id = str(uuid4())

    mock_invoice = MagicMock()
    mock_invoice.id = uuid4()
    mock_invoice.tenant_id = tenant_id
    mock_invoice.file_path = file_path
    mock_invoice.status = "PROCESSING"
    mock_invoice.vendor_name = "Acme Corp"
    mock_invoice.tags = []

    mock_session = MagicMock()
    def _mock_exec(stmt):
        res = MagicMock()
        stmt_str = str(stmt).lower()
        if "where invoice.file_path" in stmt_str:
            res.first.return_value = mock_invoice
        else:
            res.first.return_value = None
        res.all.return_value = []
        return res
    mock_session.exec.side_effect = _mock_exec

    with patch("queue_worker.handlers.Session") as mock_session_cls, \
         patch("queue_worker.handlers._run_ocr") as mock_ocr, \
         patch("queue_worker.handlers.run_extraction_agent") as mock_agent, \
         patch("queue_worker.handlers.find_near_duplicate", return_value=None), \
         patch("queue_worker.handlers._publish_sse_events"), \
         patch("chroma_client.index_invoice_document") as mock_chroma, \
         patch("chroma_client.should_index_status", return_value=True), \
         patch("queue_worker.handlers.track_extraction_pipeline_turn") as mock_track:

        mock_session_cls.return_value.__enter__.return_value = mock_session
        mock_ocr.return_value = {
            "content": "Invoice #123 Acme Corp",
            "coordinates": [],
            "field_confidence": {},
            "source_document_json": {},
        }
        mock_agent.return_value = {
            "status": "COMPLETED",
            "alerts": [],
            "extracted_data": {
                "vendor_name": "Acme Corp",
                "invoice_number": "INV-123",
                "grand_total": 500.0,
            },
            "doc_type": "TAX_INVOICE",
            "doc_type_evidence": "Printed 'Tax Invoice'",
            "doc_attributes": {},
            "doc_type_confidence": 0.98,
        }

        from queue_worker.handlers import handle_process_invoice
        result = handle_process_invoice(batch_id, file_path, tenant_id)

        assert result["status"] == "COMPLETED"
        assert result["vendor_name"] == "Acme Corp"
        assert mock_track.called

        _, kwargs = mock_track.call_args
        assert kwargs["batch_id"] == batch_id
        assert kwargs["tenant_id"] == tenant_id
        assert kwargs["status"] == "COMPLETED"
        assert "ocr_latency_ms" in kwargs
        assert "llm_latency_ms" in kwargs
        assert "db_persist_latency_ms" in kwargs
        assert "chroma_latency_ms" in kwargs
        assert "total_duration_ms" in kwargs
        assert kwargs["ocr_latency_ms"] >= 0.0
        assert kwargs["llm_latency_ms"] >= 0.0
        assert kwargs["db_persist_latency_ms"] >= 0.0
        assert kwargs["chroma_latency_ms"] >= 0.0
        assert kwargs["total_duration_ms"] >= 0.0
        assert kwargs["doc_type"] == "TAX_INVOICE"
        assert kwargs["alerts_count"] == 0


def test_gap686_stage_latency_telemetry_on_failure():
    """Verify handle_process_invoice emits extraction_pipeline_turn with FAILED status

    and error details when processing fails.
    """
    batch_id = "test-batch-686-fail"
    file_path = "tenants/t1/invoices/corrupt.pdf"
    tenant_id = str(uuid4())

    mock_invoice = MagicMock()
    mock_invoice.id = uuid4()
    mock_invoice.status = "PROCESSING"

    mock_session = MagicMock()
    mock_session.exec.return_value.first.return_value = mock_invoice

    with patch("queue_worker.handlers.Session") as mock_session_cls, \
         patch("queue_worker.handlers._run_ocr", side_effect=ValueError("Corrupt PDF")), \
         patch("queue_worker.handlers._publish_sse_events"), \
         patch("queue_worker.handlers._persist_processing_failure"), \
         patch("queue_worker.handlers.track_extraction_pipeline_turn") as mock_track:

        mock_session_cls.return_value.__enter__.return_value = mock_session

        from queue_worker.handlers import handle_process_invoice
        with pytest.raises(ValueError, match="Corrupt PDF"):
            handle_process_invoice(batch_id, file_path, tenant_id)

        assert mock_track.called
        _, kwargs = mock_track.call_args
        assert kwargs["batch_id"] == batch_id
        assert kwargs["status"] == "FAILED"
        assert kwargs["error"] == "Corrupt PDF"
        assert kwargs["total_duration_ms"] >= 0.0


def test_gap686_telemetry_never_raises_and_omits_unmeasured_verify_latency():
    """Review fix: a telemetry failure must not turn a processed invoice into FAILED,
    and a stage that was never timed must not be reported as 0 ms."""
    from telemetry import track_extraction_pipeline_turn

    with patch("telemetry._emit_event") as emit:
        track_extraction_pipeline_turn(batch_id="b", invoice_id="i", tenant_id="t", status="COMPLETED",
                                       ocr_latency_ms=12.5, llm_latency_ms=40.0)
    props = emit.call_args[0][1]
    assert "verify_latency_ms" not in props
    assert props["ocr_latency_ms"] == 12.5

    with patch("telemetry._emit_event", side_effect=RuntimeError("exporter down")):
        track_extraction_pipeline_turn(batch_id="b", invoice_id="i", tenant_id="t", status="COMPLETED")

# BE Gap 678 is verified on Postgres in tests/test_gap678_session_scope.py.
