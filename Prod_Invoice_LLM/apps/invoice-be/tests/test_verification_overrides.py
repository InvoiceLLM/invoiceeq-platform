"""Feature 18: tolerance / threshold parameterization and the verify_node wiring.

Two halves, tested separately on purpose:

  * `utils/verification_tools.py` gained an optional `tolerances` parameter.
    Nothing else about those checks changed, so the first tests pin that omitting
    the parameter is byte-identical to the pre-Feature-18 behaviour.
  * `agents/extraction_agent.py::verify_node` never read `state["rules"]` **at
    all** before this — `rules` was in `ExtractionState` and read by
    `extract_node`, but the verification node ignored it entirely. So a tenant
    could commit a "this alert is unnecessary" correction and absolutely nothing
    downstream would consult it. The second group of tests pins the wiring, not
    just the parameter, because that is where the real gap was.
"""

from agents.extraction_agent import verify_node
from agents.outbound_extraction_agent import verify_node as outbound_verify_node
from utils.rule_schema import (
    build_alert_override_rule,
    build_confidence_threshold_rule,
    build_tolerance_rule,
)
from utils.verification_tools import verify_line_items_math, verify_totals_math


# A line whose printed amount (25.00) is 5.00 away from qty * unit_price (20.00).
_OFF_BY_FIVE = [{"description": "x", "quantity": 2, "unit_price": 10.0, "amount": 25.0}]


# ── The checks themselves: additive parameter, unchanged defaults ─────────────

def test_tolerance_defaults_are_byte_identical_to_pre_feature_18():
    assert verify_line_items_math(_OFF_BY_FIVE, 25.0) == verify_line_items_math(
        _OFF_BY_FIVE, 25.0, tolerances=None
    )
    assert verify_line_items_math(_OFF_BY_FIVE, 25.0) is not None  # still flagged

    assert verify_totals_math(100.0, 10.0, 130.0) == verify_totals_math(
        100.0, 10.0, 130.0, tolerances=None
    )
    assert verify_totals_math(100.0, 10.0, 130.0) is not None


def test_tolerance_override_suppresses_a_line_item_calculation_mismatch():
    assert verify_line_items_math(_OFF_BY_FIVE, 25.0)["type"] == "line_item_calculation_mismatch"

    widened = {"line_item_calculation_mismatch": {"abs_tol": 6.0, "rel_tol": 0.005}}
    assert verify_line_items_math(_OFF_BY_FIVE, 25.0, tolerances=widened) is None

    # Loosened, not disabled: a gap wider than the override still fires.
    far = [{"description": "x", "quantity": 2, "unit_price": 10.0, "amount": 95.0}]
    assert verify_line_items_math(far, 95.0, tolerances=widened) is not None


def test_tolerance_override_is_per_alert_type_not_global():
    """The per-line and subtotal-sum checks measure different things, so widening
    one must not silently widen the other."""
    exact_line = [{"description": "x", "quantity": 2, "unit_price": 10.0, "amount": 20.0}]

    only_line_widened = {"line_item_calculation_mismatch": {"abs_tol": 50.0, "rel_tol": 0.5}}
    alert = verify_line_items_math(exact_line, 25.0, tolerances=only_line_widened)
    assert alert is not None and alert["type"] == "line_items_mismatch"

    both = dict(only_line_widened, line_items_mismatch={"abs_tol": 6.0, "rel_tol": 0.005})
    assert verify_line_items_math(exact_line, 25.0, tolerances=both) is None


def test_tax_mismatch_tolerance_override():
    assert verify_totals_math(100.0, 10.0, 115.0)["type"] == "tax_mismatch"
    widened = {"tax_mismatch": {"abs_tol": 6.0, "rel_tol": 0.005}}
    assert verify_totals_math(100.0, 10.0, 115.0, tolerances=widened) is None


# ── The wiring: verify_node must actually consult state["rules"] ──────────────

def _inbound_state(**overrides) -> dict:
    state = {
        "file_path": "mock/x.pdf",
        "ocr_text": "",
        "extracted_data": {},
        "alerts": [],
        "rules": None,
        "ocr_result": None,
    }
    state.update(overrides)
    return state


