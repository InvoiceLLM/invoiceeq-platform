"""Tests for Feature 23 Track 1's harness — not for the fixtures it contains.

The distinction matters. A test asserting "the clean US invoice totals 5,517.23"
would only restate `documents.py`, and would pass just as happily if the whole
measurement were wrong. What is worth testing is the machinery that turns a
corpus into a number, because that is what a reader has to trust when the
benchmark reports 100% recall:

  * the clean documents really are internally consistent — asserted by running
    the **real** `verify_node` over them and requiring silence, not by
    re-deriving the arithmetic here;
  * a mutation really changed what the manifest says it changed, and only that;
  * the scorer counts a hit only for the expected alert type;
  * a not-applicable case is excluded from the recall denominator rather than
    counted as a miss;
  * the field comparator's normalisations accept what should be accepted and
    still reject a genuinely wrong value.

Nothing here calls a model. Every test runs in verify mode.
"""

from __future__ import annotations

import dataclasses
import json
import os

import pytest

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

# benchmarks.extraction is the harness under test, moved out of tests/ on
# 2026-08-23 so scripts/run_extraction_benchmark.py can import it inside a
# deployed container (`.dockerignore` excludes `**/tests/`).
from benchmarks.extraction.artifacts import (
    build_manifest,
    render_manifest_markdown,
    render_run_markdown,
    summarise,
    write_corpus_artifacts,
    write_run_artifacts,
)
from benchmarks.extraction.documents import CLEAN_BY_ID, CLEAN_DOCUMENTS
from benchmarks.extraction.harness import (
    MODE_LIVE,
    MODE_VERIFY,
    run_benchmark,
    run_clean_case,
    run_seeded_case,
    score_clean_run,
    score_seeded_run,
)
from benchmarks.extraction.metrics import (
    CleanOutcome,
    build_confusion,
    compare_fields,
    field_accuracy,
    recall_by_alert_type,
    score_seeded,
    values_match,
)
from benchmarks.extraction.mutations import (
    MUTATION_ABS_FLOOR,
    MUTATION_REL,
    SeededCase,
    _replace_money_in_text,
    build_seeded_cases,
    ocr_result_for,
)

SEEDED = build_seeded_cases()
SEEDED_BY_ID = {case.case_id: case for case in SEEDED}


# ---------------------------------------------------------------------------
# The clean corpus really is clean
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spec", CLEAN_DOCUMENTS, ids=lambda s: s.doc_id)
def test_every_ground_truth_figure_is_printed_in_the_document(spec):
    """A ground-truth number the document never prints would make the five
    source-text faithfulness checks fire on a *clean* case, which would make the
    false-positive rate a property of the fixture rather than of the product."""
    text = spec.render_ocr_text()
    figures = [spec.subtotal, spec.grand_total] + [line.amount for line in spec.lines]
    figures += [line.unit_price for line in spec.lines]
    if spec.tax_amount:
        # A split-tax invoice never prints the summed figure; its components must
        # each be printed instead (Gap 69's component fallback).
        if spec.taxes and len(spec.taxes) > 1:
            figures += [t.amount for t in spec.taxes]
        else:
            figures.append(spec.tax_amount)
    for value in figures:
        assert f"{value:,.2f}" in text, f"{value:,.2f} is in the ground truth but not the document"


@pytest.mark.parametrize("spec", CLEAN_DOCUMENTS, ids=lambda s: s.doc_id)
def test_clean_documents_are_arithmetically_consistent(spec):
    assert sum(line.amount for line in spec.lines) == pytest.approx(spec.subtotal, abs=0.01)
    for line in spec.lines:
        assert line.quantity * line.unit_price == pytest.approx(line.amount, abs=0.01)
    discount = spec.discount_amount or 0.0
    expected = spec.subtotal - discount + spec.tax_amount + (spec.round_off or 0.0)
    assert expected == pytest.approx(spec.grand_total, abs=0.01)
    if spec.taxes:
        assert sum(t.amount for t in spec.taxes) == pytest.approx(spec.tax_amount, abs=0.01)


