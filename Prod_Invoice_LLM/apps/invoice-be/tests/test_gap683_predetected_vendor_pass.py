"""
Unit tests for BE Gap 683: Eliminate redundant first extraction pass via OCR vendor pre-detection.
Pure mock unit tests — DB-free, network-free.
"""
from unittest.mock import MagicMock, patch
from uuid import uuid4
from queue_worker.handlers import _extract_predetected_vendor, handle_process_invoice


def test_gap683_extract_predetected_vendor():
    """Verify _extract_predetected_vendor reads vendor from diverse OCR outputs."""
    # From direct vendor_name
    assert _extract_predetected_vendor({"vendor_name": "Acme Supplies"}) == "Acme Supplies"

    # From source_document_json dict value
    ocr_dict = {
        "source_document_json": {
            "VendorName": {"value": "Acme Global", "type": "string"}
        }
    }
    assert _extract_predetected_vendor(ocr_dict) == "Acme Global"

    # From source_document_json plain string
    ocr_plain = {"source_document_json": {"VendorName": "Acme Plain"}}
    assert _extract_predetected_vendor(ocr_plain) == "Acme Plain"

    # None cases
    assert _extract_predetected_vendor(None) is None
    assert _extract_predetected_vendor("raw text only") is None
    assert _extract_predetected_vendor({}) is None


def test_gap683_single_pass_when_vendor_predetected_with_rules():
    """Verify BE Gap 683: When vendor is pre-detected in OCR and has trained rules,

    run_extraction_agent is called EXACTLY ONCE with merged rules upfront.
    """
    batch_id = "batch-683-1"
    file_path = "tenants/t1/invoices/test_vendor.pdf"
    tenant_id = str(uuid4())

    mock_ocr_result = {
        "content": "Invoice Text",
        "vendor_name": "Trained Vendor",
        "coordinates": [],
        "field_confidence": {},
        "source_document_json": {},
    }

    mock_invoice = MagicMock()
    mock_invoice.id = uuid4()
    mock_invoice.tenant_id = tenant_id
    mock_invoice.file_path = file_path
    mock_invoice.status = "PROCESSING"
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

    # Mock template rules:
    # 1. Global rules: ["Global Rule 1"]
    # 2. Vendor rules for Trained Vendor: ["Vendor Rule 1"]
    def mock_get_template_rules(session, tid, vendor):
        if vendor is None:
            return ["Global Rule 1"]
        if "Trained Vendor" in str(vendor):
            return ["Vendor Rule 1"]
        return []

    with patch("queue_worker.handlers.Session") as mock_session_cls, \
         patch("queue_worker.handlers._run_ocr", return_value=mock_ocr_result), \
         patch("queue_worker.handlers._get_template_rules", side_effect=mock_get_template_rules), \
         patch("queue_worker.handlers.run_extraction_agent") as mock_agent, \
         patch("queue_worker.handlers._publish_sse_events"), \
         patch("chroma_client.should_index_status", return_value=False), \
         patch("queue_worker.handlers.track_extraction_pipeline_turn"):

        mock_session_cls.return_value.__enter__.return_value = mock_session
        mock_agent.return_value = {
            "status": "COMPLETED",
            "alerts": [],
            "extracted_data": {
                "vendor_name": "Trained Vendor",
                "invoice_number": "INV-100",
                "grand_total": 250.0,
            },
            "doc_type": "TAX_INVOICE",
            "doc_type_evidence": "Printed",
            "doc_attributes": {},
            "doc_type_confidence": 0.99,
        }

        result = handle_process_invoice(batch_id, file_path, tenant_id)

        assert result["status"] == "COMPLETED"
        # Crucial check: run_extraction_agent must only be called ONCE!
        assert mock_agent.call_count == 1

        # Check that the single run received the merged constraints upfront
        call_kwargs = mock_agent.call_args[1]
        rules_passed = call_kwargs["rules"]["constraints"]
        assert "Global Rule 1" in rules_passed
        assert "Vendor Rule 1" in rules_passed


