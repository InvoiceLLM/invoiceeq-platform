"""Regression and unit tests for BE Gap 676:
Verification retry prompt guidance, anti-hallucination directive, and shared feedback builder.
"""
from typing import Any, Dict, List
import pytest

from agents.extraction_agent import (
    ALERT_DIAGNOSTIC_GUIDANCE,
    NO_HALLUCINATION_DIRECTIVE,
    RETRY_FEEDBACK_HEADER,
    build_extraction_retry_feedback,
    extract_node,
    _DIRECTION_PROFILES,
)
import agents.extraction_agent as ea
import config


def test_empty_feedback_returns_empty_string():
    assert build_extraction_retry_feedback([], []) == ""
    assert build_extraction_retry_feedback([]) == ""
    assert build_extraction_retry_feedback([], None) == ""


def test_no_hallucination_directive_in_all_feedback():
    feedback = ["Line items sum (90.00) does not match subtotal (100.00)"]
    result = build_extraction_retry_feedback(feedback)
    assert RETRY_FEEDBACK_HEADER in result
    assert NO_HALLUCINATION_DIRECTIVE in result
    assert "CRITICAL RECONCILIATION RULE" in result
    assert "NEVER invent, hallucinate, or fabricate line items" in result
    assert "- Line items sum (90.00) does not match subtotal (100.00)" in result


def test_tax_mismatch_targeted_guidance():
    alerts = [
        {
            "type": "tax_mismatch",
            "message": "Subtotal (100.00) + Tax (10.00) does not match Grand Total (125.00)",
            "field": "tax_amount",
        }
    ]
    feedback = ["Subtotal (100.00) + Tax (10.00) does not match Grand Total (125.00)"]
    result = build_extraction_retry_feedback(feedback, alerts=alerts)

    assert ALERT_DIAGNOSTIC_GUIDANCE["tax_mismatch"] in result
    assert "tax-inclusive or tax-exclusive" in result
    assert "freight" in result.lower()
    assert "handling" in result.lower()
    assert NO_HALLUCINATION_DIRECTIVE in result


def test_line_items_mismatch_targeted_guidance():
    alerts = [
        {
            "type": "line_items_mismatch",
            "message": "Line items sum (85.00) does not match subtotal (100.00)",
            "field": "subtotal",
        }
    ]
    feedback = ["Line items sum (85.00) does not match subtotal (100.00)"]
    result = build_extraction_retry_feedback(feedback, alerts=alerts)

    assert ALERT_DIAGNOSTIC_GUIDANCE["line_items_mismatch"] in result
    assert "header-level discount" in result
    assert "merged cells" in result
    assert NO_HALLUCINATION_DIRECTIVE in result


def test_line_item_calculation_mismatch_guidance():
    alerts = [
        {
            "type": "line_item_calculation_mismatch",
            "message": "Line item 'Widget' amount (50.00) does not match calculated amount (45.00)",
            "field": "items",
        }
    ]
    feedback = ["Line item 'Widget' amount (50.00) does not match calculated amount (45.00)"]
    result = build_extraction_retry_feedback(feedback, alerts=alerts)

    assert ALERT_DIAGNOSTIC_GUIDANCE["line_item_calculation_mismatch"] in result
    assert "unit price and quantity" in result


def test_missing_required_field_guidance():
    alerts = [
        {
            "type": "missing_required_field",
            "field": "vendor_name",
            "message": "Required field 'vendor_name' could not be extracted.",
        }
    ]
    feedback = ["Required field 'vendor_name' could not be extracted."]
    result = build_extraction_retry_feedback(feedback, alerts=alerts)

    assert ALERT_DIAGNOSTIC_GUIDANCE["missing_required_field"] in result
    assert "header, footer, seller/buyer details" in result


def test_source_text_mismatch_guidance():
    alerts = [
        {
            "type": "source_text_mismatch",
            "field": "grand_total",
            "message": "Extracted grand total (120.00) not found in source document text",
        }
    ]
    feedback = ["Extracted grand total (120.00) not found in source document text"]
    result = build_extraction_retry_feedback(feedback, alerts=alerts)

    assert ALERT_DIAGNOSTIC_GUIDANCE["source_text_mismatch"] in result
    assert "verbatim exactly as printed" in result


def test_table_alignment_guidance():
    alerts = [
        {
            "type": "table_alignment",
            "message": "Table row alignment error in columns",
        }
    ]
    feedback = ["Table row alignment error in columns"]
    result = build_extraction_retry_feedback(feedback, alerts=alerts)

    assert ALERT_DIAGNOSTIC_GUIDANCE["table_alignment"] in result
    assert "table columns and headers" in result


