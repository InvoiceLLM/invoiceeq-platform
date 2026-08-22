"""Feature 23 — tests for `scripts/seed_golden_bank.py`.

Deliberately hermetic. Every real source this script reads
(`tests/{us,india,eu,realworld_tenant}/`) is **gitignored**, so a test that
asserted against the real files would pass on this machine and fail on any
checkout that does not happen to have the local scratch dirs. The fixtures below
are short excerpts reproducing each real format *exactly* — including the
inconsistencies the parser has to survive: the `(follow-up on Qn)` annotation,
the `Matching:`/`Computation:` two-line answer form, the escaped pipes inside
`live_test_results.md` table cells, and the two different `raw_turns_*.json`
shapes.

The one non-hermetic test (`test_build_fixture_produces_the_documented_shape`)
asserts structure only, never counts, so it is meaningful with or without the
gitignored directories present.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.seed_golden_bank import (
    KIND_EXPECTED_ENTITIES,
    KIND_NONE,
    KIND_OBSERVED_POST_FIX,
    KIND_REFERENCE_ANSWER,
    GoldenBankCase,
    attach_live_verdicts,
    build_coverage,
    build_fixture,
    deduplicate,
    extract_gap_numbers,
    parse_live_test_results,
    parse_question_bank,
    parse_test_evidence,
    summarise,
    tracker_gap_index,
)

# ---------------------------------------------------------------------------
# Format 1 — chat_question_bank.md
# ---------------------------------------------------------------------------

BANK_MD = """# Chat Question Bank -- Autoloop Test Tenant: US (tenant-us)

Tenant: Infinevo Cloud Inc. 6 inbound invoices, 3 outbound invoices.

---

## Grading Rubric

- Required to pass: the correct number/entity.

---

## Session 1 -- Tier 1: simple, single-filter lookups

Q1. What is the total on the invoice from Summit Office Supplies, SOS-100442?
Answer: $450.00 (10 laptop stands at $45.00 each, no sales tax charged).

Q4 (reconciliation check, required not bonus). Does the Apex Print Solutions invoice, APS-410093, reconcile quantity times unit price against the printed amount?
Answer: No. 5,000 x $0.08 = $400.00 true math, but the printed line Amount and
Subtotal are both $420.00, a $20.00 discrepancy.

---

## Session 3 -- Tier 3/4: cross-invoice math

Q11. Across Summit Office Supplies and Blue Ridge Logistics, what is the combined grand total?
Matching: $450.00 + $2,386.31.
Computation: 450.00 + 2,386.31 = $2,836.31.

