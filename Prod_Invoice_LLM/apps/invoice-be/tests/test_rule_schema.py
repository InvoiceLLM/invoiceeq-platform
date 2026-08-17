"""Feature 18: the structured rule schema and its shared normalizer.

The single highest-risk regression in this whole redesign is that a tenant's
already-committed free-text rules stop working. Every read site now goes through
`utils.rule_schema.normalize_constraints()`, so this file tests that function
hard, and then tests the real read sites end-to-end with a legacy-only template
to prove nothing downstream cares which format a rule was stored in.
"""
import pytest
from uuid import uuid4

from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool

from dependencies import MOCK_TENANT_ID
from models import ExtractionTemplate
from utils.rule_schema import (
    KIND_EXTRACTION,
    KIND_TOLERANCE,
    alert_overrides,
    apply_alert_overrides,
    build_alert_override_rule,
    build_audit_correction_rule,
    build_confidence_threshold_rule,
    build_extraction_rule,
    build_tolerance_rule,
    confidence_threshold_override,
    constraints_of,
    is_structured_rule,
    merge_constraints,
    normalize_constraints,
    render_constraint,
    rule_kind,
    rules_fingerprint,
    tolerance_overrides,
)

engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


LEGACY = "Tax is listed as GST not VAT for this vendor"


# ── The normalizer: legacy and structured must be indistinguishable ──────────

def test_legacy_string_and_structured_object_render_identically():
    """The core promise: an old string and a new object produce the same prompt line."""
    structured = build_extraction_rule(LEGACY)
    assert render_constraint(LEGACY) == render_constraint(structured) == LEGACY
    assert normalize_constraints([LEGACY]) == normalize_constraints([structured]) == [LEGACY]


def test_mixed_list_preserves_order_and_dedupes_by_rendered_text():
    structured = build_extraction_rule(LEGACY)
    mixed = [LEGACY, structured, build_extraction_rule("Second rule")]
    # The structured duplicate of LEGACY collapses, order is preserved.
    assert normalize_constraints(mixed) == [LEGACY, "Second rule"]


def test_normalizer_never_raises_on_malformed_stored_rules():
    """One tenant's corrupt template row must not break extraction for that tenant."""
    junk = [None, "", "   ", 42, {"no_text_key": True}, {"condition": "fallback text"}, [1, 2]]
    out = normalize_constraints(junk, for_prompt=False)
    # 42 stringifies, the condition-only dict falls back to its condition; nothing raises.
    assert "42" in out
    assert "fallback text" in out


def test_normalizer_tolerates_being_handed_the_whole_rules_dict():
    assert normalize_constraints({"constraints": [LEGACY]}) == [LEGACY]
    assert constraints_of({"constraints": [LEGACY]}) == [LEGACY]


def test_legacy_string_is_treated_as_an_extraction_rule():
    assert rule_kind(LEGACY) == KIND_EXTRACTION
    assert is_structured_rule(LEGACY) is False
    assert is_structured_rule(build_extraction_rule(LEGACY)) is True


# ── for_prompt filtering ─────────────────────────────────────────────────────

def test_numeric_rules_are_kept_out_of_extraction_prompts():
    """A tolerance override must never reach the extraction prompt.

    `GAP_46_VERBATIM_DIRECTIVE` exists to stop the model smoothing numbers so
    arithmetic reconciles. Telling it in the same prompt that a 5.00 gap is
    acceptable would work directly against that.
    """
    rules = [
        LEGACY,
        build_tolerance_rule(alert_type="tax_mismatch", field="tax_amount", abs_tol=5.0, rel_tol=0.01),
        build_confidence_threshold_rule(threshold=0.2),
        build_alert_override_rule(alert_type="tax_mismatch", severity="warning"),
    ]
    assert normalize_constraints(rules, for_prompt=True) == [LEGACY]
    # ...but a display surface still sees all four.
    assert len(normalize_constraints(rules, for_prompt=False)) == 4


# ── Override extraction ──────────────────────────────────────────────────────

def test_tolerance_overrides_extracted_only_for_eligible_types():
    eligible = build_tolerance_rule(
        alert_type="line_items_mismatch", field="subtotal", abs_tol=2.5, rel_tol=0.02
    )
    # Hand-built rule naming an ineligible type: must be ignored, not applied.
    ineligible = dict(eligible, source_alert_type="total_not_verified_in_source")

    out = tolerance_overrides([LEGACY, eligible, ineligible])
    assert out == {"line_items_mismatch": {"abs_tol": 2.5, "rel_tol": 0.02}}


def test_later_tolerance_rule_wins():
    first = build_tolerance_rule(alert_type="tax_mismatch", field="tax_amount", abs_tol=1.0, rel_tol=0.01)
    second = build_tolerance_rule(alert_type="tax_mismatch", field="tax_amount", abs_tol=9.0, rel_tol=0.05)
    assert tolerance_overrides([first, second])["tax_mismatch"]["abs_tol"] == 9.0


def test_confidence_threshold_rejects_out_of_range_values():
    """A threshold of 0 would disable the check entirely -- that's suppression, not
    tolerance-widening, and this flow deliberately doesn't offer it."""
    assert confidence_threshold_override([build_confidence_threshold_rule(threshold=0.25)]) == 0.25
    zero = dict(build_confidence_threshold_rule(threshold=0.25), params={"threshold": 0.0})
    assert confidence_threshold_override([zero]) is None
    over = dict(build_confidence_threshold_rule(threshold=0.25), params={"threshold": 4.0})
    assert confidence_threshold_override([over]) is None