def test_clean_inbound_documents_raise_no_alert_through_the_real_verify_node():
    """The false-positive measurement, asserted as a floor.

    Scoped to INBOUND: `outbound_trade_discount` is a known, deliberately-kept
    false positive (`OutboundInvoiceExtractionSchema` carries no discount field,
    so a discounted outbound invoice cannot pass `verify_totals_math`) and has
    its own test below. Pinning it here would either hide the defect or force
    this test to be edited when it is fixed.
    """
    for spec in CLEAN_DOCUMENTS:
        if spec.flow_direction != "INBOUND":
            continue
        run = run_clean_case(spec, MODE_VERIFY)
        assert run.error is None
        assert run.fired_types == [], f"{spec.doc_id} raised {run.fired_types}"
        assert run.status == "COMPLETED"


def test_known_outbound_discount_false_positive_is_still_present():
    """Pins the defect the first benchmark run found, so a fix is visible.

    If this starts failing, `OutboundInvoiceExtractionSchema` has gained a
    discount field (or `verify_totals_math` learned to infer one) — update the
    README's 'What the first run found' section and delete this test rather than
    editing it to match.
    """
    spec = CLEAN_BY_ID["outbound_trade_discount"]
    run = run_clean_case(spec, MODE_VERIFY)
    assert run.fired_types == ["tax_mismatch"]
    assert spec.discount_amount is not None
    assert "discount_amount" not in spec.initial_extraction()


# ---------------------------------------------------------------------------
# Mutations change what they claim to change, and only that
# ---------------------------------------------------------------------------


def test_seeded_case_ids_are_unique():
    ids = [case.case_id for case in SEEDED]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("case", SEEDED, ids=lambda c: c.case_id)
def test_mutation_actually_changed_something(case):
    """A mutator that silently no-ops would be recorded in the review manifest
    as if it had happened — the single worst failure this corpus could have."""
    spec = CLEAN_BY_ID[case.doc_id]
    clean_text = spec.render_ocr_text()
    clean_data = spec.initial_extraction()
    if case.surface == "document":
        assert case.ocr_text != clean_text, "document-surface mutation left the text untouched"
    else:
        assert case.ocr_text == clean_text, "extraction-surface mutation must not touch the text"
        assert case.extracted_data != clean_data or ocr_result_for(case) is not None


@pytest.mark.parametrize("case", SEEDED, ids=lambda c: c.case_id)
def test_manifest_correct_value_matches_the_clean_document(case):
    """`correct_value` must be the clean document's real value, not a retyped
    copy that could drift from it."""
    spec = CLEAN_BY_ID[case.doc_id]
    path = case.field_path
    if path.startswith("ocr_result."):
        pytest.skip("confidence case: the correct value is a Doc Intelligence score, not a field")
    if path.startswith("items["):
        idx = int(path[len("items[") : path.index("]")])
        attr = path.rsplit(".", 1)[1]
        assert getattr(spec.lines[idx], attr) == case.correct_value
    elif path in ("customer_name", "vendor_name"):
        assert spec.party_name == case.correct_value
    else:
        assert getattr(spec, path) == case.correct_value


@pytest.mark.parametrize("case", SEEDED, ids=lambda c: c.case_id)
def test_planted_value_differs_from_correct_value(case):
    assert case.planted_value != case.correct_value


@pytest.mark.parametrize(
    "case",
    [c for c in SEEDED if c.surface == "document" and c.field_path != "customer_name"],
    ids=lambda c: c.case_id,
)
def test_document_mutations_change_exactly_one_line(case):
    spec = CLEAN_BY_ID[case.doc_id]
    clean_lines = spec.render_ocr_text().splitlines()
    seeded_lines = case.ocr_text.splitlines()
    assert len(clean_lines) == len(seeded_lines)
    differing = [i for i, (a, b) in enumerate(zip(clean_lines, seeded_lines)) if a != b]
    assert len(differing) == 1, f"expected one changed line, got {differing}"