Q12 (follow-up on Q11). And how much of that combined total is sales tax?
Matching: Summit $0.00 + Blue Ridge $161.31.
Computation: $161.31.
"""


@pytest.fixture
def bank_path(tmp_path: Path) -> Path:
    path = tmp_path / "chat_question_bank.md"
    path.write_text(BANK_MD, encoding="utf-8")
    return path


def test_question_bank_yields_one_case_per_question(bank_path):
    cases = parse_question_bank(bank_path, "us")
    assert [case.turn_index for case in cases] == [1, 4, 11, 12]
    assert all(case.tenant == "us" for case in cases)
    assert all(case.expectation_kind == KIND_REFERENCE_ANSWER for case in cases)


def test_annotated_question_keeps_the_question_not_the_annotation(bank_path):
    case = next(c for c in parse_question_bank(bank_path, "us") if c.turn_index == 4)
    assert case.question.startswith("Does the Apex Print Solutions invoice, APS-410093,")
    assert "reconciliation check" not in case.question
    assert case.notes == "reconciliation check, required not bonus"


def test_wrapped_answer_lines_are_joined(bank_path):
    case = next(c for c in parse_question_bank(bank_path, "us") if c.turn_index == 4)
    assert "5,000 x $0.08 = $400.00" in case.expected_answer
    # ...and the continuation line that was wrapped in the source.
    assert "$20.00 discrepancy" in case.expected_answer


def test_matching_and_computation_form_is_preserved_with_its_labels(bank_path):
    """The cross-invoice sums state which lines matched and then the sum. The
    labels carry meaning — a reference answer that lost them would read as one
    undifferentiated blob to the accuracy judge."""
    case = next(c for c in parse_question_bank(bank_path, "us") if c.turn_index == 11)
    assert case.expected_answer.startswith("Matching: $450.00 + $2,386.31.")
    assert "Computation: 450.00 + 2,386.31 = $2,836.31." in case.expected_answer


def test_follow_up_annotation_becomes_a_thread_link(bank_path):
    """This is the doc's bounded multi-turn tier — 2-3 turn scripts with pinned
    expectations, recovered from annotations that already exist."""
    cases = parse_question_bank(bank_path, "us")
    follow_up = next(c for c in cases if c.turn_index == 12)
    assert follow_up.follow_up_of == "us_q11"
    assert follow_up.tier == "thread"
    assert follow_up.thread_id and "session_3" in follow_up.thread_id
    # ...and the turn it depends on is a plain trace case.
    assert next(c for c in cases if c.turn_index == 11).tier == "trace"


def test_rubric_and_headings_do_not_become_cases(bank_path):
    questions = [case.question for case in parse_question_bank(bank_path, "us")]
    assert not any("Required to pass" in q for q in questions)
    assert not any(q.startswith("#") for q in questions)


def test_missing_bank_file_is_not_an_error(tmp_path):
    assert parse_question_bank(tmp_path / "nope.md", "us") == []


# ---------------------------------------------------------------------------
# Format 2 — live_test_results.md
# ---------------------------------------------------------------------------

RESULTS_MD = """# Live Chat-Accuracy Test Results -- US Tenant

