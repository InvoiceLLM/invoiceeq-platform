"""Tests for the outbound extraction agent (Feature 2.1, Task 2.1.2).

Mirrors test_extraction.py's style: mock check_token_guardrails + get_llm at
the module boundary, run the graph directly (no queue worker involved yet --
Task 2.1.3 builds that), and confirm each field lands where expected plus the
faithfulness checks actually catch a mismatch.

Gap 283 (2026-08-21): the patch targets moved from
`agents.outbound_extraction_agent.*` to `agents.extraction_agent.*`. Outbound no
longer has its own graph -- `run_outbound_extraction_agent` is a thin wrapper
over the one shared graph, so `check_token_guardrails`/`get_llm` now resolve in
`agents.extraction_agent`'s module globals. The imports below deliberately still
go through the outbound module, so these tests also cover the wrapper's
re-exports staying intact.
"""
from unittest.mock import patch

from agents.extraction_agent import TaxItem
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

    with patch("agents.extraction_agent.check_token_guardrails", return_value=(True, 100, 128000)), \
         patch("agents.extraction_agent.get_llm", return_value=_mock_llm(schema)):
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

    with patch("agents.extraction_agent.check_token_guardrails", return_value=(True, 100, 128000)), \
         patch("agents.extraction_agent.get_llm", return_value=_mock_llm(schema)):
        result = run_outbound_extraction_agent("mock/outbound.pdf", ocr_text, "tenant-1")

    assert result["status"] == "NEEDS_REVIEW"
    assert any(a.get("type") == "missing_required_field" and a.get("field") == "customer_name" for a in result["alerts"])


def test_zero_grand_total_is_not_treated_as_missing_required_field():
    """Post-Gap-283 correction (falsy-zero bug): the required-field check used a
    bare `if not data.get(field)`, so a genuine, faithfully-transcribed
    grand_total of 0.00 (fully-credited note / 100%-discounted order) was
    reported as `missing_required_field` and routed to NEEDS_REVIEW. Zero is a
    value, not an absence."""
    ocr_text = (
        "CREDIT NOTE\nBill To: Vertex Industries\nInvoice #: OUT-2001\n"
        "Fully credited -- no balance due\n"
        "Subtotal: 0.00\nTax: 0.00\nTotal: 0.00"
    )
    schema = OutboundInvoiceExtractionSchema(
        customer_name="Vertex Industries",
        invoice_number="OUT-2001",
        subtotal=0.00,
        grand_total=0.00,
        tax_amount=0.00,
        currency="INR",
        items=[],
    )

    with patch("agents.extraction_agent.check_token_guardrails", return_value=(True, 100, 128000)), \
         patch("agents.extraction_agent.get_llm", return_value=_mock_llm(schema)):
        result = run_outbound_extraction_agent("mock/outbound.pdf", ocr_text, "tenant-1")

    assert not any(
        a.get("type") == "missing_required_field" and a.get("field") == "grand_total"
        for a in result["alerts"]
        if isinstance(a, dict)
    ), f"0.0 grand_total wrongly flagged as missing: {result['alerts']}"
    # Nothing else is wrong with this document, so it should pass cleanly.
    assert result["alerts"] == []
    assert result["status"] == "VERIFIED"
    assert result["extracted_data"]["grand_total"] == 0.00


def test_absent_grand_total_still_flags_missing_required_field():
    """Guard on the other side of the zero fix -- None must still be caught."""
    ocr_text = "INVOICE\nBill To: Vertex Industries\nInvoice #: OUT-2002\n"
    schema = OutboundInvoiceExtractionSchema(
        customer_name="Vertex Industries",
        invoice_number="OUT-2002",
        grand_total=None,
        items=[],
    )

    with patch("agents.extraction_agent.check_token_guardrails", return_value=(True, 100, 128000)), \
         patch("agents.extraction_agent.get_llm", return_value=_mock_llm(schema)):
        result = run_outbound_extraction_agent("mock/outbound.pdf", ocr_text, "tenant-1")

    assert result["status"] == "NEEDS_REVIEW"
    assert any(
        a.get("type") == "missing_required_field" and a.get("field") == "grand_total"
        for a in result["alerts"]
        if isinstance(a, dict)
    )


def test_outbound_cgst_sgst_split_does_not_flag_tax_faithfulness():
    """Post-Gap-283 correction (Bug 2): Gap 283 told the model to sum CGST+SGST
    into `tax_amount` but gave it no `taxes[]` to record the components in, so
    `verify_tax_amount_in_source_text` always got `tax_components=None` for
    OUTBOUND and Gap 69's component-aware fallback could never engage. On a real
    India GST invoice the summed figure is never printed as one number, so every
    such outbound invoice raised `tax_amount_not_verified_in_source` for a
    correctly-extracted value. With `taxes[]` on the outbound schema the same
    fallback inbound uses now applies."""
    ocr_text = (
        "TAX INVOICE\nBill To: Vertex Industries\nInvoice #: OUT-3001\n"
        "Line 1   1   67,760.00   67,760.00\n"
        "Taxable Value: 67,760.00\n"
        "CGST 9%: 6,098.40\n"
        "SGST 9%: 6,098.40\n"
        "Total: 79,956.80"
    )
    schema = OutboundInvoiceExtractionSchema(
        customer_name="Vertex Industries",
        invoice_number="OUT-3001",
        subtotal=67760.00,
        # Never printed as a single figure -- only the two components are.
        tax_amount=12196.80,
        grand_total=79956.80,
        currency="INR",
        items=[OutboundInvoiceLineItem(description="Line 1", quantity=1.0, unit_price=67760.00, amount=67760.00)],
        taxes=[
            TaxItem(tax_type="CGST", rate_percent=9.0, amount=6098.40),
            TaxItem(tax_type="SGST", rate_percent=9.0, amount=6098.40),
        ],
    )

    with patch("agents.extraction_agent.check_token_guardrails", return_value=(True, 100, 128000)), \
         patch("agents.extraction_agent.get_llm", return_value=_mock_llm(schema)):
        result = run_outbound_extraction_agent("mock/outbound.pdf", ocr_text, "tenant-1")

    assert not any(
        a.get("type") == "tax_amount_not_verified_in_source"
        for a in result["alerts"]
        if isinstance(a, dict)
    ), f"CGST+SGST split wrongly flagged as unfaithful tax: {result['alerts']}"
    assert result["alerts"] == []
    assert result["status"] == "VERIFIED"
    assert [t["tax_type"] for t in result["extracted_data"]["taxes"]] == ["CGST", "SGST"]