def test_tolerance_override_with_junk_params_is_ignored_not_crashed():
    bad = dict(
        build_tolerance_rule(alert_type="tax_mismatch", field="tax_amount", abs_tol=1.0, rel_tol=0.01),
        params={"abs_tol": "not a number"},
    )
    assert tolerance_overrides([bad]) == {}


# ── Alert relabelling ────────────────────────────────────────────────────────

def test_apply_alert_overrides_relabels_and_keeps_the_original_message():
    alerts = [{"type": "tax_mismatch", "message": "computed detail", "field": "tax_amount", "severity": "error"}]
    rules = [build_alert_override_rule(
        alert_type="tax_mismatch", severity="warning", message="Known rounding quirk",
    )]
    out = apply_alert_overrides(alerts, rules)
    assert out[0]["severity"] == "warning"
    assert out[0]["message"] == "Known rounding quirk"
    # The computed text survives, so an auditor can still see what actually happened.
    assert out[0]["original_message"] == "computed detail"
    assert out[0]["overridden_by_rule"] is True
    # The input list was not mutated in place.
    assert alerts[0]["severity"] == "error"


def test_alert_override_respects_field_scoping():
    alerts = [
        {"type": "low_confidence_field", "field": "vendor_name", "severity": "warning"},
        {"type": "low_confidence_field", "field": "grand_total", "severity": "warning"},
    ]
    rules = [build_alert_override_rule(
        alert_type="low_confidence_field", field="grand_total", severity="error",
    )]
    out = apply_alert_overrides(alerts, rules)
    assert out[0]["severity"] == "warning"  # untouched, different field
    assert out[1]["severity"] == "error"


def test_apply_alert_overrides_is_a_noop_without_rules():
    alerts = [{"type": "tax_mismatch", "message": "x"}]
    assert apply_alert_overrides(alerts, [LEGACY]) is alerts
    assert alert_overrides([LEGACY]) == []


# ── Merge + fingerprint ──────────────────────────────────────────────────────

def test_merge_dedupes_a_structured_rule_against_an_identical_legacy_string():
    """Before Feature 18 this de-duplicated by object identity, so a structured
    rule rendering to an existing sentence would have been applied twice."""
    merged = merge_constraints([LEGACY], [build_extraction_rule(LEGACY), build_extraction_rule("New")])
    assert normalize_constraints(merged) == [LEGACY, "New"]


def test_fingerprint_is_stable_and_changes_when_rules_change():
    rules = [LEGACY, build_extraction_rule("Second")]
    assert rules_fingerprint(rules) == rules_fingerprint(list(rules))
    assert rules_fingerprint(rules) != rules_fingerprint(rules + ["Third"])


def test_audit_correction_rule_text_is_unchanged_from_the_pre_feature_18_sentence():
    """routers/audit.py emitted this exact sentence as a bare string. The prompt the
    model sees must be byte-identical now that it is wrapped in an object."""
    rule = build_audit_correction_rule(field="grand_total", new_value=150.0, old_value=100.0)
    assert render_constraint(rule) == "For grand total, extract the value as 150.0, not 100.0."
    assert rule["field"] == "grand_total"
    assert rule["params"] == {"new_value": 150.0, "old_value": 100.0}


# ── Real read sites, with a LEGACY-ONLY template (the regression that matters) ─

def test_legacy_only_template_still_reaches_every_read_site(db_session):
    """End-to-end: a tenant who has only ever committed free-text rules sees them
    applied in extraction, in the worker's two-stage resolution, and in Chat."""
    from agents.extraction_agent import build_multimodal_prompt
    from agents.outbound_extraction_agent import build_outbound_multimodal_prompt
    from agents.query_agent import _get_global_business_rules, _get_vendor_business_rules
    from queue_worker.handlers import _get_template_rules, _merge_constraints

    db_session.add(ExtractionTemplate(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, vendor_name=None, flow_direction="INBOUND",
        rules={"constraints": [LEGACY]}, version=1,
    ))
    db_session.add(ExtractionTemplate(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, vendor_name="ACME Corporation", flow_direction="INBOUND",
        rules={"constraints": ["Vendor legacy rule"]}, version=1,
    ))
    db_session.commit()

    # Chat prompt injection (query_agent)
    assert _get_global_business_rules(str(MOCK_TENANT_ID), db_session) == [LEGACY]
    assert _get_vendor_business_rules(
        str(MOCK_TENANT_ID), "what did we pay acme corporation", db_session
    ) == ["Vendor legacy rule"]

    # Worker two-stage rule resolution
    global_rules = _get_template_rules(db_session, str(MOCK_TENANT_ID), None)
    vendor_rules = _get_template_rules(db_session, str(MOCK_TENANT_ID), "ACME Corporation")
    assert global_rules == [LEGACY]
    assert _merge_constraints(global_rules, vendor_rules) == [LEGACY, "Vendor legacy rule"]

    # Both extraction prompt builders
    inbound = build_multimodal_prompt("ocr", [], {"constraints": [LEGACY]})
    assert LEGACY in inbound[0].content[0]["text"]
    outbound = build_outbound_multimodal_prompt("ocr", [], {"constraints": [LEGACY]})
    assert LEGACY in outbound[0].content[0]["text"]


def test_mixed_legacy_and_structured_template_renders_both_in_the_prompt(db_session):
    from agents.extraction_agent import build_multimodal_prompt

    rules = {"constraints": [LEGACY, build_extraction_rule("Structured rule")]}
    prompt = build_multimodal_prompt("ocr text", [], rules)[0].content[0]["text"]
    assert LEGACY in prompt
    assert "Structured rule" in prompt