# ---------------------------------------------------------------------------
# Review additions (2026-09-17)
# ---------------------------------------------------------------------------
from types import SimpleNamespace  # noqa: E402

RULES = {None: ["Global Rule 1"], "Trained Vendor": ["Vendor Rule 1"], "Other Trained": ["Other Rule"]}


def _run_with(extracted_vendor, predetected="Trained Vendor"):
    mock_invoice = MagicMock()
    mock_invoice.id = uuid4()
    mock_invoice.status = "PROCESSING"
    mock_invoice.tags = []
    session = MagicMock()

    def _exec(stmt):
        res = MagicMock()
        res.first.return_value = mock_invoice if "where invoice.file_path" in str(stmt).lower() else None
        res.all.return_value = []
        return res

    session.exec.side_effect = _exec
    ocr = {"content": "text", "vendor_name": predetected, "coordinates": [], "field_confidence": {}, "source_document_json": {}}
    agent_out = {"status": "COMPLETED", "alerts": [],
                 "extracted_data": {"vendor_name": extracted_vendor, "invoice_number": "INV-1", "grand_total": 10.0}}
    with patch("queue_worker.handlers.Session") as session_cls, \
         patch("queue_worker.handlers._run_ocr", return_value=ocr), \
         patch("queue_worker.handlers._get_template_rules", side_effect=lambda s, t, v: RULES.get(v, [])), \
         patch("queue_worker.handlers.run_extraction_agent", return_value=agent_out) as agent, \
         patch("queue_worker.handlers._publish_sse_events"), \
         patch("chroma_client.should_index_status", return_value=False), \
         patch("queue_worker.handlers.track_extraction_pipeline_turn"):
        session_cls.return_value.__enter__.return_value = session
        handle_process_invoice("b", "tenants/t/invoices/x.pdf", str(uuid4()))
    return [c.kwargs["rules"] for c in agent.call_args_list]


def test_gap683_predetected_vendor_confirmed_by_extraction_stays_single_pass():
    assert len(_run_with("Trained Vendor")) == 1


def test_gap683_wrong_predetected_vendor_reruns_with_global_only():
    """DI read the wrong party; the real vendor has no trained rules -> Global-only re-run."""
    calls = _run_with("Some Untrained Supplier")
    assert len(calls) == 2
    assert "Vendor Rule 1" in calls[0]["constraints"]
    assert calls[1] == {"constraints": ["Global Rule 1"]}


def test_gap683_wrong_predetected_vendor_reruns_with_the_extracted_vendors_rules():
    calls = _run_with("Other Trained")
    assert len(calls) == 2
    assert "Other Rule" in calls[1]["constraints"]
    assert "Vendor Rule 1" not in calls[1]["constraints"]


def test_gap683_run_ocr_does_not_crash_when_document_intelligence_returns_no_documents():
    """The first version raised UnboundLocalError here, failing every such upload."""
    result = SimpleNamespace(content="plain page text", pages=[], documents=[])
    client = MagicMock()
    client.begin_analyze_document.return_value.result.return_value = result
    pool = MagicMock()
    pool.next_endpoint_key.return_value = ("https://di.example", "key")
    settings = SimpleNamespace(LLM_PROVIDER="azure", DOC_INTEL_MODEL_ID="prebuilt-invoice")

    from queue_worker.handlers import _run_ocr

    with patch("queue_worker.handlers.download_pdf_from_storage", return_value=b"%PDF"), \
         patch("utils.doc_intel_client.get_doc_intel_pool", return_value=pool), \
         patch("azure.ai.documentintelligence.DocumentIntelligenceClient", return_value=client):
        out = _run_ocr("tenants/t/invoices/x.pdf", settings)

    assert out["content"] == "plain page text"
    assert out["vendor_name"] is None