def test_outbound_fabricated_tax_amount_still_flagged_with_components():
    """The split-tax fallback must not become a blanket exemption: components
    that don't sum to the extracted tax_amount still fail the check."""
    ocr_text = (
        "TAX INVOICE\nBill To: Vertex Industries\nInvoice #: OUT-3002\n"
        "Line 1   1   1000.00   1000.00\n"
        "Taxable Value: 1000.00\n"
        "CGST 9%: 90.00\n"
        "SGST 9%: 90.00\n"
        "Total: 1250.00"
    )
    schema = OutboundInvoiceExtractionSchema(
        customer_name="Vertex Industries",
        invoice_number="OUT-3002",
        subtotal=1000.00,
        # 250.00 is printed nowhere, and the two grounded components sum to
        # 180.00 -- so neither the direct check nor the Gap 69 fallback passes.
        tax_amount=250.00,
        grand_total=1250.00,
        currency="INR",
        items=[OutboundInvoiceLineItem(description="Line 1", quantity=1.0, unit_price=1000.00, amount=1000.00)],
        taxes=[
            TaxItem(tax_type="CGST", rate_percent=9.0, amount=90.00),
            TaxItem(tax_type="SGST", rate_percent=9.0, amount=90.00),
        ],
    )

    with patch("agents.extraction_agent.check_token_guardrails", return_value=(True, 100, 128000)), \
         patch("agents.extraction_agent.get_llm", return_value=_mock_llm(schema)):
        result = run_outbound_extraction_agent("mock/outbound.pdf", ocr_text, "tenant-1")

    assert result["status"] == "NEEDS_REVIEW"
    assert any(
        a.get("type") == "tax_amount_not_verified_in_source"
        for a in result["alerts"]
        if isinstance(a, dict)
    )


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

    with patch("agents.extraction_agent.check_token_guardrails", return_value=(True, 100, 128000)), \
         patch("agents.extraction_agent.get_llm", return_value=_mock_llm(schema)):
        result = run_outbound_extraction_agent("mock/outbound.pdf", ocr_text, "tenant-1")

    assert result["status"] == "NEEDS_REVIEW"
    assert len(result["alerts"]) >= 1


def test_token_limit_exceeded_short_circuits():
    with patch("agents.extraction_agent.check_token_guardrails", return_value=(False, 999999, 128000)):
        result = run_outbound_extraction_agent("mock/outbound.pdf", "some ocr text", "tenant-1")

    assert result["status"] == "NEEDS_REVIEW"
    assert result["alerts"][0]["type"] == "token_limit_exceeded"
    assert result["extracted_data"] is None


def test_outbound_discount_and_round_off_reconciles_without_needs_review():
    """Gap 293: before this, `OutboundInvoiceExtractionSchema` had no
    discount_amount/discount_percent/round_off fields, so an outbound invoice
    with a real trade discount or Round Off line always failed
    verify_totals_math (those keys always came back None) and landed on
    NEEDS_REVIEW even though the printed numbers reconcile perfectly:
    1000 (subtotal) - 100 (discount) + 90 (tax) + 0.20 (round off) = 990.20."""
    ocr_text = (
        "TAX INVOICE\nBill To: Vertex Industries\nInvoice #: OUT-4001\n"
        "Line 1   1   1000.00   1000.00\n"
        "Subtotal: 1000.00\nTrade Discount: 100.00\nTax: 90.00\n"
        "Round Off: 0.20\nTotal: 990.20"
    )
    schema = OutboundInvoiceExtractionSchema(
        customer_name="Vertex Industries",
        invoice_number="OUT-4001",
        subtotal=1000.00,
        tax_amount=90.00,
        grand_total=990.20,
        discount_amount=100.00,
        round_off=0.20,
        currency="INR",
        items=[OutboundInvoiceLineItem(description="Line 1", quantity=1.0, unit_price=1000.00, amount=1000.00)],
    )

    with patch("agents.extraction_agent.check_token_guardrails", return_value=(True, 100, 128000)), \
         patch("agents.extraction_agent.get_llm", return_value=_mock_llm(schema)):
        result = run_outbound_extraction_agent("mock/outbound.pdf", ocr_text, "tenant-1")

    assert not any(
        "does not match Grand Total" in a.get("message", "")
        for a in result["alerts"]
        if isinstance(a, dict)
    ), f"discount+round_off invoice wrongly flagged as a totals mismatch: {result['alerts']}"
    assert result["extracted_data"]["discount_amount"] == 100.00
    assert result["extracted_data"]["round_off"] == 0.20


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

    with patch("agents.extraction_agent.check_token_guardrails", return_value=(True, 100, 128000)), \
         patch("agents.extraction_agent.get_llm", return_value=_mock_llm(schema)):
        result = run_outbound_extraction_agent("mock/outbound.pdf", ocr_text, "tenant-1")

    assert result["status"] == "NEEDS_REVIEW"
    assert any("does not match Grand Total" in a.get("message", "") for a in result["alerts"])