| Q# | Question | Expected | Actual (verbatim) | Verdict | Output Quality | Notes |
|---|---|---|---|---|---|---|
| 1 | Total on Summit invoice | $450.00 | "The total is USD 450.00." | PASS | Good | |
| 4 | Reconciliation check, Apex | No -- $400 true math vs $420 printed | prose says 5000 \\| 0.08 = 420 | **FAIL** | Noisy | New bug, same class as the tax-component guardrail (Gap 263) was built for. |
| 14 | Has TSD-620458 been paid? | Not tracked | "I couldn't find invoice TSD-620458" | **FAIL** | Noisy | Direction flipped -- see Gaps 267/270. |
"""


@pytest.fixture
def results_path(tmp_path: Path) -> Path:
    path = tmp_path / "live_test_results.md"
    path.write_text(RESULTS_MD, encoding="utf-8")
    return path


def test_live_results_table_is_parsed_by_question_number(results_path):
    verdicts = parse_live_test_results(results_path)
    assert sorted(verdicts) == [1, 4, 14]
    assert verdicts[1].verdict == "PASS"
    assert verdicts[4].verdict == "FAIL"


def test_gap_attribution_comes_out_of_the_notes_column(results_path):
    """The only place in any of these sources where a question is tied to a gap."""
    verdicts = parse_live_test_results(results_path)
    assert verdicts[1].gaps == []
    assert verdicts[4].gaps == [263]
    assert verdicts[14].gaps == [267, 270]


def test_escaped_pipes_inside_a_cell_do_not_shift_the_columns(results_path):
    """The Actual column embeds markdown tables with escaped pipes; splitting on
    every `|` would push Verdict and Notes one column left and silently lose the
    gap references."""
    verdicts = parse_live_test_results(results_path)
    assert verdicts[4].expected.startswith("No -- $400 true math")
    assert "Gap 263" in verdicts[4].source or verdicts[4].gaps == [263]


def test_attach_live_verdicts_matches_on_number_not_text(bank_path, results_path):
    """The results tables paraphrase long questions to fit the column, so text
    matching would drop exactly the rows carrying the gap references."""
    cases = parse_question_bank(bank_path, "us")
    attached = attach_live_verdicts(cases, "us", parse_live_test_results(results_path))
    assert attached == 1  # only Q4 of {1, 4} has a gap in its notes
    q4 = next(c for c in cases if c.turn_index == 4)
    assert q4.source_gap == 263
    assert q4.live_verdict == "FAIL"
    # A bank question the live run did not cover keeps no verdict at all.
    assert next(c for c in cases if c.turn_index == 11).live_verdict is None


# ---------------------------------------------------------------------------
# Format 3 — per-gap evidence folders
# ---------------------------------------------------------------------------


@pytest.fixture
def evidence_root(tmp_path: Path) -> Path:
    root = tmp_path / "test_evidence"

    retrieval = root / "gap244_rag_retrieval_2026-08-17"
    retrieval.mkdir(parents=True)
    (retrieval / "README.md").write_text(
        "# BE Gaps 244 / 240 / 243 / 239 - RAG retrieval evidence\n", encoding="utf-8"
    )
    (retrieval / "probe.json").write_text(
        json.dumps(
            {
                "threshold": 0.49,
                "turns": [
                    {
                        "query": "How much did we spend on office supplies?",
                        "expected": ["Summit Office Supplies"],
                        "matches": [{"vendor": "Summit Office Supplies", "distance": 0.41}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (retrieval / "threshold_derivation.json").write_text(
        json.dumps(
            {
                "cosine": {
                    "report": [
                        {"query": "What about printing costs?", "expect": ["APS-410093"]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    session = root / "gap237_jsonb_cast_2026-08-18"
    session.mkdir(parents=True)
    (session / "raw_turns_after_0.json").write_text(
        json.dumps(
            {
                "run_label": "after_0",
                "turns": [
                    {
                        "label": "turn_1_broad",
                        "prompt": "What are the total invoices related to cloud?",
                        "response_json": {"content": "There are 4 cloud-related invoices."},
                    },
                    {
                        "label": "turn_2_narrow",
                        "prompt": "Can you explain the 3 USD ones in detail?",
                        "response_json": {"content": "Here are the three USD invoices."},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    repro = root / "gap237_sql_repro_2026-08-17"
    repro.mkdir(parents=True)
    (repro / "raw_turns_run0.json").write_text(
        json.dumps(
            {
                "run_label": "run0",
                "chat_message_db_rows": [
                    {"role": "user", "content": "What are the total invoices related to cloud?"},
                    {"role": "assistant", "content": "There are 4 (buggy pre-fix answer)."},
                ],
            }
        ),
        encoding="utf-8",
    )
    return root


def test_retrieval_probes_become_deterministic_entity_cases(evidence_root):
    cases = parse_test_evidence(evidence_root)
    probes = [c for c in cases if c.expectation_kind == KIND_EXPECTED_ENTITIES]
    assert len(probes) == 2
    by_question = {c.question: c for c in probes}
    assert by_question["How much did we spend on office supplies?"].expected_entities == [
        "Summit Office Supplies"
    ]
    # Both `expected` (turns) and `expect` (threshold_derivation) spellings.
    assert by_question["What about printing costs?"].expected_entities == ["APS-410093"]
    # A retrieval expectation is a Run-level check, not an answer to judge.
    assert all(probe.tier == "run" for probe in probes)
    assert all(probe.expected_answer is None for probe in probes)


def test_readme_title_supplies_the_grouped_gap_numbers(evidence_root):
    """`gap244_rag_retrieval` is titled "BE Gaps 244 / 240 / 243 / 239". Reading
    the folder name alone under-reports coverage by three gaps."""
    cases = parse_test_evidence(evidence_root)
    probe = next(c for c in cases if c.expectation_kind == KIND_EXPECTED_ENTITIES)
    assert probe.source_gap == 244
    assert probe.related_gaps == [239, 240, 243, 244]


def test_post_fix_capture_gives_a_provisional_expectation_flagged_for_review(evidence_root):
    cases = parse_test_evidence(evidence_root)
    post_fix = [c for c in cases if c.expectation_kind == KIND_OBSERVED_POST_FIX]
    assert post_fix, "the after-fix capture must yield something"
    first = next(c for c in post_fix if c.turn_index == 0)
    assert first.expected_answer == "There are 4 cloud-related invoices."
    assert first.needs_review is True
    assert "not an independently authored expected answer" in first.notes
    assert first.tier == "thread"  # two ordered turns in one session


def test_prefix_repro_capture_records_no_expectation(evidence_root):
    """A pre-fix repro's observed answer is the *bug*. Emitting it as an expected
    answer would pin the regression suite to the broken behaviour."""
    cases = parse_test_evidence(evidence_root)
    repro = [c for c in cases if "sql_repro" in c.source]
    assert repro
    assert all(c.expectation_kind == KIND_NONE for c in repro)
    assert all(c.expected_answer is None for c in repro)
    assert all(c.needs_review for c in repro)


def test_missing_evidence_root_is_not_an_error(tmp_path):
    assert parse_test_evidence(tmp_path / "nope") == []


# ---------------------------------------------------------------------------
# Gap reference parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("closed by Gap 263", [263]),
        ("run_agentic_sage_live.py (gap270)", [270]),
        ("Gaps 263/264: this schema stores one combined tax_amount", [263, 264]),
        ("# BE Gaps 244 / 240 / 243 / 239 - RAG retrieval evidence", [239, 240, 243, 244]),
        ("Scope: confirm BE Gaps 228-232 hold", [228, 229, 230, 231, 232]),
        ("no gap numbers here at all", []),
    ],
)
def test_extract_gap_numbers_handles_every_spelling_used_in_this_repo(text, expected):
    assert extract_gap_numbers(text) == expected


def test_an_implausibly_wide_range_is_read_as_two_citations_not_a_range():
    assert extract_gap_numbers("Gaps 1-999") == [1, 999]


# ---------------------------------------------------------------------------
# Dedup, summary, coverage
# ---------------------------------------------------------------------------


def _case(**kwargs) -> GoldenBankCase:
    base = dict(case_id="c", question="q", expectation_kind=KIND_NONE, tenant="evidence")
    base.update(kwargs)
    return GoldenBankCase(**base)


def test_dedup_keeps_the_copy_that_carries_an_expectation():
    """The evidence folders hold 7-8 statistical repeats of one session, so the
    same question recurs a dozen times with only some copies carrying an answer."""
    cases = [
        _case(case_id="bare", turn_index=0, source_gap=237),
        _case(
            case_id="with_answer",
            turn_index=0,
            source_gap=237,
            expectation_kind=KIND_OBSERVED_POST_FIX,
            expected_answer="post-fix answer",
        ),
        _case(case_id="bare_again", turn_index=0, source_gap=237),
    ]
    kept, dropped = deduplicate(cases)
    assert dropped == 2
    assert len(kept) == 1
    assert kept[0].case_id == "with_answer"


def test_dedup_does_not_merge_the_same_question_at_different_turn_positions():
    cases = [
        _case(case_id="t0", turn_index=0, source_gap=237),
        _case(case_id="t1", turn_index=1, source_gap=237),
    ]
    kept, dropped = deduplicate(cases)
    assert dropped == 0 and len(kept) == 2


def test_summary_counts_what_the_scorer_can_actually_consume():
    cases = [
        _case(expectation_kind=KIND_REFERENCE_ANSWER, expected_answer="a"),
        _case(expectation_kind=KIND_EXPECTED_ENTITIES, expected_entities=["v"]),
        _case(expectation_kind=KIND_NONE, needs_review=True),
    ]
    summary = summarise(cases)
    assert summary["total_cases"] == 3
    assert summary["directly_scorable_by_services_agent_eval"] == 1
    assert summary["deterministic_retrieval_cases"] == 1
    assert summary["no_expectation_recorded_must_be_written"] == 1
    assert summary["provisional_needs_human_review"] == 1


def test_coverage_reports_both_a_strict_and_a_loose_denominator(tmp_path):
    """A keyword classifier over hand-written prose is not exact. Reporting one
    number would hide that; reporting both brackets the real population."""
    tracker = tmp_path / "tracker.md"
    tracker.write_text(
        "- `[x]` **Gap 263 (BE): Chat SQL route misfires on tax-component questions**"
        " - closed 2026-08-19.\n"
        "- `[x]` **Gap 42: No per-tenant fair-share throttling on the extraction queue**"
        " - the chat path was unaffected.\n"
        "- `[x]` **Gap 131: Google Drive redirect_uri_mismatch** - OAuth only.\n"
        "- `[ ]` **Gap 999: Not closed yet, about chat answers**\n",
        encoding="utf-8",
    )
    index = tracker_gap_index(tracker)
    assert set(index) == {263, 42, 131, 999}

    coverage = build_coverage([_case(source_gap=263)], index)
    assert coverage["tracker_gap_entries"] == 4
    assert coverage["tracker_closed_gaps"] == 3
    # Gap 42's *title* is about queue throttling; only its narrative says "chat".
    assert coverage["closed_answer_quality_gaps_strict_title_match"] == 1
    assert coverage["closed_answer_quality_gaps_loose_anywhere_in_entry"] == 2
    assert coverage["strict_answer_quality_gaps_with_a_recovered_case"] == 1
    assert coverage["strict_answer_quality_gaps_without_a_case"] == []
    assert coverage["covered_gap_numbers"] == [263]


def test_coverage_counts_related_gaps_not_only_the_primary(tmp_path):
    tracker = tmp_path / "tracker.md"
    tracker.write_text(
        "- `[x]` **Gap 240: RAG retrieval returns nothing for a category question**\n"
        "- `[x]` **Gap 244: RAG retrieval distance threshold is wrong**\n",
        encoding="utf-8",
    )
    coverage = build_coverage(
        [_case(source_gap=244, related_gaps=[239, 240, 243, 244])],
        tracker_gap_index(tracker),
    )
    assert coverage["covered_gap_numbers"] == [239, 240, 243, 244]
    assert coverage["strict_answer_quality_gaps_with_a_recovered_case"] == 2


# ---------------------------------------------------------------------------
# The assembled fixture
# ---------------------------------------------------------------------------


def test_build_fixture_produces_the_documented_shape():
    """Structure only, never counts — the real sources are gitignored, so a
    count assertion would pass here and fail on a clean checkout."""
    fixture = build_fixture()
    for key in (
        "generated_by",
        "generated_at",
        "consumed_by",
        "provenance",
        "extraction_stats",
        "summary",
        "gap_coverage",
        "cases",
    ):
        assert key in fixture

    assert fixture["provenance"]["source_directories_are_gitignored"]
    assert "scrubbing" in fixture["provenance"]
    assert json.dumps(fixture)  # must be serialisable as written


def test_every_reference_answer_case_is_directly_feedable_to_the_scorer():
    """`services/agent_eval.py::score_answer` takes question/expected_answer as
    strings. Anything the fixture labels `reference_answer` must satisfy that
    without further massaging, or the label is a lie."""
    import inspect

    from services.agent_eval import score_answer

    parameters = inspect.signature(score_answer).parameters
    assert {"question", "expected_answer"} <= set(parameters)

    for case in build_fixture()["cases"]:
        if case["expectation_kind"] != KIND_REFERENCE_ANSWER:
            continue
        assert isinstance(case["question"], str) and case["question"].strip()
        assert isinstance(case["expected_answer"], str) and case["expected_answer"].strip()