@pytest.mark.parametrize(
    "case",
    [c for c in SEEDED if c.surface == "document" and c.field_path.startswith(("grand_total", "subtotal", "items["))],
    ids=lambda c: c.case_id,
)
def test_arithmetic_mutations_clear_the_verification_tolerance(case):
    """`verify_*_math` accepts max(0.01, 0.5% relative). A mutation inside that
    band would be a legitimately-undetectable miss reported as a product failure."""
    from utils.verification_tools import REL_TOLERANCE

    delta = abs(float(case.planted_value) - float(case.correct_value))
    assert delta > max(0.01, abs(float(case.correct_value)) * REL_TOLERANCE)
    assert delta == pytest.approx(
        max(abs(float(case.correct_value)) * MUTATION_REL, MUTATION_ABS_FLOOR), abs=0.01
    )


def test_replace_money_refuses_a_target_it_cannot_find():
    with pytest.raises(ValueError):
        _replace_money_in_text("Subtotal: 100.00", 999.00, 1.00, on_line_with="Subtotal")


def test_replace_money_refuses_an_ambiguous_target():
    """The zero-VAT document prints the same figure as subtotal and as total.
    A whole-text replace would mutate both and the manifest would be wrong."""
    text = "Subtotal: EUR 18,170.00\nTOTAL DUE: EUR 18,170.00"
    with pytest.raises(ValueError):
        _replace_money_in_text(text, 18170.00, 17000.00, on_line_with="EUR")
    # Scoped to one line, it succeeds and leaves the other alone.
    out = _replace_money_in_text(text, 18170.00, 17000.00, on_line_with="Subtotal:")
    assert out.splitlines()[0] == "Subtotal: EUR 17,000.00"
    assert out.splitlines()[1] == "TOTAL DUE: EUR 18,170.00"


def test_seeded_corpus_is_deterministic():
    first = [(c.case_id, c.ocr_text, json.dumps(c.extracted_data, sort_keys=True, default=str)) for c in build_seeded_cases()]
    second = [(c.case_id, c.ocr_text, json.dumps(c.extracted_data, sort_keys=True, default=str)) for c in build_seeded_cases()]
    assert first == second


# ---------------------------------------------------------------------------
# The seeded cases really do trip the check they name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", SEEDED, ids=lambda c: c.case_id)
def test_every_seeded_case_fires_its_expected_alert_in_verify_mode(case):
    run = run_seeded_case(case, MODE_VERIFY)
    assert run.error is None
    assert case.expected_alert_type in run.fired_types, (
        f"{case.case_id}: expected {case.expected_alert_type}, fired {run.fired_types}"
    )


@pytest.mark.parametrize("case", SEEDED, ids=lambda c: c.case_id)
def test_no_seeded_case_fires_an_undeclared_alert_type(case):
    """Every alert a case raises must be either the expected type or a declared
    tolerated side effect. An undeclared one means the manifest under-describes
    what the case actually does."""
    run = run_seeded_case(case, MODE_VERIFY)
    outcome = score_seeded_run(case, run, MODE_VERIFY)
    assert outcome.collateral == [], f"{case.case_id} fired undeclared {outcome.collateral}"


def test_a_wrong_alert_type_is_not_a_hit():
    """The property that makes recall meaningful: a pipeline that raised
    `tax_mismatch` on everything must not score 100%."""
    outcome = score_seeded("c", "missing_required_field", (), ["tax_mismatch"])
    assert outcome.hit is False
    assert outcome.collateral == ["tax_mismatch"]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_not_applicable_cases_leave_the_recall_denominator():
    case = SEEDED_BY_ID["us_flat_sales_tax__tax_silently_corrected"]
    assert case.gradeable_live is False
    run = run_seeded_case(case, MODE_VERIFY)
    live_outcome = score_seeded_run(case, run, MODE_LIVE)
    assert live_outcome.not_applicable is True
    matrix = build_confusion([], [live_outcome])
    assert matrix.not_applicable == 1
    assert matrix.recall is None  # nothing gradeable -> no number, not 0.0


def test_confusion_matrix_arithmetic():
    clean = [
        CleanOutcome("a", [], false_positive=False),
        CleanOutcome("b", ["tax_mismatch"], false_positive=True),
    ]
    seeded = [
        score_seeded("s1", "tax_mismatch", (), ["tax_mismatch"]),
        score_seeded("s2", "line_items_mismatch", (), []),
        score_seeded("s3", "tax_mismatch", (), ["tax_mismatch"]),
    ]
    matrix = build_confusion(clean, seeded)
    assert (matrix.true_positive, matrix.false_negative) == (2, 1)
    assert (matrix.false_positive, matrix.true_negative) == (1, 1)
    assert matrix.recall == pytest.approx(2 / 3)
    assert matrix.false_positive_rate == pytest.approx(0.5)
    assert matrix.precision == pytest.approx(2 / 3)


