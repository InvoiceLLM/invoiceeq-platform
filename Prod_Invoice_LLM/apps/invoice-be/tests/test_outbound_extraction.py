"""Tests for the outbound extraction agent (Feature 2.1, Task 2.1.2).

Mirrors test_extraction.py's style: mock check_token_guardrails + get_llm at
the module boundary, run the graph directly (no queue worker involved yet --
Task 2.1.3 builds that), and confirm each field lands where expected plus the
faithfulness checks actually catch a mismatch.
"""
from unittest.mock import patch

from agents.outbound_extraction_agent import (
    OutboundInvoiceExtractionSchema,
    OutboundInvoiceLineItem,
    run_outbound_extraction_agent,
)


def _mock_llm(schema_instance):
    class MockStructuredLLM:
        def invoke(self, prompt):
            return schema_instance

    class MockLLM:
        def with_structured_output(self, schema):
            return MockStructuredLLM()

    return MockLLM()


def test_clean_outbound_invoice_reaches_verified():
    ocr_text = (
        "INVOICE\nBill To: Vertex Industries\nInvoice #: OUT-1001\n"
        "Line 1   1   100.00   100.00\n"
        "Tax: 10.00\nTotal: 110.00"
    )
    schema = OutboundInvoiceExtractionSchema(
        customer_name="Vertex Industries",
        invoice_number="OUT-1001",
        invoice_date="2026-07-01",
        due_date="2026-07-31",
        subtotal=100.00,
        grand_total=110.00,
        tax_amount=10.00,
        currency="USD",
        items=[OutboundInvoiceLineItem(description="Line 1", quantity=1.0, unit_price=100.00, amount=100.00)],
    )

    with patch("agents.outbound_extraction_agent.check_token_guardrails", return_value=(True, 100, 128000)), \
         patch("agents.outbound_extraction_agent.get_llm", return_value=_mock_llm(schema)):
        result = run_outbound_extraction_agent("mock/outbound.pdf", ocr_text, "tenant-1")

    assert result["status"] == "VERIFIED"
    assert result["alerts"] == []
    assert result["extracted_data"]["customer_name"] == "Vertex Industries"
    assert result["extracted_data"]["grand_total"] == 110.00


def test_missing_required_field_flags_needs_review():
    ocr_text = "INVOICE\nInvoice #: OUT-1002\nTotal: 50.00"
    schema = OutboundInvoiceExtractionSchema(
        customer_name=None,  # missing -- required field
        invoice_number="OUT-1002",
        grand_total=50.00,
        items=[],
    )

    with patch("agents.outbound_extraction_agent.check_token_guardrails", return_value=(True, 100, 128000)), \
         patch("agents.outbound_extraction_agent.get_llm", return_value=_mock_llm(schema)):
        result = run_outbound_extraction_agent("mock/outbound.pdf", ocr_text, "tenant-1")

    assert result["status"] == "NEEDS_REVIEW"
    assert any(a.get("type") == "missing_required_field" and a.get("field") == "customer_name" for a in result["alerts"])


def test_grand_total_not_in_source_text_flags_needs_review():
    """Gap 33's outbound equivalent -- a silently 'corrected' total that
    doesn't match anything actually printed in the OCR text."""
    ocr_text = "INVOICE\nBill To: Vertex Industries\nInvoice #: OUT-1003\nTotal: 999.00"
    schema = OutboundInvoiceExtractionSchema(
        customer_name="Vertex Industries",
        invoice_number="OUT-1003",
        grand_total=123.45,  # never appears in ocr_text above
        items=[],
    )

    with patch("agents.outbound_extraction_agent.check_token_guardrails", return_value=(True, 100, 128000)), \
         patch("agents.outbound_extraction_agent.get_llm", return_value=_mock_llm(schema)):
        result = run_outbound_extraction_agent("mock/outbound.pdf", ocr_text, "tenant-1")

    assert result["status"] == "NEEDS_REVIEW"
    assert len(result["alerts"]) >= 1


def test_token_limit_exceeded_short_circuits():
    with patch("agents.outbound_extraction_agent.check_token_guardrails", return_value=(False, 999999, 128000)):
        result = run_outbound_extraction_agent("mock/outbound.pdf", "some ocr text", "tenant-1")

    assert result["status"] == "NEEDS_REVIEW"
    assert result["alerts"][0]["type"] == "token_limit_exceeded"
    assert result["extracted_data"] is None


def test_outbound_invoice_math_mismatch_flags_needs_review():
    ocr_text = (
        "INVOICE\nBill To: Vertex Industries\nInvoice #: OUT-1001\n"
        "Line 1   1   100.00   100.00\n"
        "Subtotal: 100.00\n"
        "Tax: 10.00\nTotal: 150.00"
    )
    schema = OutboundInvoiceExtractionSchema(
        customer_name="Vertex Industries",
        invoice_number="OUT-1001",
        invoice_date="2026-07-01",
        due_date="2026-07-31",
        subtotal=100.00,
        grand_total=150.00,
        tax_amount=10.00,
        currency="USD",
        items=[OutboundInvoiceLineItem(description="Line 1", quantity=1.0, unit_price=100.00, amount=100.00)],
    )

    with patch("agents.outbound_extraction_agent.check_token_guardrails", return_value=(True, 100, 128000)), \
         patch("agents.outbound_extraction_agent.get_llm", return_value=_mock_llm(schema)):
        result = run_outbound_extraction_agent("mock/outbound.pdf", ocr_text, "tenant-1")

    assert result["status"] == "NEEDS_REVIEW"
    assert any("does not match Grand Total" in a.get("message", "") for a in result["alerts"])