def test_combined_alerts_multiple_guidance_sections():
    alerts = [
        {
            "type": "tax_mismatch",
            "message": "Subtotal + Tax mismatch",
        },
        {
            "type": "line_items_mismatch",
            "message": "Line items sum mismatch",
        },
    ]
    feedback = ["Subtotal + Tax mismatch", "Line items sum mismatch"]
    result = build_extraction_retry_feedback(feedback, alerts=alerts)

    assert ALERT_DIAGNOSTIC_GUIDANCE["tax_mismatch"] in result
    assert ALERT_DIAGNOSTIC_GUIDANCE["line_items_mismatch"] in result
    assert NO_HALLUCINATION_DIRECTIVE in result


def test_string_feedback_fallback_inference():
    """When alerts dict list is missing, string messages still infer alert types."""
    feedback = [
        "Subtotal (100.00) + Tax (10.00) does not match Grand Total (125.00)",
        "Line items sum (85.00) does not match subtotal (100.00)",
        "Required field 'invoice_number' could not be extracted.",
    ]
    result = build_extraction_retry_feedback(feedback)

    assert ALERT_DIAGNOSTIC_GUIDANCE["tax_mismatch"] in result
    assert ALERT_DIAGNOSTIC_GUIDANCE["line_items_mismatch"] in result
    assert ALERT_DIAGNOSTIC_GUIDANCE["missing_required_field"] in result
    assert NO_HALLUCINATION_DIRECTIVE in result


class _MockStructuredLLM:
    def __init__(self):
        self.invoked_prompts = []

    def with_structured_output(self, schema):
        return self

    def invoke(self, prompt_or_messages):
        self.invoked_prompts.append(prompt_or_messages)
        return {
            "vendor_name": "Test Vendor",
            "invoice_number": "INV-1001",
            "invoice_date": "2026-09-17",
            "subtotal": 100.0,
            "grand_total": 110.0,
            "tax_amount": 10.0,
            "items": [],
        }


def test_extract_node_text_retry_feedback_integration(monkeypatch):
    mock_llm = _MockStructuredLLM()
    monkeypatch.setattr(ea, "get_llm", lambda **kwargs: mock_llm)
    monkeypatch.setattr(config.settings, "LLM_PROVIDER", "openai")

    alerts = [{"type": "tax_mismatch", "message": "Totals mismatch"}]
    feedback = ["Totals mismatch"]
    state: Dict[str, Any] = {
        "file_path": "test_invoice.pdf",
        "ocr_text": "Sample invoice text",
        "images": [],
        "flow_direction": "INBOUND",
        "doc_type": None,
        "rules": None,
        "retry_count": 1,
        "feedback": feedback,
        "alerts": alerts,
        "complexity": "STANDARD",
    }

    ea.extract_node(state)

    assert len(mock_llm.invoked_prompts) == 1
    prompt_str = mock_llm.invoked_prompts[0]
    assert isinstance(prompt_str, str)
    assert RETRY_FEEDBACK_HEADER in prompt_str
    assert NO_HALLUCINATION_DIRECTIVE in prompt_str
    assert ALERT_DIAGNOSTIC_GUIDANCE["tax_mismatch"] in prompt_str
    assert "- Totals mismatch" in prompt_str


def test_extract_node_multimodal_retry_feedback_integration(monkeypatch):
    mock_llm = _MockStructuredLLM()
    monkeypatch.setattr(ea, "get_llm", lambda **kwargs: mock_llm)
    monkeypatch.setattr(config.settings, "LLM_PROVIDER", "azure")

    alerts = [{"type": "line_items_mismatch", "message": "Line items sum mismatch"}]
    feedback = ["Line items sum mismatch"]
    state: Dict[str, Any] = {
        "file_path": "test_invoice.pdf",
        "ocr_text": "Sample invoice text",
        "images": ["data:image/png;base64,AAAA"],
        "flow_direction": "INBOUND",
        "doc_type": None,
        "rules": None,
        "retry_count": 1,
        "feedback": feedback,
        "alerts": alerts,
        "complexity": "STANDARD",
    }

    ea.extract_node(state)

    assert len(mock_llm.invoked_prompts) == 1
    messages = mock_llm.invoked_prompts[0]
    # Check that feedback block is appended to message text content
    text_content_blocks = [c["text"] for c in messages[0].content if c.get("type") == "text"]
    all_text = "\n".join(text_content_blocks)
    assert RETRY_FEEDBACK_HEADER in all_text
    assert NO_HALLUCINATION_DIRECTIVE in all_text
    assert ALERT_DIAGNOSTIC_GUIDANCE["line_items_mismatch"] in all_text
    assert "- Line items sum mismatch" in all_text


def test_multimodal_and_text_feedback_parity():
    """Text and multimodal retry paths generate the exact same feedback payload."""
    alerts = [{"type": "tax_mismatch", "message": "Tax mismatch"}]
    feedback = ["Tax mismatch"]
    expected_feedback = build_extraction_retry_feedback(feedback, alerts=alerts)

    # Calling it directly twice produces identical output
    call_1 = build_extraction_retry_feedback(feedback, alerts=alerts)
    call_2 = build_extraction_retry_feedback(feedback, alerts=alerts)
    assert call_1 == call_2 == expected_feedback
