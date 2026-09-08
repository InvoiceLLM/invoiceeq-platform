"""Gap 486 (Feature 29 phase-2 P1.4/P1.5) -- the long-document fixtures and their cases.

Task 29.10 decides a permanent model role (Luna or Terra as `long_doc`) on a 2-point rule.
That decision is only as good as the fixtures, and the previous attempt at it was blocked
precisely because the eight probe documents are single-page and ~2 KB -- at that length
Luna and Terra both score whatever the agent logic scores, so the comparison measures
nothing about long-context recall.

So the tests here are not about parsing. They are about whether these fixtures can still
tell the two models apart:

  1. Every document clears its `min_pages` floor. A fixture that shrinks stops
     discriminating while continuing to pass every other test in this file.
  2. The decisive fact is never on page 1. That is the whole mechanism.
  3. The contract's decoy is present and is a DIFFERENT percentage from the answer --
     without it, "find a percentage" succeeds without any recall at all.
  4. Ground truth is derived from the fixture data, not transcribed beside it. Each
     assertion re-derives the figure from the module and compares, so a fixture edit that
     moved a number without moving the expected answer fails here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from benchmarks.long_doc_fixtures import (
    CONTRACT,
    DELIVERY_NOTE,
    LONG_DOCS,
    LONG_DOCS_BY_KEY,
    PO_ALPHA,
    PO_BETA,
    STATEMENT,
    page_layout,
    page_of,
)

_GOLDEN = Path(__file__).resolve().parents[1] / "tests" / "golden_long_doc.json"
_DOC = json.loads(_GOLDEN.read_text(encoding="utf-8"))
_CASES = _DOC["cases"]
_BY_ID = {c["case_id"]: c for c in _CASES}


# --- 1/2: they are long, and the fact is buried -----------------------------

@pytest.mark.parametrize("doc", LONG_DOCS, ids=lambda d: d.key)
def test_each_document_clears_its_page_floor(doc):
    pages = len(page_layout(doc))
    assert pages >= doc.min_pages, (
        f"{doc.key} is {pages} pages against a floor of {doc.min_pages}; it has shrunk "
        f"and no longer measures long-context recall"
    )


@pytest.mark.parametrize("doc", LONG_DOCS, ids=lambda d: d.key)
def test_the_decisive_fact_is_present_and_never_on_page_one(doc):
    page = page_of(doc, doc.buried_fact)
    assert page is not None, f"{doc.key}: buried fact {doc.buried_fact!r} is not in the document"
    assert page > 1, (
        f"{doc.key}: the decisive fact is on page 1, so a model that reads only the "
        f"first page answers it correctly and the fixture discriminates nothing"
    )


def test_all_five_documents_exist_and_are_distinct():
    assert len(LONG_DOCS) == 5
    assert len({d.key for d in LONG_DOCS}) == 5
    # the five types task 29.10 names
    assert {d.doc_type for d in LONG_DOCS} == {
        "CONTRACT", "STATEMENT", "PURCHASE_ORDER", "DELIVERY_NOTE"
    }
    assert sum(1 for d in LONG_DOCS if d.doc_type == "PURCHASE_ORDER") == 2


# --- 3: the contract's decoy --------------------------------------------------

def test_the_contract_carries_a_decoy_percentage_earlier_than_the_answer():
    answer_page = page_of(CONTRACT, "1.5% per month")
    decoy_page = page_of(CONTRACT, "2.0%")
    assert decoy_page is not None, "the decoy percentage is gone; the case is now trivial"
    assert decoy_page < answer_page, (
        "the decoy must come BEFORE the answer, or 'take the first percentage' succeeds"
    )
    assert "2.0%" != "1.5%"


def test_the_contract_states_the_late_fee_exactly_once():
    body = "\n".join(line for page in page_layout(CONTRACT) for line in page)
    assert body.count("1.5% per month") == 1, "the answer appears more than once"


# --- 4: ground truth is derived, not transcribed ----------------------------

def test_statement_ground_truth_matches_the_rendered_document():
    gt = STATEMENT.ground_truth
    body = "\n".join(line for page in page_layout(STATEMENT) for line in page)
    assert gt["unmatched_invoice"] in body
    assert gt["first_invoice"] in body and gt["last_invoice"] in body
    # exactly `line_count` invoice rows were rendered
    assert len(re.findall(r"BRL-\d{6}", body)) == gt["line_count"]


def test_po_outlier_is_really_an_outlier_in_the_rendered_document():
    gt = PO_ALPHA.ground_truth
    body = "\n".join(line for page in page_layout(PO_ALPHA) for line in page)
    assert gt["outlier_unit_price"] in body
    low, high = (float(x) for x in gt["typical_unit_price_range"].split(" to "))
    assert float(gt["outlier_unit_price"].replace(",", "")) > high * 5, (
        "the outlier is not far enough from the other lines to be findable"
    )


def test_delivery_note_shortfalls_are_the_lines_the_ground_truth_names():
    gt = DELIVERY_NOTE.ground_truth
    short = []
    for row in DELIVERY_NOTE.rows:
        m = re.search(r"^\s*(\d+)\s+.*ordered\s+(\d+)\s+delivered\s+(\d+)", row)
        assert m, row
        line, ordered, delivered = (int(m.group(i)) for i in (1, 2, 3))
        if ordered != delivered:
            short.append(line)
            assert ordered - delivered == gt["shortfall_per_line"]
    assert short == gt["short_shipped_lines"]
    assert len(short) == gt["short_shipped_count"]


def test_po_beta_states_its_delivery_term_in_the_footer():
    assert any("NOT permitted" in line for line in PO_BETA.footer)
    assert PO_BETA.ground_truth["partial_shipments_allowed"] is False


# --- the golden cases -------------------------------------------------------

def test_there_are_five_cases_one_per_document():
    assert len(_CASES) == 5
    keys = [k for c in _CASES for k in c["attachment_keys"]]
    assert sorted(keys) == sorted(LONG_DOCS_BY_KEY)


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c["case_id"])
def test_every_case_is_complete_and_points_at_a_real_fixture(case):
    for key in ("case_id", "question", "expected_answer", "why_on_file"):
        assert case.get(key), f"{case['case_id']} is missing {key}"
    assert case["required"], f"{case['case_id']} has nothing to grade on"
    assert case["forbidden"], f"{case['case_id']} has no wrong answer defined"
    for key in case["attachment_keys"]:
        assert key in LONG_DOCS_BY_KEY, f"unknown fixture {key}"
    assert case["attachment_intent"] in {"read", "compare", "reconcile"}


@pytest.mark.parametrize("case", _CASES, ids=lambda c: c["case_id"])
def test_facts_are_prose_sentences_not_regexes(case):
    for line in case["required"] + case["forbidden"]:
        assert line.endswith("."), f"{case['case_id']}: not a sentence: {line!r}"
        assert not any(tok in line for tok in (r"\d", "(?", ".*", "|r")), line


def test_the_expected_figures_are_the_fixtures_own_figures():
    """The transcription guard: every headline figure in a case must be the one the
    fixture module derives, so a fixture edit cannot leave a case grading a stale number."""
    contract = CONTRACT.ground_truth
    assert contract["late_payment_interest"] in _BY_ID["long_doc_contract_late_fee"]["expected_answer"]
    assert contract["late_payment_clause"] in _BY_ID["long_doc_contract_late_fee"]["expected_answer"]

    statement = STATEMENT.ground_truth
    assert statement["unmatched_invoice"] in _BY_ID["long_doc_statement_unmatched_line"]["expected_answer"]

    po = PO_ALPHA.ground_truth
    outlier_case = _BY_ID["long_doc_po_outlier_line"]
    assert po["outlier_unit_price"] in outlier_case["expected_answer"]
    assert str(po["outlier_line"]) in outlier_case["expected_answer"]

    dn = DELIVERY_NOTE.ground_truth
    shortfall_case = _BY_ID["long_doc_delivery_shortfall"]
    for line in dn["short_shipped_lines"]:
        assert any(str(line) in fact for fact in shortfall_case["required"]), (
            f"short-shipped line {line} is not required by the case"
        )


def test_the_file_records_that_a_founder_spot_check_is_owed():
    """Task 29.10's role decision rests on figures this session authored."""
    assert "OWED" in _DOC["_founder_spot_check"]
    assert _DOC["_generated_from"] == "benchmarks/long_doc_fixtures.py"
