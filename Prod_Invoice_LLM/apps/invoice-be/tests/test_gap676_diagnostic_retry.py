"""Tests for BE Gap 676: Targeted Diagnostic Guidance on Verification Retry.

Verifies:
1. format_retry_feedback generates targeted diagnostic guidance per alert type.
2. Tax mismatch guidance provides specific troubleshooting steps (tax-inclusive rates, header charges, split taxes).
3. Line items mismatch guidance provides multiline/merged cells steps and prohibits dummy line invention.
4. Faithfulness alerts provide verbatim transcription instructions.
5. Strict anti-hallucination requirement is always present on every retry pass.
6. Legacy string feedback fallback properly maps to targeted guidance.
7. extract_node injects the structured diagnostic guidance into LLM retry prompts.
"""
from unittest.mock import MagicMock, patch
import pytest
from agents.extraction_agent import (
    RETRY_DIAGNOSTIC_GUIDANCE,
    STRICT_RETRY_PROHIBITION,
    format_retry_feedback,
    extract_node,
)


def test_tax_mismatch_diagnostic_guidance():
    """tax_mismatch produces targeted instructions for rates, header charges, and verbatim totals."""
    alerts = [{
        "type": "tax_mismatch",
        "message": "Subtotal (100.00) + Tax (10.00) does not match Grand Total (125.00)",
        "field": "tax_amount",
        "severity": "error",
    }]
    feedback = ["Subtotal (100.00) + Tax (10.00) does not match Grand Total (125.00)"]
    formatted = format_retry_feedback(alerts=alerts, raw_feedback=feedback)

    assert "Subtotal (100.00) + Tax (10.00) does not match Grand Total (125.00)" in formatted
    assert "DIAGNOSTIC GUIDANCE FOR TAX / TOTALS MISMATCH:" in formatted
    assert "tax-inclusive vs tax-exclusive" in formatted
    assert "freight, shipping, handling" in formatted
    assert STRICT_RETRY_PROHIBITION in formatted
    assert "NEVER invent dummy line items" in formatted


def test_line_items_mismatch_diagnostic_guidance():
    """line_items_mismatch produces targeted instructions for multiline rows and merged cells."""
    alerts = [{
        "type": "line_items_mismatch",
        "message": "Sum of line item amounts (90.00) does not match subtotal (100.00)",
        "field": "items",
        "severity": "error",
    }]
    formatted = format_retry_feedback(alerts=alerts)

    assert "Sum of line item amounts" in formatted
    assert "DIAGNOSTIC GUIDANCE FOR LINE ITEMS MISMATCH:" in formatted
    assert "multiline descriptions, wrapped rows, or merged columns" in formatted
    assert "DO NOT invent, fabricate, or hallucinate dummy line items" in formatted
    assert STRICT_RETRY_PROHIBITION in formatted


def test_faithfulness_alerts_diagnostic_guidance():
    """Faithfulness alerts produce verbatim transcription guidance."""
    alerts = [
        {"type": "grand_total_unfaithful", "message": "Grand total 150.00 not found in source text"},
        {"type": "subtotal_unfaithful", "message": "Subtotal 120.00 not found in source text"},
    ]
    formatted = format_retry_feedback(alerts=alerts)

    assert "DIAGNOSTIC GUIDANCE FOR GRAND TOTAL FAITHFULNESS:" in formatted
    assert "DIAGNOSTIC GUIDANCE FOR SUBTOTAL FAITHFULNESS:" in formatted
    assert "transcribe it verbatim without recalculation" in formatted
    assert STRICT_RETRY_PROHIBITION in formatted


def test_legacy_string_feedback_fallback():
    """Raw feedback strings without structured alert dicts still trigger targeted guidance."""
    raw_fb = ["Subtotal (500.00) + Tax (50.00) does not match Grand Total (600.00)"]
    formatted = format_retry_feedback(alerts=[], raw_feedback=raw_fb)

    assert "Subtotal (500.00) + Tax (50.00) does not match Grand Total (600.00)" in formatted
    assert "DIAGNOSTIC GUIDANCE FOR TAX / TOTALS MISMATCH:" in formatted
    assert STRICT_RETRY_PROHIBITION in formatted


def test_anti_hallucination_prohibition_always_included():
    """Every retry prompt includes the anti-hallucination requirement regardless of alert type."""
    formatted = format_retry_feedback(alerts=[{"type": "unknown_error", "message": "Something went wrong"}])

    assert "Something went wrong" in formatted
    assert STRICT_RETRY_PROHIBITION in formatted
    assert "You must extract ONLY figures and line items that are visibly printed" in formatted
    assert "NEVER invent dummy line items, fabricate charges, or alter numbers" in formatted


def test_extract_node_injects_diagnostic_feedback():
    """extract_node appends diagnostic guidance and anti-hallucination text on retry."""
    state = {
        "ocr_text": "Sample invoice text with Subtotal: 100.00",
        "images": [],
        "flow_direction": "INBOUND",
        "retry_count": 1,
        "feedback": ["Subtotal (100.00) + Tax (10.00) does not match Grand Total (125.00)"],
        "alerts": [{
            "type": "tax_mismatch",
            "message": "Subtotal (100.00) + Tax (10.00) does not match Grand Total (125.00)",
        }],
    }

    mock_llm_result = MagicMock()
    mock_llm_result.dict.return_value = {"vendor_name": "Test Vendor", "grand_total": 125.0}

    captured_prompts = []

    def fake_invoke(prompt_arg):
        captured_prompts.append(prompt_arg)
        return mock_llm_result

    with patch("agents.extraction_agent.get_llm") as mock_get_llm, \
         patch("agents.extraction_agent.tracked_llm_call"):
        mock_instance = MagicMock()
        mock_instance.with_structured_output.return_value.invoke = fake_invoke
        mock_get_llm.return_value = mock_instance

        result = extract_node(state)

    assert len(captured_prompts) == 1
    prompt_text = captured_prompts[0]
    assert "CRITICAL FEEDBACK FROM PREVIOUS EXTRACTION ATTEMPT:" in prompt_text
    assert "DIAGNOSTIC GUIDANCE FOR TAX / TOTALS MISMATCH:" in prompt_text
    assert "CRITICAL ANTI-HALLUCINATION REQUIREMENT:" in prompt_text
    assert "NEVER invent dummy line items" in prompt_text
    assert result["retry_count"] == 2
