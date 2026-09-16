"""BE Gap 535: the arithmetic re-check after a correction (utils/correction_recheck.py). Pure functions, no database."""
from utils.correction_recheck import alerts_raised_by_correction
from utils.rule_schema import KIND_TOLERANCE

BALANCED = {
    "items": [{"description": "Widget", "amount": 500.0}],
    "subtotal": 500.0,
    "tax_amount": 20.0,
    "grand_total": 520.0,
    "discount_amount": None,
    "discount_percent": None,
}


def _raised(before, after, rules=None, open_alerts=()):
    return alerts_raised_by_correction(before, after, rules=rules, doc_type=None, open_alerts=list(open_alerts))


def test_breaking_the_totals_raises_a_tax_mismatch_marked_as_raised_by_the_correction():
    raised = _raised(BALANCED, {**BALANCED, "grand_total": 100.0})
    assert [(a["type"], a["field"], a["raised_by"]) for a in raised] == [("tax_mismatch", "tax_amount", "correction")]


def test_moving_the_line_items_away_from_the_subtotal_raises_a_line_items_mismatch():
    raised = _raised(BALANCED, {**BALANCED, "items": [{"description": "Widget", "amount": 450.0}]})
    assert [a["type"] for a in raised] == ["line_items_mismatch"]


def test_a_discount_that_explains_the_total_raises_nothing():
    assert _raised(BALANCED, {**BALANCED, "discount_amount": 20.0, "grand_total": 500.0}) == []


def test_a_check_already_failing_before_the_correction_is_not_raised_again():
    off = {**BALANCED, "grand_total": 540.0}
    assert _raised(off, {**off, "tax_amount": 25.0}) == []


def test_an_identical_open_alert_is_not_duplicated():
    after = {**BALANCED, "grand_total": 100.0}
    first = _raised(BALANCED, after)
    assert _raised(BALANCED, after, open_alerts=first) == []


def test_the_tenants_tolerance_override_is_respected():
    rules = {"constraints": [{"kind": KIND_TOLERANCE, "source_alert_type": "tax_mismatch", "params": {"abs_tol": 50}}]}
    assert _raised(BALANCED, {**BALANCED, "grand_total": 560.0}, rules=rules) == []
    assert [a["type"] for a in _raised(BALANCED, {**BALANCED, "grand_total": 560.0})] == ["tax_mismatch"]
