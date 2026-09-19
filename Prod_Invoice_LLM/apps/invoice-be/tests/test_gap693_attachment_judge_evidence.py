"""BE Gap 693: attachment turns must hand the judge the document they answered from.

The 2026-09-18 Dev eval is the evidence this exists: `attach_a1` and `attach_b1`
both answered correctly (`accuracy_score=1.0`) and both failed, because
`faithfulness` was scored 0.00 against no context at all.
"""
from types import SimpleNamespace

from agents.query_agent import _attachment_judge_evidence


def _turn(status="success", gate="", stop=""):
    return SimpleNamespace(status=status, answer_gate=gate, stop_reason=stop)


def test_content_branch_page_spans_become_context():
    result = {
        "content": "The PO covers freight of USD 40.",
        "evidence": [
            {"page": 2, "text": "Freight and handling ......... USD 40.00"},
            {"page": 3, "text": "Total ......... USD 5,740.00"},
        ],
    }
    ev = _attachment_judge_evidence(result, _turn())
    assert ev["route"] == "attachment"
    assert "DOCUMENT PAGE 2:" in ev["context"]
    assert "USD 40.00" in ev["context"]
    assert "USD 5,740.00" in ev["context"]
    assert ev["executed_queries"] == ""


def test_pair_comparison_payload_becomes_context():
    result = {"attachment_pair_comparison": {"doc_a": "PO-7002", "doc_b": "INV-9", "delta": 40.0}}
    ev = _attachment_judge_evidence(result, _turn())
    assert "DOCUMENT-TO-DOCUMENT COMPARISON:" in ev["context"]
    assert "PO-7002" in ev["context"]


def test_multi_invoice_and_reconciliation_payloads_become_context():
    multi = _attachment_judge_evidence({"attachment_multi_comparison": {"matched": ["INV-1"]}}, _turn())
    assert "DOCUMENT-TO-INVOICE COMPARISON:" in multi["context"] and "INV-1" in multi["context"]
    recon = _attachment_judge_evidence({"reconciliation": {"unmatched": ["INV-2"]}}, _turn())
    assert "RECONCILIATION RESULT:" in recon["context"] and "INV-2" in recon["context"]


def test_line_items_are_carried_when_a_branch_narrates_them():
    ev = _attachment_judge_evidence(
        {"line_items": [{"description": "Bolts", "amount": 120.0}], "unmatched": [{"description": "Freight"}]},
        _turn(),
    )
    assert "LINE ITEMS:" in ev["context"] and "Bolts" in ev["context"]
    assert "UNMATCHED LINES:" in ev["context"] and "Freight" in ev["context"]


def test_a_turn_with_nothing_to_judge_returns_no_evidence_rather_than_empty_context():
    """The clarification reply asks a question and asserts nothing. The judge must
    skip it -- scoring it 0.0 for lack of evidence is the defect this gap is about."""
    result = {"content": "Did you want me to read it or compare it?", "attachment_clarification": {}}
    assert _attachment_judge_evidence(result, _turn()) == {}


def test_the_turns_declared_outcome_is_carried_for_the_abstain_rule():
    ev = _attachment_judge_evidence(
        {"evidence": [{"page": 1, "text": "x"}]},
        _turn(status="success", gate="abstained", stop="answer_contract_gate"),
    )
    assert ev["answer_gate"] == "abstained"
    assert ev["turn_status"] == "success"
    assert ev["stop_reason"] == "answer_contract_gate"