def test_verify_node_reads_state_rules_for_tolerances():
    data = {
        "items": _OFF_BY_FIVE,
        "subtotal": 25.0,
        "tax_amount": 10.0,
        "grand_total": 35.0,
    }
    before = verify_node(_inbound_state(extracted_data=data))
    assert any(a.get("type") == "line_item_calculation_mismatch" for a in before["alerts"])

    rules = {"constraints": [build_tolerance_rule(
        alert_type="line_item_calculation_mismatch", field="items", abs_tol=6.0, rel_tol=0.005,
    )]}
    after = verify_node(_inbound_state(extracted_data=data, rules=rules))
    assert not any(a.get("type") == "line_item_calculation_mismatch" for a in after["alerts"])


def test_verify_node_applies_confidence_threshold_override():
    ocr_result = {"field_confidence": {"VendorName": 0.3}}
    before = verify_node(_inbound_state(ocr_result=ocr_result))
    assert any(a.get("type") == "low_confidence_field" for a in before["alerts"])

    rules = {"constraints": [build_confidence_threshold_rule(threshold=0.2)]}
    after = verify_node(_inbound_state(ocr_result=ocr_result, rules=rules))
    assert not any(a.get("type") == "low_confidence_field" for a in after["alerts"])


def test_verify_node_applies_severity_and_message_overrides():
    rules = {"constraints": [build_alert_override_rule(
        alert_type="tax_mismatch", severity="warning", message="Known vendor rounding.",
    )]}
    alerts = verify_node(_inbound_state(
        extracted_data={"subtotal": 100.0, "tax_amount": 10.0, "grand_total": 130.0},
        rules=rules,
    ))["alerts"]

    tax_alert = next(a for a in alerts if a.get("type") == "tax_mismatch")
    assert tax_alert["severity"] == "warning"
    assert tax_alert["message"] == "Known vendor rounding."
    # The computed detail survives, so an auditor can still see what really happened.
    assert tax_alert["original_message"].startswith("Subtotal")


def test_outbound_verify_node_gets_the_same_parameterization():
    """Gap 223 wired the math checks into the outbound path, but they ran on
    hardcoded tolerances — so an outbound correction had nothing to act on."""
    data = {
        "customer_name": "Vertex",
        "invoice_number": "OUT-1",
        "grand_total": 25.0,
        "items": _OFF_BY_FIVE,
        "subtotal": 25.0,
        "tax_amount": 0.0,
    }
    # Gap 283: one shared verify_node now, selected by flow_direction -- without
    # the flag this would silently exercise the INBOUND profile instead.
    state = {"file_path": "mock/o.pdf", "ocr_text": "", "extracted_data": data,
             "alerts": [], "rules": None, "ocr_result": None,
             "flow_direction": "OUTBOUND"}

    before = outbound_verify_node(dict(state))
    assert any(a.get("type") == "line_item_calculation_mismatch" for a in before["alerts"])

    state["rules"] = {"constraints": [build_tolerance_rule(
        alert_type="line_item_calculation_mismatch", field="items", abs_tol=6.0, rel_tol=0.005,
    )]}
    after = outbound_verify_node(dict(state))
    assert not any(a.get("type") == "line_item_calculation_mismatch" for a in after["alerts"])


def test_legacy_free_text_rules_leave_verification_on_its_defaults():
    """A tenant with only legacy string rules must get exactly the default
    tolerances — the dual-format read must not accidentally parse prose as config."""
    rules = {"constraints": ["Tax is listed as GST not VAT for this vendor"]}
    alerts = verify_node(_inbound_state(
        extracted_data={"subtotal": 100.0, "tax_amount": 10.0, "grand_total": 130.0},
        rules=rules,
    ))["alerts"]

    tax_alert = next(a for a in alerts if a.get("type") == "tax_mismatch")
    assert tax_alert["severity"] == "error"
    assert "overridden_by_rule" not in tax_alert