def test_empty_denominators_report_none_not_zero():
    """An empty window must never read as a healthy one — the same rule
    `services/online_eval_signals.py` follows."""
    matrix = build_confusion([], [])
    assert matrix.recall is None
    assert matrix.false_positive_rate is None
    assert matrix.precision is None


def test_recall_by_alert_type_names_the_missed_case():
    seeded = [
        score_seeded("s1", "tax_mismatch", (), ["tax_mismatch"]),
        score_seeded("s2", "tax_mismatch", (), []),
    ]
    buckets = recall_by_alert_type(seeded)
    assert buckets["tax_mismatch"]["seeded"] == 2
    assert buckets["tax_mismatch"]["detected"] == 1
    assert buckets["tax_mismatch"]["recall"] == pytest.approx(0.5)
    assert buckets["tax_mismatch"]["missed_cases"] == ["s2"]


# ---------------------------------------------------------------------------
# Field comparison
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "field_name,expected,actual,should_match",
    [
        ("grand_total", 5085.0, 5085, True),
        ("grand_total", 5085.0, "5085.00", True),
        ("grand_total", 5085.0, 5085.02, False),
        ("invoice_date", "2026-07-14", "14/07/2026", True),
        ("invoice_date", "2026-07-14", "2026-07-15", False),
        ("vendor_name", "Cascade Industrial Supply LLC", "cascade industrial supply", True),
        ("vendor_name", "Cascade Industrial Supply LLC", "Cascade Industrial", False),
        ("currency", "USD", "usd", True),
        ("po_number", None, None, True),
        ("po_number", None, "PO-1", False),
        ("po_number", "PO-1", None, False),
    ],
)
def test_values_match(field_name, expected, actual, should_match):
    assert values_match(field_name, expected, actual) is should_match


def test_a_dropped_line_item_costs_every_field_of_that_line():
    truth = {
        "grand_total": 100.0,
        "items": [
            {"description": "A", "quantity": 1, "unit_price": 50.0, "amount": 50.0},
            {"description": "B", "quantity": 1, "unit_price": 50.0, "amount": 50.0},
        ],
    }
    extracted = {"grand_total": 100.0, "items": [truth["items"][0]]}
    comparisons = compare_fields(truth, extracted)
    correct, total, _ = field_accuracy(comparisons)
    assert total == 1 + 2 * 4
    assert correct == 1 + 4  # grand_total plus line A's four fields


def test_line_items_are_matched_by_description_not_position():
    truth = {
        "items": [
            {"description": "Bolts", "quantity": 1, "unit_price": 2.0, "amount": 2.0},
            {"description": "Angle", "quantity": 1, "unit_price": 3.0, "amount": 3.0},
        ]
    }
    reordered = {"items": list(reversed(truth["items"]))}
    correct, total, ratio = field_accuracy(compare_fields(truth, reordered))
    assert ratio == 1.0 and correct == total == 8


def test_a_failed_extraction_is_scored_as_all_fields_missed():
    """Not skipped. A harness that dropped failed extractions would report its
    best accuracy on the day the model stopped responding."""
    truth = {"grand_total": 100.0, "items": [{"description": "A", "quantity": 1, "unit_price": 1.0, "amount": 1.0}]}
    correct, total, ratio = field_accuracy(compare_fields(truth, None))
    assert correct == 0 and total == 5 and ratio == 0.0


def test_verify_mode_does_not_report_a_field_accuracy_figure():
    """Verify mode is handed the extraction it would be grading, so any figure
    would be a guaranteed 100% that measures nothing."""
    spec = CLEAN_BY_ID["us_flat_sales_tax"]
    outcome = score_clean_run(spec, run_clean_case(spec, MODE_VERIFY), MODE_VERIFY)
    assert (outcome.field_correct, outcome.field_total) == (0, 0)


