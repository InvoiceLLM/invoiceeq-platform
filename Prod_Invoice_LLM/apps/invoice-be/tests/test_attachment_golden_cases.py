"""Gap 483 (Feature 29 phase-2 P0.5) -- the 16-turn attachment probe as golden cases.

`scripts/attach_chat_eval.py` grades those turns with deterministic regexes and is kept
for ad-hoc use; `ATTACHMENT_CASES` is the same 16 turns expressed as `GoldenCase`s with
prose facts, so one live golden run can eventually cover the attachment branches.

Two copies of the same 16 questions is a drift hazard, and the drift would be silent --
the probe would go on passing while the golden copy graded a question nobody asks any
more. `test_the_golden_copy_matches_the_probe_turn_for_turn` is the guard, and it is the
reason this file exists at all.

The rest pins the things that would quietly corrupt a number:

  * the cases are NOT in `CASES`, because twelve of them need a document attached and the
    golden harness has no document-seeding step yet -- putting them on the default path
    would fail twelve turns for a reason unrelated to the model, on the run CP1's baseline
    is measured from;
  * every case has facts, and every required/forbidden line is a prose assertion rather
    than a leftover regex;
  * the figures asserted are the ones actually seeded in `region_seed_fixtures.py`, so a
    fixture edit cannot leave the reference answers quietly wrong.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmarks.agent_eval_golden_sample import ATTACHMENT_CASES, CASES
from benchmarks.region_seed_fixtures import US_TENANT_ID
from scripts.attach_chat_eval import SESSIONS

_BE_ROOT = Path(__file__).resolve().parents[1]
_FACTS = _BE_ROOT / "benchmarks" / "agent_eval_golden_facts.json"

_BY_ID = {c.case_id: c for c in ATTACHMENT_CASES}


def _probe_turns():
    """(case_id, attachment keys, intent, question) for each probe turn, in order."""
    out = []
    for session_name, _docs, turns in SESSIONS:
        for index, (keys, intent, question, _req, _forb) in enumerate(turns, 1):
            out.append((
                f"attach_{session_name.lower()}{index}",
                tuple(keys or ()),
                intent,
                question,
            ))
    return out


# --- the drift guard --------------------------------------------------------

def test_the_golden_copy_matches_the_probe_turn_for_turn():
    """The probe is the source; this list is a transcription. They must not diverge."""
    probe = _probe_turns()
    assert len(probe) == 16, f"the probe no longer has 16 turns ({len(probe)})"
    assert len(ATTACHMENT_CASES) == len(probe)
    for (case_id, keys, intent, question), case in zip(probe, ATTACHMENT_CASES):
        assert case.case_id == case_id, f"order/id drift at {case_id}"
        assert case.question == question, (
            f"{case_id}: question text differs from scripts/attach_chat_eval.py.\n"
            f"  probe : {question}\n  golden: {case.question}"
        )
        assert case.attachment_keys == keys, f"{case_id}: attachment keys differ"
        assert case.attachment_intent == intent, f"{case_id}: intent differs"


def test_the_probe_ids_the_gaps_cite_are_all_present():
    """Gaps 470/472/473/475/476 and task 29.7 cite A4, A7, B3, B4, B5 by id."""
    for case_id in ("attach_a4", "attach_a7", "attach_b3", "attach_b4", "attach_b5"):
        assert case_id in _BY_ID


# --- kept off the default path ---------------------------------------------

def test_the_attachment_cases_are_now_in_the_default_golden_set():
    """Reversed 2026-09-07 (Gap 483, founder: "Fixture loader in the harness").

    These were deliberately held OUT of `CASES` while the harness could not seed an
    attachment -- twelve of them would have run with no document and failed for a
    reason unrelated to the model, on the very run CP1's baseline is measured from.
    `run_agent_eval.py::seed_case_attachments()` now seeds them through the product's
    own extraction pipeline, so holding them back would only hide them.
    """
    ids = {c.case_id for c in CASES}
    missing = set(_BY_ID) - ids
    assert not missing, f"{missing} are not on the default golden path"


def test_twelve_need_a_document_and_four_do_not():
    with_docs = [c.case_id for c in ATTACHMENT_CASES if c.attachment_keys]
    without = [c.case_id for c in ATTACHMENT_CASES if not c.attachment_keys]
    assert len(with_docs) == 12, with_docs
    # A8, A9, B6, B7 are ordinary database questions asked in the same sessions
    assert sorted(without) == ["attach_a8", "attach_a9", "attach_b6", "attach_b7"]


def test_the_pair_branch_cases_carry_exactly_two_documents():
    """A4, A6 and B5 are the turns whose whole point is two attachments."""
    pairs = {c.case_id for c in ATTACHMENT_CASES if len(c.attachment_keys) == 2}
    assert pairs == {"attach_a4", "attach_a6", "attach_b5"}


def test_every_case_is_asked_against_the_us_benchmark_tenant():
    for case in ATTACHMENT_CASES:
        assert case.tenant_id == US_TENANT_ID, (
            f"{case.case_id} is on tenant {case.tenant_id}; the probe's figures are the US "
            f"fixtures and are wrong anywhere else"
        )


# --- facts integrity --------------------------------------------------------

@pytest.mark.parametrize("case", ATTACHMENT_CASES, ids=lambda c: c.case_id)
def test_every_case_has_required_facts_and_a_prose_reference(case):
    assert case.required_facts, f"{case.case_id} has no required facts to grade on"
    assert case.expected_answer, f"{case.case_id} has no prose reference"
    assert case.source.startswith("scripts/attach_chat_eval.py"), case.source
    assert case.why_on_file, f"{case.case_id} does not say why it is on file"


@pytest.mark.parametrize("case", ATTACHMENT_CASES, ids=lambda c: c.case_id)
def test_facts_are_prose_assertions_not_leftover_regexes(case):
    """A transcription bug that pasted the probe's regexes in would be graded as text."""
    for line in tuple(case.required_facts) + tuple(case.forbidden):
        assert line.endswith("."), f"{case.case_id}: fact is not a sentence: {line!r}"
        assert not any(tok in line for tok in (r"\d", "(?", "|r", "[r", ".*")), (
            f"{case.case_id}: fact looks like a regex: {line!r}"
        )


