"""Gap 307 — the multi-turn context-drift tier of the golden bank.

Offline only. This grades *scripted* conversations against the same seeded
SQLite fixture the rest of the bank uses; nothing here looks at production
traffic. A live judge over real `chat_turn` events is a separate, later gap and
is deliberately not started here.

What "context drift" means, taken from this repo rather than invented
---------------------------------------------------------------------
`be_features_tracker.md`'s Gaps 303 and 307 and
`docs/feature_20_23_24_ops_workbook.md` define it by two already-observed
failure shapes, both of them **closed bugs cited as the failure class** — closing
them built no detector:

  Gap 237  a narrowing follow-up ("explain the 3 USD ones") silently dropping a
           branch of the previous turn's predicate. Context that SHOULD still
           apply, and did not.
  Gap 276  the previous turn's SQL reused after the subject changed. Context that
           should NOT still apply, and did.

Gap 307's own words are that the two shapes should be scoped down to "fixed 2-3
turn scripts with pinned expectations" before a general detector is promised.
That is exactly what this file is: five scripts, twelve turns, every expectation
pinned to a row in `benchmarks/sage_seed_fixtures.py` /
`benchmarks/large_invoice_fixture.py` and stated to the cent.

Why this is a new module and not more entries in `CASES`
--------------------------------------------------------
A `GoldenCase` in `agent_eval_golden_sample.py` is a standalone question: the
runner gives every one of them a fresh `session_id`, and nothing links them. A
drift case is meaningless standalone — turn 2 of script A is *correct* as a
first turn. So the tier needs three things the single-turn bank does not have,
and all three live here or in the runner rather than being retrofitted onto the
35 existing cases:

  1. **A shared session across a script's turns**, so `get_chat_history()` and
     `get_prior_turn_sql()` (the two functions drift actually happens in) see the
     earlier turns at all.
  2. **`ChatMessage` write-back between turns.** `run_query_agent()` does not
     persist anything — `routers/chat.py::post_chat_message` does. So the runner
     writes the user/assistant rows itself, with the assistant row carrying that
     turn's real `generated_sql`, which is the row `get_prior_turn_sql()` reads.
     Without it the "conversation" would be twelve independent first turns.
  3. **Its own summary bucket** (`MULTI_TURN_PATH`). These turns are deliberately
     harder than the single-turn bank, so folding them into `summary["default"]`
     would move the nightly pass rate and every quality mean onto a different
     population than every historical figure in the docs.

Cost, stated because a nightly job pays it every night: twelve extra turns, each
with its own judge calls, on top of the 35-case bank. `--no-multi-turn` skips
the tier for a developer's own run.

The seeded facts these scripts turn on
---------------------------------------
All five scripts run against the base fixture tenant (nine invoices). The three
facts that make the drift checks discriminating, and which are asserted by
`tests/test_agent_eval_multiturn.py` against the fixture rather than trusted:

  * The oldest invoice **overall** is Harbor Tech's `US-20260722-001`
    (2026-06-01), and it is *not* in the over-USD-20,000 set — so a follow-up
    that drops the threshold filter lands on it and nowhere else.
  * The largest invoice **overall** is Meridian Industrial Supply's
    `MIS-2026-0881` (USD 271,019.63, 2026-07-14), and it is *not* in June — so a
    follow-up that drops a stated June scope lands on it.
  * The only freight line in the tenant is on Blue Ridge Logistics' `BRL-7702`,
    dated 2026-07-05 — also *not* in June.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

_BE_ROOT = Path(__file__).resolve().parent.parent
if str(_BE_ROOT) not in sys.path:
    sys.path.insert(0, str(_BE_ROOT))

from benchmarks.agent_eval_golden_sample import GoldenCase, TENANT_ID  # noqa: E402
from services.agent_eval import DriftExpectation  # noqa: E402
from services.benchmark_artifacts import MULTI_TURN_PATH  # noqa: E402

__all__ = [
    "MULTI_TURN_CASES",
    "MULTI_TURN_PATH",
    "MULTI_TURN_SCRIPTS",
    "MultiTurnScript",
    "cases_for",
]


@dataclass(frozen=True)
class MultiTurnScript:
    """One scripted conversation, run in order against one shared session.

    `turns` are ordinary `GoldenCase`s — same dataclass, same judge, same
    scoring path — so this tier reuses the whole grading stack rather than
    running a parallel one. What makes them a conversation is that the runner
    gives them one `session_id` and writes each turn's `ChatMessage` rows before
    the next turn starts.
    """

    script_id: str
    why_on_file: str
    source: str
    turns: tuple[GoldenCase, ...]
    tenant_id: str = TENANT_ID

    def case_ids(self) -> tuple[str, ...]:
        return tuple(case.case_id for case in self.turns)


def _turn_id(script_id: str, index: int) -> str:
    """`<script>__t<n>`, 1-based. The `__t` separator is what lets a reader of a
    persisted `agent_eval_run` row tell a drift turn from a single-turn case
    without opening this file, and what `--cases <script_id>` expands over."""
    return f"{script_id}__t{index}"


# ---------------------------------------------------------------------------
# Script 1 — the subject changes and the old filter must go with it (Gap 276)
# ---------------------------------------------------------------------------

_SUBJECT_SWITCH = MultiTurnScript(
    script_id="drift_subject_switch_vendor",
    source="Gap 276 (prior SQL reused after a topic change); Gap 307's failure class",
    why_on_file=(
        "The cleanest statement of Gap 276's shape that the seeded tenant can support: "
        "two turns, two different vendors, and an explicit 'instead' in the second. The "
        "failure is the previous turn's `vendor_name` predicate surviving into turn 2 — "
        "which shows up in the WHERE clause whether or not the stale rows reach the prose, "
        "which is why the SQL is its own scored surface."
    ),
    turns=(
        GoldenCase(
            case_id=_turn_id("drift_subject_switch_vendor", 1),
            question="which invoices do we have from Blue Ridge Logistics?",
            expected_answer=(
                "One invoice: BRL-7702 from Blue Ridge Logistics, USD 6,120.00, dated "
                "2026-07-05 and due 2026-08-04, status COMPLETED. Naming the invoice and its "
                "total is what this turn needs; the line-item breakdown is not required here."
            ),
            source="Gap 307 multi-turn tier (setup turn)",
            why_on_file=(
                "The setup turn. It is graded like any other case so a script cannot pass its "
                "drift check by having failed to establish a subject in the first place."
            ),
            expected_invoice_numbers=("BRL-7702",),
        ),
        GoldenCase(
            case_id=_turn_id("drift_subject_switch_vendor", 2),
            question="now show me everything from DataPipe Solutions instead",
            expected_answer=(
                "One invoice: DPS-9981 from DataPipe Solutions, USD 42,300.00, dated "
                "2026-06-30 and due 2026-07-30, status COMPLETED. The word 'instead' replaces "
                "the subject: Blue Ridge Logistics' BRL-7702 is no longer in scope and must "
                "not be reported as part of the answer. An answer that lists both vendors' "
                "invoices has not switched subject, it has widened."
            ),
            source="Gap 307 multi-turn tier (drift turn)",
            why_on_file=(
                "Gap 276 exactly: does turn 2's query filter on DataPipe, or on Blue Ridge, or "
                "on both? The tenant has one invoice per vendor, so the right and wrong answers "
                "are single rows and cannot be confused with each other."
            ),
            expected_invoice_numbers=("DPS-9981",),
            drift=DriftExpectation(
                forbidden_sql_terms=("Blue Ridge",),
                forbidden_terms=("BRL-7702",),
                required_entities=(("DataPipe", "DPS-9981"),),
                forbidden_invoice_numbers=("BRL-7702",),
                note=(
                    "turn 1 was about Blue Ridge Logistics; 'instead' means its predicate, its "
                    "invoice number and its row must all be gone by turn 2"
                ),
            ),
        ),
    ),
)


# ---------------------------------------------------------------------------
# Script 2 — the follow-up that must KEEP the filter (Gap 237)
# ---------------------------------------------------------------------------

_NARROWING_FOLLOWUP = MultiTurnScript(
    script_id="drift_narrowing_followup_keeps_filter",
    source="Gap 237 (a follow-up re-deriving the predicate from prose and dropping a branch)",
    why_on_file=(
        "The mirror image of script 1, and the reason both are needed: drift is not 'the old "
        "context leaked', it is 'the context at turn N is not the context turn N should have'. "
        "Here the earlier filter MUST survive. 'Which of those' is scoped to the over-USD-20,000 "
        "set, whose oldest member is StratEdge's SEP-4410 (2026-06-27) — while the oldest "
        "invoice in the tenant is Harbor Tech's US-20260722-001 (2026-06-01), which is USD 420 "
        "and therefore only reachable by dropping the threshold."
    ),
    turns=(
        GoldenCase(
            case_id=_turn_id("drift_narrowing_followup_keeps_filter", 1),
            question="list every vendor we have an invoice from over USD 20,000, with the amount",
            expected_answer=(
                "Exactly three, and every one of them is required: Meridian Industrial Supply at "
                "USD 271,019.63 (invoice MIS-2026-0881), DataPipe Solutions at USD 42,300.00 "
                "(invoice DPS-9981), and StratEdge Partners at USD 27,950.00 (invoice SEP-4410). "
                "Rajesh Steel's INR 118,000.00 invoice must NOT be listed — it is in a different "
                "currency and no exchange rate is available."
            ),
            source=(
                "phrasing reused verbatim from `all_vendors_over_twenty_thousand` in "
                "benchmarks/agent_eval_golden_sample.py (Gap 268's truncation shape)"
            ),
            why_on_file=(
                "Reused deliberately rather than reworded: the single-turn bank already grades "
                "this exact question, so any difference between the two runs is attributable to "
                "the conversation and not to a differently-phrased setup."
            ),
            expected_invoice_numbers=("MIS-2026-0881", "DPS-9981", "SEP-4410"),
        ),
        GoldenCase(
            case_id=_turn_id("drift_narrowing_followup_keeps_filter", 2),
            question="which of those is the oldest?",
            expected_answer=(
                "StratEdge Partners' invoice SEP-4410, dated 2026-06-27 — the oldest of the "
                "three invoices over USD 20,000 (DataPipe's DPS-9981 is 2026-06-30 and "
                "Meridian's MIS-2026-0881 is 2026-07-14). 'Of those' means the previous turn's "
                "over-USD-20,000 set: answering with Harbor Tech's US-20260722-001 (2026-06-01), "
                "which is the oldest invoice in the tenant but is only USD 420.00, means the "
                "threshold was dropped and is wrong."
            ),
            source="Gap 307 multi-turn tier (drift turn)",
            why_on_file=(
                "Gap 237's shape with a pinned wrong answer. The predicate has two branches "
                "(currency and amount) and the follow-up adds a third (date); the observed "
                "failure mode is re-deriving the query from the conversation prose and losing "
                "one of them."
            ),
            # No expected set: re-running the threshold query and returning all three,
            # or narrowing to the single oldest row, are both correct retrievals. The
            # drift expectation carries the whole check -- see DriftExpectation's docstring.
            expected_invoice_numbers=None,
            drift=DriftExpectation(
                forbidden_terms=("Harbor Tech", "US-20260722-001"),
                required_entities=(("StratEdge", "SEP-4410"),),
                forbidden_invoice_numbers=("US-20260722-001",),
                note=(
                    "'of those' is scoped to turn 1's over-USD-20,000 set; Harbor Tech is the "
                    "oldest invoice only if that filter was dropped"
                ),
            ),
        ),
    ),
)


# ---------------------------------------------------------------------------
# Script 3 — three turns, and the referent moves with the conversation
# ---------------------------------------------------------------------------

_MOVING_REFERENT = MultiTurnScript(
    script_id="drift_referent_moves_with_conversation",
    source="Gap 307's 'loses track of which document is under discussion'",
    why_on_file=(
        "The three-turn case, and the one closest to how drift is actually described: an early "
        "subject that should stop applying once a later one replaces it. Turn 3 says 'that one' "
        "with no name at all, so the only thing that can resolve it is the conversation — and "
        "the two candidates have different due dates (Titan 2026-08-01, Blue Ridge 2026-08-04), "
        "so a stale referent is visible as a wrong date rather than as a matter of opinion."
    ),
    turns=(
        GoldenCase(
            case_id=_turn_id("drift_referent_moves_with_conversation", 1),
            question="what's the due date on the Titan Steel Distributors invoice?",
            expected_answer=(
                "2026-08-01. Titan Steel Distributors' invoice TSD-620458 (USD 18,450.00, dated "
                "2026-07-02) is due 2026-08-01. Note this system tracks document-processing "
                "status, not payment status, so an answer must not claim the invoice has or has "
                "not been paid."
            ),
            source="Gap 307 multi-turn tier (setup turn)",
            why_on_file="Establishes the first referent, and the date turn 3 must NOT return.",
            expected_invoice_numbers=("TSD-620458",),
        ),
        GoldenCase(
            case_id=_turn_id("drift_referent_moves_with_conversation", 2),
            question="what about Blue Ridge Logistics -- what did they bill us for?",
            expected_answer=(
                "Blue Ridge Logistics' invoice BRL-7702, USD 6,120.00 in total, carries two "
                "lines: 'Freight and handling', 4 at USD 280.00 = USD 1,120.00, and 'Warehouse "
                "storage', 1 at USD 5,000.00 = USD 5,000.00. Both lines are required; they sum "
                "to the USD 6,120.00 total. The subject has moved: this question is about Blue "
                "Ridge, so an answer that reports Titan Steel's TSD-620458 — or that queries "
                "for it — has not followed the change of subject."
            ),
            source="Gap 307 multi-turn tier (referent hand-over turn)",
            why_on_file=(
                "The turn that replaces the referent. It is scored for drift too, because the "
                "hand-over is where the previous subject most plausibly survives — the question "
                "names a new vendor but asks a differently-shaped question about it."
            ),
            expected_invoice_numbers=("BRL-7702",),
            drift=DriftExpectation(
                forbidden_sql_terms=("Titan Steel",),
                forbidden_terms=("TSD-620458",),
                required_entities=(("Blue Ridge", "BRL-7702"),),
                forbidden_invoice_numbers=("TSD-620458",),
                note="the subject moves from Titan Steel to Blue Ridge here",
            ),
        ),
        GoldenCase(
            case_id=_turn_id("drift_referent_moves_with_conversation", 3),
            question="and when is that one due?",
            expected_answer=(
                "2026-08-04 — the due date of Blue Ridge Logistics' invoice BRL-7702, which is "
                "the invoice under discussion by this point in the conversation. Returning "
                "2026-08-01 (Titan Steel's TSD-620458, two turns back) means the referent never "
                "moved and is the failure this turn exists to catch."
            ),
            source="Gap 307 multi-turn tier (drift turn)",
            why_on_file=(
                "'That one' with no noun. Two turns of history, and the correct referent is the "
                "more recent one — the single most compact statement of context drift available "
                "against this fixture."
            ),
            expected_invoice_numbers=("BRL-7702",),
            drift=DriftExpectation(
                forbidden_sql_terms=("Titan Steel",),
                # `2026-08-01` is Titan's due date and appears nowhere in a correct
                # answer to this question. It is an ISO date because that is how the
                # column is stored, so it is a stable string -- see DriftExpectation.
                forbidden_terms=("TSD-620458", "2026-08-01"),
                forbidden_invoice_numbers=("TSD-620458",),
                note=(
                    "'that one' must resolve to Blue Ridge (turn 2), not to Titan Steel "
                    "(turn 1)"
                ),
            ),
        ),
    ),
)


# ---------------------------------------------------------------------------
# Script 4 — "the previous invoice", said when there are two of them
# ---------------------------------------------------------------------------

_AMBIGUOUS_BACKREF = MultiTurnScript(
    script_id="drift_ambiguous_previous_invoice",
    source="Gap 307's 'referencing the previous invoice ambiguously'",
    why_on_file=(
        "A back-reference that genuinely has no single referent: turn 1 puts two invoices in "
        "play, so 'the previous invoice' can only be answered by covering both or by asking "
        "which. The failure this catches is not a wrong number, it is resolving an ambiguous "
        "reference silently — and the most plausible silent resolution is not either candidate "
        "but the tenant's own most recent invoice, Rajesh Steel's INDIA-20260722-003 "
        "(2026-07-22), which was never under discussion at all."
    ),
    turns=(
        GoldenCase(
            case_id=_turn_id("drift_ambiguous_previous_invoice", 1),
            question=(
                "Between DataPipe Solutions and StratEdge Partners, whose invoice to us had "
                "the bigger total?"
            ),
            expected_answer=(
                "DataPipe Solutions' invoice is bigger: DPS-9981 at USD 42,300.00 against "
                "StratEdge Partners' SEP-4410 at USD 27,950.00. Both vendors and both figures "
                "are required; reporting only the winner is wrong."
            ),
            source=(
                "phrasing reused verbatim from `datapipe_vs_stratedge` in "
                "benchmarks/agent_eval_golden_sample.py (Gap 268)"
            ),
            why_on_file=(
                "Reused so the setup is a question the bank already grades, and because it is "
                "the one seeded question that leaves exactly two invoices in play."
            ),
            expected_invoice_numbers=("DPS-9981", "SEP-4410"),
        ),
        GoldenCase(
            case_id=_turn_id("drift_ambiguous_previous_invoice", 2),
            question="how much tax was on the previous invoice?",
            expected_answer=(
                "'The previous invoice' is ambiguous here: the turn before named two invoices. "
                "A correct answer either asks which of the two is meant, naming both, or gives "
                "both figures — DataPipe's DPS-9981 carries USD 3,384.00 of tax and StratEdge's "
                "SEP-4410 carries USD 2,236.00. Silently picking one of the two without saying "
                "so is wrong even when the figure quoted is right, and answering about any "
                "third invoice (for example the tenant's most recent one, Rajesh Steel's "
                "INDIA-20260722-003) is wrong outright."
            ),
            source="Gap 307 multi-turn tier (drift turn)",
            why_on_file=(
                "The ambiguous back-reference. Both required entities are ones the correct "
                "answer must name under either correct strategy (ask, or cover both), which "
                "is the rule `DriftExpectation.required_entities` is limited to. It is also "
                "the case whose first live run (2026-08-26) proved the aliases have to be a "
                "group rather than a flat term list: the real answer asked the clarifying "
                "question correctly but named both invoices by NUMBER, not by vendor."
            ),
            # Deliberately unscored for retrieval: asking a clarifying question and
            # fetching nothing is correct here, and so is fetching both rows.
            expected_invoice_numbers=None,
            drift=DriftExpectation(
                forbidden_terms=("Rajesh Steel", "INDIA-20260722-003"),
                required_entities=(("DataPipe", "DPS-9981"), ("StratEdge", "SEP-4410")),
                forbidden_invoice_numbers=("INDIA-20260722-003",),
                note=(
                    "'previous' is a conversational referent, not a row ordering — resolving it "
                    "against the tenant's latest invoice is the drift"
                ),
            ),
        ),
    ),
)


# ---------------------------------------------------------------------------
# Script 5 — a scope stated once, three turns of it
# ---------------------------------------------------------------------------

_STATED_SCOPE = MultiTurnScript(
    script_id="drift_scope_stated_once_still_applies",
    source="Gap 307's 'long conversations where early context should still apply'",
    why_on_file=(
        "The hardest of the five, and knowingly so. The scope is stated once, in a turn that "
        "asks no question at all, and then has to survive two questions that never mention it. "
        "Both later turns have a pinned wrong answer reachable only by dropping it: the largest "
        "invoice in the tenant (Meridian's MIS-2026-0881, 2026-07-14) is not in June, and the "
        "only freight line in the tenant (Blue Ridge's BRL-7702, 2026-07-05) is not either. "
        "This script is expected to be the one that fails first; that is the point of having it."
    ),
    turns=(
        GoldenCase(
            case_id=_turn_id("drift_scope_stated_once_still_applies", 1),
            question=(
                "For the rest of this conversation I only want to look at invoices dated in "
                "June 2026."
            ),
            expected_answer=(
                "An acknowledgement that the June 2026 scope is understood. Four seeded "
                "invoices fall in June 2026 — Harbor Tech's US-20260722-001 (2026-06-01), "
                "Redwood Facilities Group's RFG-2026-114 (2026-06-18), StratEdge Partners' "
                "SEP-4410 (2026-06-27) and DataPipe Solutions' DPS-9981 (2026-06-30) — so an "
                "answer that also lists them is correct and helpful. Claiming a different count, "
                "or ignoring the instruction, is wrong."
            ),
            source="Gap 307 multi-turn tier (scope-setting turn)",
            why_on_file=(
                "A turn that is an instruction rather than a question. Nothing in the "
                "single-turn bank has this shape, and it is the shape that makes the two turns "
                "after it a drift test."
            ),
            expected_invoice_numbers=None,
        ),
        GoldenCase(
            case_id=_turn_id("drift_scope_stated_once_still_applies", 2),
            question="which vendor billed us the most?",
            expected_answer=(
                "Within the June 2026 scope set one turn earlier: DataPipe Solutions, invoice "
                "DPS-9981, USD 42,300.00 (2026-06-30). Answering Meridian Industrial Supply "
                "(MIS-2026-0881, USD 271,019.63) means the June scope was dropped — that "
                "invoice is dated 2026-07-14. An answer that asks whether the June scope still "
                "applies is acceptable; one that silently answers over all nine invoices is not."
            ),
            source="Gap 307 multi-turn tier (drift turn)",
            why_on_file=(
                "The scope's first test. The wrong answer is not a near miss: USD 271,019.63 "
                "against USD 42,300.00, a different vendor and a different month."
            ),
            # Unscored for retrieval on purpose: a June-scoped MAX query legitimately
            # fetches either the single winning row or all four June rows.
            expected_invoice_numbers=None,
            drift=DriftExpectation(
                forbidden_terms=("Meridian", "MIS-2026-0881"),
                required_entities=(("DataPipe", "DPS-9981"),),
                forbidden_invoice_numbers=("MIS-2026-0881",),
                note="the June 2026 scope from turn 1 must still bound this aggregate",
            ),
        ),
        GoldenCase(
            case_id=_turn_id("drift_scope_stated_once_still_applies", 3),
            question="does any of them include a freight or delivery charge?",
            expected_answer=(
                "No. Within the June 2026 scope, none of the four invoices carries a freight, "
                "delivery or shipping line: Harbor Tech's US-20260722-001 is a single 'Bolts' "
                "line, and the other three record no line items at all. The tenant's only "
                "freight line is 'Freight and handling' on Blue Ridge Logistics' BRL-7702 — "
                "dated 2026-07-05, i.e. outside the stated scope. Reporting Blue Ridge here "
                "means the June scope was dropped. Saying plainly that nothing in June matches, "
                "and optionally that a freight line exists outside the scope if the user wants "
                "it, is the correct answer."
            ),
            source="Gap 307 multi-turn tier (drift turn)",
            why_on_file=(
                "The scope's second test, two turns after it was stated, and with a correct "
                "answer that is a negative — so the tempting wrong answer (the one invoice in "
                "the tenant that does have freight) is also the only positive answer available."
            ),
            expected_invoice_numbers=None,
            drift=DriftExpectation(
                forbidden_sql_terms=("Blue Ridge",),
                forbidden_terms=("BRL-7702",),
                forbidden_invoice_numbers=("BRL-7702",),
                note=(
                    "the only freight line in the tenant is outside the June scope, so a "
                    "Blue Ridge answer is the scope having been dropped"
                ),
            ),
        ),
    ),
)


MULTI_TURN_SCRIPTS: list[MultiTurnScript] = [
    _SUBJECT_SWITCH,
    _NARROWING_FOLLOWUP,
    _MOVING_REFERENT,
    _AMBIGUOUS_BACKREF,
    _STATED_SCOPE,
]

#: Flattened, in script order then turn order. `scripts/run_agent_eval.py` needs
#: this for `case_by_id` and for `persist()`; the *order* only matters inside a
#: script, which `MULTI_TURN_SCRIPTS` preserves.
MULTI_TURN_CASES: list[GoldenCase] = [
    case for script in MULTI_TURN_SCRIPTS for case in script.turns
]


def cases_for(selected: set[str] | None) -> list[MultiTurnScript]:
    """The scripts `--cases` selected, by script id or by any of its case ids.

    A script is all-or-nothing: selecting one of its turns selects the whole
    script, because running turn 2 without turn 1 is not running turn 2 — it is
    running a different, easier question. `None` (no `--cases` given) means every
    script.
    """
    if not selected:
        return list(MULTI_TURN_SCRIPTS)
    return [
        script
        for script in MULTI_TURN_SCRIPTS
        if script.script_id in selected or (selected & set(script.case_ids()))
    ]