# ---------------------------------------------------------------------------
# End to end + artifacts
# ---------------------------------------------------------------------------


def test_full_verify_run_detects_every_seeded_issue():
    result = run_benchmark(mode=MODE_VERIFY)
    summary = summarise(result)
    matrix = summary["confusion_matrix"]
    assert matrix["false_negative"] == 0
    assert matrix["recall"] == 1.0
    assert matrix["true_positive"] == len(SEEDED)
    # The one known false positive, pinned by name so a regression that adds a
    # second one fails here rather than passing a >= assertion.
    assert [e["case_id"] for e in summary["false_positive_documents"]] == [
        "outbound_trade_discount__clean"
    ]
    assert summary["errors"] == []


def test_case_filter_restricts_the_run():
    result = run_benchmark(mode=MODE_VERIFY, case_ids={"us_flat_sales_tax__clean"})
    assert len(result.clean_runs) == 1
    assert result.seeded_runs == []


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        run_benchmark(mode="pretend")


def test_manifest_covers_every_case_and_carries_the_review_fields():
    manifest = build_manifest()
    assert len(manifest["clean_documents"]) == len(CLEAN_DOCUMENTS)
    assert len(manifest["seeded_cases"]) == len(SEEDED)
    for entry in manifest["seeded_cases"]:
        # The four questions the review artifact has to answer.
        assert entry["field_path"]
        assert entry["expected_alert_type"]
        assert entry["rationale"]
        assert "correct_value" in entry and "planted_value" in entry
        assert entry["mutated_ocr_text"]
    json.dumps(manifest)  # must be serialisable as written


def test_manifest_markdown_names_every_case():
    text = render_manifest_markdown(build_manifest())
    for case in SEEDED:
        assert case.case_id in text
        assert case.expected_alert_type in text


def test_artifacts_write_under_a_tmp_root(tmp_path):
    written = write_corpus_artifacts(tmp_path)
    assert (tmp_path / "case_manifest.json").exists()
    assert (tmp_path / "case_manifest.md").exists()
    assert len(list((tmp_path / "documents").glob("*.txt"))) == len(CLEAN_DOCUMENTS) + len(SEEDED)
    assert len(written) == 2 + len(CLEAN_DOCUMENTS) + len(SEEDED)

    result = run_benchmark(mode=MODE_VERIFY, case_ids={"us_flat_sales_tax__clean"})
    run_written = write_run_artifacts(result, tmp_path)
    assert (tmp_path / "runs" / "verify-latest.md").exists()
    assert len(run_written) == 2
    text = render_run_markdown(summarise(result), result)
    assert "Confusion matrix" in text


def test_regenerating_the_corpus_is_byte_identical(tmp_path):
    write_corpus_artifacts(tmp_path / "a")
    write_corpus_artifacts(tmp_path / "b")
    for name in ("case_manifest.md",):
        assert (tmp_path / "a" / name).read_text(encoding="utf-8") == (
            tmp_path / "b" / name
        ).read_text(encoding="utf-8")
    for doc in (tmp_path / "a" / "documents").glob("*.txt"):
        assert doc.read_text(encoding="utf-8") == (
            tmp_path / "b" / "documents" / doc.name
        ).read_text(encoding="utf-8")


def test_verify_mode_never_short_circuits_on_the_legacy_audit_path():
    """`verify_node` returns a single bare-string alert and skips every check
    when an INBOUND `file_path` contains 'audit'. If the harness ever generated
    such a path, every case would silently become one meaningless alert."""
    spec = CLEAN_BY_ID["us_flat_sales_tax"]
    run = run_clean_case(spec, MODE_VERIFY)
    assert "legacy_string_alert" not in run.fired_types


def test_seeded_case_dataclass_reports_live_gradeability_from_surface():
    document = SeededCase(
        case_id="x", doc_id="d", mutation="m", surface="document",
        expected_alert_type="tax_mismatch", tolerated_alert_types=(), field_path="f",
        correct_value=1, planted_value=2, rationale="r", ocr_text="t",
        extracted_data={}, flow_direction="INBOUND",
    )
    assert document.gradeable_live is True
    assert dataclasses.replace(document, surface="extraction").gradeable_live is False