def test_the_facts_file_covers_every_attachment_case_and_nothing_extra():
    facts = json.loads(_FACTS.read_text(encoding="utf-8"))
    for case in ATTACHMENT_CASES:
        assert case.case_id in facts, f"{case.case_id} missing from the facts file"
        spec = facts[case.case_id]
        assert spec.get("required"), f"{case.case_id} has an empty required list"
        assert set(spec) <= {"required", "forbidden", "notes"}, spec.keys()


def test_the_turns_that_failed_on_every_model_forbid_their_known_wrong_answer():
    """The five turns Gaps 470/472/473 and task 29.7 were opened for. A `forbidden`
    line is what stops the probe's own Gap 475 weakness -- an answer passing on a
    figure quoted in the sentence that contradicts it."""
    assert any("475.20" in f for f in _BY_ID["attach_a4"].forbidden)
    assert any("counts" in f for f in _BY_ID["attach_a7"].forbidden)
    assert any("clarif" in f.lower() for f in _BY_ID["attach_b3"].forbidden)
    assert any("correct" in f for f in _BY_ID["attach_b4"].forbidden)
    assert any("Cascade" in f for f in _BY_ID["attach_b5"].forbidden)


# --- the figures match the seeded fixtures ----------------------------------

@pytest.mark.parametrize(
    "case_id, figure",
    [
        ("attach_a1", "450.00"),      # SOS-100442 grand_total
        ("attach_a4", "432.00"),      # 452.00 PO less the 20.00 credit
        ("attach_a8", "12,943.91"),   # BRL-200981 2,386.31 + TSD-620458 10,557.60
        ("attach_b4", "123.75"),      # 8.25% of RFG-500712's 1,500.00 subtotal
        ("attach_b6", "10,557.60"),   # TSD-620458 grand_total
    ],
)
def test_the_headline_figure_is_stated_in_the_required_facts(case_id, figure):
    facts = " ".join(_BY_ID[case_id].required_facts)
    assert figure in facts, f"{case_id} does not require the figure {figure}"


def test_the_asserted_totals_are_the_ones_region_seed_fixtures_actually_seeds():
    """If a fixture total is edited, these reference answers become wrong in silence."""
    src = (_BE_ROOT / "benchmarks" / "region_seed_fixtures.py").read_text(encoding="utf-8")
    for invoice_number, grand_total in (
        ("SOS-100442", "450.00"),
        ("BRL-200981", "2386.31"),
        ("RFG-500712", "1590.00"),
        ("TSD-620458", "10557.60"),
        ("IEQ-US-9001", "2500.00"),
    ):
        assert invoice_number in src, f"{invoice_number} is no longer seeded"
        assert grand_total in src, (
            f"{invoice_number}'s grand total {grand_total} is no longer in the fixtures; "
            f"the attachment golden references were written against it"
        )
