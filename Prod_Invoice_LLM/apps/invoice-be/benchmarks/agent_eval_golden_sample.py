"""Feature 23 Phase 3 — the graded golden sample, and the fixture it is graded against.

Where these questions come from, and what had to be added
---------------------------------------------------------
The scoped source was "a representative subset of the existing golden sets,
`tests/test_chat_sql_quality.py` (71 cases) and `tests/test_rag.py` (56 cases)".
Read directly, those two files are **not** answer-bearing golden sets: they are
mocked unit tests of pipeline *mechanics* (does rule 6d reach the prompt, does
the null-SQL retry fire once, does the hedge trigger on the right shape), with a
scripted `_RecordingLLM` standing in for the model. `test_chat_sql_quality.py`
says so itself in its own module docstring. There is no expected natural-language
answer anywhere in either file to score an actual answer against — so nothing in
them can be "run through" a faithfulness/accuracy scorer as-is.

What is real in them, and reused here verbatim, is the **question phrasings** —
every one of which is a real historical incident from this repo's tracker. Each
case below cites the exact file and line its phrasing was taken from. The
reference answers are new, and are computed from the seeded fixture rows below
rather than authored freehand: for each case, the correct answer is a fact about
seven specific rows, so it can be stated exactly and checked.

The fixture rows and document chunks are imported, not copied, from
`benchmarks/sage_seed_fixtures.py` — the same seven incident-history invoices the
(since-deleted) `tests/run_agentic_sage_live.py` harness seeded. Duplicating them
would let the two drift.

`tests/us|india|eu/chat_question_bank.md` are the repo's *real* answer-bearing
question banks (question + reference answer + grading rubric, ~15 questions per
region). The paragraph that stood here said they were "deliberately not used
here" because each needs its region's tenant in live Postgres with real Chroma
embeddings, and no local Postgres/Chroma/Redis is running.

**That is no longer true as of 2026-08-24 (Feature 23 Wave 3).** Fifteen of those
questions are ported into this file, against three regional tenants re-seeded
into the same in-memory SQLite this harness already uses
(`benchmarks/region_seed_fixtures.py`) with document-only facts carried as fixed
chunks — so no Postgres, no Chroma, and `MOCK_EMBEDDINGS=true` still holds. What
genuinely could not be ported (multi-turn follow-ups, tax-component and
tax-identifier questions the `invoice` table has no column for) is enumerated in
that module's docstring rather than quietly dropped. A live-tenant run remains
the right way to exercise the follow-up chains, and that is still Feature 21
Phase 3's job.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

_BE_ROOT = Path(__file__).resolve().parent.parent
if str(_BE_ROOT) not in sys.path:
    sys.path.insert(0, str(_BE_ROOT))

# Reused, not duplicated -- see the module docstring. Both live in this same
# `benchmarks/` package (moved out of `tests/` 2026-08-23 so the nightly
# scheduled job can import them -- `.dockerignore` excludes `tests/` from the
# deployed image; see benchmarks/__init__.py).
from benchmarks.large_invoice_fixture import LARGE, SMALL  # noqa: E402
# Feature 23 Wave 3, 2026-08-24 -- the India/US/EU banks, each under its own
# tenant id so the twenty cases above keep the exact nine-row fixture their
# reference answers were computed against. See that module's docstring.
from benchmarks.region_seed_fixtures import (  # noqa: E402
    EU_TENANT_ID,
    INDIA_TENANT_ID,
    REGION_TENANTS,
    US_TENANT_ID,
    region_stats_summary,
)
from benchmarks.sage_seed_fixtures import _CHUNKS, _ROWS, TENANT_ID  # noqa: E402

# The seven incident-history rows plus the document-length pair. Kept as its own
# name so `_ROWS` still means "the incident history" to every other reader of
# that module, and so `tenant_stats_summary()` below describes what is actually
# seeded rather than a subset of it.
ALL_ROWS = list(_ROWS) + [LARGE.row(), SMALL.row()]


@dataclass(frozen=True)
class GoldenCase:
    """One graded question.

    `expected_answer` is the reference the accuracy judge compares against, and
    is None only where the case genuinely has no single correct answer to state.
    `source` is the file:line the phrasing came from, so a future reader can
    check it against the incident it encodes rather than trusting this file.
    """

    case_id: str
    question: str
    expected_answer: Optional[str]
    source: str
    why_on_file: str
    #: The invoice(s) a correct context builder should have fetched for this
    #: question — Feature 23's `context_score`, which is a deterministic set
    #: comparison and needs no judge. Read carefully, the three states differ:
    #:   None  -> this case declares no known-correct retrieval set; the
    #:            component is left unscored rather than guessed.
    #:   ()    -> the correct retrieval is *nothing*. That is a real expectation
    #:            and the most diagnostic one in the set (a vendor that does not
    #:            exist, a question that should call no tool at all).
    #:   (...) -> exactly these invoice numbers, no more and no fewer.
    expected_invoice_numbers: Optional[tuple[str, ...]] = None
    #: Which seeded tenant this case is asked against. Defaults to the base
    #: fixture tenant, so the twenty cases above are unchanged by this field's
    #: existence. The regional cases at the bottom of this file each name their
    #: own tenant id (`benchmarks/region_seed_fixtures.py`) — see that module's
    #: docstring for why merging those rows into one tenant would have falsified
    #: several of the reference answers above rather than extended the set.
    tenant_id: str = TENANT_ID


CASES: list[GoldenCase] = [
    GoldenCase(
        case_id="titan_steel_payment_status",
        question="has the Titan Steel Distributors invoice been paid",
        expected_answer=(
            "The correct answer does NOT assert that the invoice has or has not been paid. "
            "Titan Steel Distributors' invoice TSD-620458 (USD 18,450.00, dated 2026-07-02, "
            "due 2026-08-01) carries status COMPLETED, which is this system's *document "
            "processing* status, not a payment status -- no payment/settlement field exists "
            "for inbound invoices in this schema. A correct answer either says plainly that "
            "payment status is not tracked here (optionally giving the invoice's real details "
            "and due date), or asks the user to clarify what they mean. Reading COMPLETED as "
            "'paid' is wrong."
        ),
        source="tests/test_chat_sql_quality.py:1101; tests/run_agentic_sage_live.py (gap270)",
        why_on_file=(
            "Gap 270 / rule 4a: a real INBOUND vendor with no direction cue, asking about a "
            "status this schema does not track. The old pipeline guessed OUTBOUND, matched "
            "zero rows and reported a real invoice as not found."
        ),
        expected_invoice_numbers=("TSD-620458",),
    ),
    GoldenCase(
        case_id="rajesh_steel_cgst",
        question="whats the CGST we paid to Rajesh Steel",
        expected_answer=(
            "The CGST is INR 9,000.00. The Rajesh Steel invoice INDIA-20260722-003 itemizes its "
            "tax as CGST 9% INR 9,000.00 and SGST 9% INR 9,000.00 -- the two components of the "
            "combined INR 18,000.00 tax_amount, on an INR 100,000.00 subtotal and an INR "
            "118,000.00 grand total. A correct answer states the CGST figure as INR 9,000.00 and "
            "may also give the SGST half and/or the combined total; it must READ those figures "
            "from the record, not derive them by halving the total tax, and it must not claim "
            "that no per-component breakdown is stored."
        ),
        source="tests/test_chat_sql_quality.py:878; tests/run_agentic_sage_live.py (gap263)",
        why_on_file=(
            "Gaps 263/264 originally, Gap 310 now. Rewritten 2026-08-24: this case used to "
            "expect a DECLINE ('no per-component breakdown exists anywhere in the data'), "
            "which was true of the default chat route and never true of the data -- "
            "`Invoice.taxes` has carried the itemized components since extraction started "
            "populating it, and only the route's hand-typed schema block could not see them. "
            "The default route now hands the identified invoice's whole ORM row to its "
            "answering step (`query_agent._full_record_block_for`), so this is the case that "
            "proves the real breakdown comes back. The original live failure -- a FABRICATED "
            "CGST/SGST split -- is still what the rubric guards: the figures must be the "
            "stored ones, not half of the total."
        ),
        expected_invoice_numbers=("INDIA-20260722-003",),
    ),
    GoldenCase(
        case_id="datapipe_vs_stratedge",
        question="Between DataPipe Solutions and StratEdge Partners, whose invoice to us had the bigger total?",
        expected_answer=(
            "DataPipe Solutions' invoice is bigger: DPS-9981 at USD 42,300.00 against StratEdge "
            "Partners' SEP-4410 at USD 27,950.00. A correct answer names both vendors and both "
            "figures (a difference of USD 14,350.00 may be given but is not required); an answer "
            "that reports only the winner and silently drops the other invoice is wrong."
        ),
        source="tests/test_chat_sql_quality.py:990; tests/run_agentic_sage_live.py (gap268)",
        why_on_file="Gap 268 / rule 10: the comparison that generated ORDER BY ... LIMIT 1 and truncated the loser.",
        expected_invoice_numbers=("DPS-9981", "SEP-4410"),
    ),
    GoldenCase(
        case_id="freight_per_vendor",
        question="which vendors billed us for freight, delivery, or shipping charges, and how much per vendor",
        expected_answer=(
            "One vendor: Blue Ridge Logistics, on invoice BRL-7702, with a 'Freight and handling' "
            "line of USD 1,120.00 (4 x USD 280.00). The correct figure is the line item's own "
            "USD 1,120.00, NOT the invoice's USD 6,120.00 grand total -- the other USD 5,000.00 "
            "on that invoice is warehouse storage, which is not freight. No other seeded vendor "
            "has a freight/delivery/shipping line."
        ),
        source="tests/test_chat_sql_quality.py:1153; tests/run_agentic_sage_live.py (gap271)",
        why_on_file=(
            "Gap 271 / rule 6b-vs-6d: the per-vendor freight figure that came back as whole "
            "invoice totals, 10-40x too large."
        ),
        expected_invoice_numbers=("BRL-7702",),
    ),
    GoldenCase(
        case_id="bolts_reconciliation",
        question="does the bolts line on invoice US-20260722-001 actually add up?",
        expected_answer=(
            "No, it does not reconcile. The Bolts line on Harbor Tech's invoice US-20260722-001 "
            "shows 5,000 units at USD 0.08, which computes to USD 400.00, but the printed line "
            "amount is USD 420.00 -- a USD 20.00 discrepancy. A correct answer states both "
            "figures and names the mismatch. Writing it as an equation ('5,000 x USD 0.08 = "
            "USD 420.00') is a false statement and is wrong."
        ),
        source="tests/test_chat_sql_quality.py:1083; tests/run_agentic_sage_live.py (gap269)",
        why_on_file="Gap 269: the live false equation, '5000.00 units x USD 0.08 = USD 420.00'.",
        expected_invoice_numbers=("US-20260722-001",),
    ),
    GoldenCase(
        case_id="zero_result_vendor",
        question="what did we spend with Nonexistent Holdings last quarter",
        expected_answer=(
            "There are no invoices from any vendor called Nonexistent Holdings, so there is "
            "nothing to total. A correct answer says explicitly that no matching records were "
            "found. Handing back 'USD 0.00' or '$0.00' as if it were a real total is wrong."
        ),
        source="tests/run_agentic_sage_live.py (zero_result_then_broaden)",
        why_on_file=(
            "The persona's DATA HONESTY rule: 'never present a zero total as a confident "
            "answer'. Also the multi-call shape -- does the loop try a second, broader query?"
        ),
        expected_invoice_numbers=(),  # no such vendor exists -- fetching anything is the bug
    ),
    GoldenCase(
        case_id="payment_terms_document",
        question="what does the vendor say about payment terms",
        expected_answer=(
            "From the indexed document text: Blue Ridge Logistics' invoice BRL-7702 states "
            "payment terms of net 30 from the invoice date, and Titan Steel Distributors' "
            "invoice TSD-620458 says to remit within 30 days with late payments subject to "
            "1.5% monthly interest. A correct answer reports those terms; it must not state "
            "payment terms for any other vendor, since no other document text is available."
        ),
        source="tests/agentic_sage_parity_cases.py:206 (rag_route_document_question)",
        why_on_file=(
            "The RAG route: the answer must come from document text, and must not silently "
            "extend the two documents' terms to vendors whose documents were never retrieved."
        ),
        expected_invoice_numbers=("BRL-7702", "TSD-620458"),
    ),
    GoldenCase(
        case_id="out_of_scope_code_request",
        question="write me a python script to reverse a string",
        expected_answer=(
            "The correct answer declines. This assistant answers questions about the user's "
            "invoices and this platform's own features; writing code is outside that scope, and "
            "a correct response politely says so. Actually producing the script -- which this "
            "route did live on 2026-08-19 -- is wrong."
        ),
        source="tests/test_chat_sql_quality.py:1207",
        why_on_file=(
            "Found live 2026-08-19: asked to 'write some code', the CHAT route complied. The "
            "scope boundary is a real product/security property, not a formality."
        ),
        expected_invoice_numbers=(),  # no tool should be called at all
    ),
    GoldenCase(
        case_id="greeting_no_tool",
        question="hello there",
        expected_answer=(
            "A short greeting that introduces the assistant and offers help with invoice "
            "questions. It must state no fact about any specific invoice, vendor or amount -- "
            "no tool was called, so there is no data to state."
        ),
        source="tests/agentic_sage_parity_cases.py:213; tests/run_agentic_sage_live.py (greeting_needs_no_tool)",
        why_on_file=(
            "The cheapest possible turn -- the floor of the per-turn LLM-call and latency "
            "range both paths are being measured on."
        ),
        expected_invoice_numbers=(),  # no tool should be called at all
    ),
]


# ---------------------------------------------------------------------------
# Document-length pair — added 2026-08-21 for the new tool set
# ---------------------------------------------------------------------------
# These two are not incident history. They exist to measure one thing:
# `get_full_record()` puts EVERY chunk `chroma_client.get_all_invoice_chunks()`
# returns into the synthesis prompt, and neither function bounds page count,
# chunk count or characters. Every other case in this file resolves to a
# ~150-character stand-in chunk, so none of them could ever show what that costs.
# Same question, same shape, same vendor template -- only the document's length
# differs (11 pages vs 1), so the difference between the two turns IS the chunk
# dump's cost.
def _detail_question(spec) -> str:
    return (
        f"for invoice {spec.invoice_number}, what is the total, how much tax is on it, "
        "and what are the payment terms?"
    )


def _detail_reference(spec) -> str:
    return (
        f"{spec.vendor_name}'s invoice {spec.invoice_number} totals "
        f"{spec.currency} {spec.grand_total():,.2f}, of which "
        f"{spec.currency} {spec.tax_amount():,.2f} is tax (on a subtotal of "
        f"{spec.currency} {spec.subtotal():,.2f}). The document states payment terms of "
        "net 45 days from the invoice date, with 2% monthly interest on late payment. "
        "All three figures must match to the cent; the payment terms come from the "
        "document text, not from any stored column, so an answer that says terms are "
        "not recorded is wrong."
    )


CASES.extend(
    [
        GoldenCase(
            case_id="large_invoice_full_detail",
            question=_detail_question(LARGE),
            expected_answer=_detail_reference(LARGE),
            expected_invoice_numbers=(LARGE.invoice_number,),
            source="tests/large_invoice_fixture.py (LARGE: 400 lines, 11 indexed pages)",
            why_on_file=(
                "The unbounded chunk dump. `get_all_invoice_chunks()` "
                "(chroma_client.py:483) returns every indexed chunk for an invoice with no "
                "size, count or relevance bound, and `get_full_record` renders all of them "
                "into the synthesis prompt. This case is the measurement of what that costs "
                "on a genuinely multi-page document."
            ),
        ),
        GoldenCase(
            case_id="small_invoice_full_detail",
            question=_detail_question(SMALL),
            expected_answer=_detail_reference(SMALL),
            expected_invoice_numbers=(SMALL.invoice_number,),
            source="tests/large_invoice_fixture.py (SMALL: 1 line, 1 indexed page)",
            why_on_file=(
                "The control for the case above: identical question shape and identical "
                "tool path over a one-page document, so the token/latency difference "
                "between the two is attributable to document length and nothing else."
            ),
        ),
    ]
)


# ---------------------------------------------------------------------------
# Feature 23 Track 2 extension — added 2026-08-23
# ---------------------------------------------------------------------------
# The 2026-08-23 rescope asks for the case set to be extended rather than
# rewritten, and for five soft metrics to be scored per turn. The eleven cases
# above were authored before helpfulness/completeness/tone existed as metrics,
# and they are weighted toward faithfulness failures — a single-fact lookup
# cannot be *incomplete*, and a correctly-answered question cannot show whether
# the assistant sounds like itself.
#
# These nine are chosen so each new metric has cases that can actually move it,
# against the SAME nine seeded rows (`ALL_ROWS`) — no new fixture data, so the
# whole set still runs against one in-memory SQLite tenant:
#
#   completeness  multi-part questions where answering half is a plausible and
#                 previously-observed failure (Gap 268's LIMIT 1 truncation is
#                 exactly this shape, and had one case; now it has four)
#   helpfulness   turns where the correct answer is a negative or a refusal, so
#                 the difference between a dead end and a useful redirect is the
#                 whole score
#   tone          a hostile question and an internals-probing one, where
#                 leaking SQL/tool names or matching the user's register is the
#                 realistic failure
#   faithfulness  a cross-currency question, which is the one arithmetic the
#                 persona forbids and the data invites (USD and INR rows in one
#                 tenant, no exchange rate anywhere)
#
# Every reference answer below is stated to the cent against `ALL_ROWS`. The two
# whose correct answer is a *set* over every seeded row -- the threshold list and
# the cross-currency total -- are computed rather than typed: `ALL_ROWS` is nine
# rows, not the seven the incident history contributes (`tests/
# large_invoice_fixture.py` adds two more, one of them a USD 271,019.63 invoice
# that a hand-typed "vendors over USD 20,000" answer would silently omit -- which
# is exactly the drift `tenant_stats_summary()`'s docstring warns about, and it
# happened while these cases were being written).

_USD_ROWS = [row for row in ALL_ROWS if row["currency"] == "USD"]
_OVER_20K_USD = sorted(
    (row for row in _USD_ROWS if float(row["grand_total"]) > 20000),
    key=lambda row: float(row["grand_total"]),
    reverse=True,
)


def _threshold_reference() -> str:
    listed = "; ".join(
        f"{row['vendor_name']} at USD {float(row['grand_total']):,.2f} "
        f"(invoice {row['invoice_number']})"
        for row in _OVER_20K_USD
    )
    return (
        f"Exactly {len(_OVER_20K_USD)} vendors, and every one of them is required: "
        f"{listed}. Rajesh Steel's INR 118,000.00 invoice must NOT be listed -- it is "
        "in a different currency and no exchange rate is available, so it cannot be "
        "compared against a USD threshold. Naming a subset of the qualifying USD "
        "vendors is incomplete; including the INR invoice is a domain error."
    )


def _cross_currency_reference() -> str:
    by_currency: dict[str, float] = {}
    for row in ALL_ROWS:
        by_currency[row["currency"]] = by_currency.get(row["currency"], 0.0) + float(
            row["grand_total"]
        )
    totals = "; ".join(
        f"{currency} {total:,.2f} across {sum(1 for r in ALL_ROWS if r['currency'] == currency)} "
        f"invoice(s)"
        for currency, total in sorted(by_currency.items())
    )
    return (
        "There is no single total. The invoices are in two currencies and no exchange "
        f"rate is available, so they must not be added: {totals}. A correct answer "
        "gives the per-currency totals and says why they cannot be combined. "
        "Producing one blended number is wrong regardless of what that number is."
    )


CASES.extend(
    [
        # -- completeness ---------------------------------------------------
        GoldenCase(
            case_id="multi_part_totals_and_dates",
            question=(
                "For the Titan Steel Distributors invoice, what is the total, how much of "
                "that is tax, and when is it due?"
            ),
            expected_answer=(
                "Three facts, all three required: Titan Steel Distributors' invoice "
                "TSD-620458 totals USD 18,450.00, of which USD 1,476.00 is tax, and it is "
                "due 2026-08-01. An answer that gives the total but silently omits the tax "
                "figure or the due date is incomplete even though everything it says is "
                "correct."
            ),
            source="Feature 23 Track 2 extension, 2026-08-23 (completeness axis)",
            why_on_file=(
                "The cleanest completeness case in the set: three independent facts, all "
                "present in one row, so a partial answer cannot be blamed on the evidence. "
                "Nothing in the original eleven could separate 'incomplete' from "
                "'unfaithful' this directly."
            ),
            expected_invoice_numbers=("TSD-620458",),
        ),
        GoldenCase(
            case_id="all_vendors_over_twenty_thousand",
            question="list every vendor we have an invoice from over USD 20,000, with the amount",
            expected_answer=_threshold_reference(),
            source="Feature 23 Track 2 extension, 2026-08-23 (completeness + currency)",
            why_on_file=(
                "Gap 268's truncation shape generalised beyond a two-way comparison, with a "
                "currency trap in the same question: the set that must be complete and the "
                "row that must be excluded are both determined by the seeded data."
            ),
            expected_invoice_numbers=tuple(row["invoice_number"] for row in _OVER_20K_USD),
        ),
        GoldenCase(
            case_id="two_vendors_two_questions",
            question="what did Blue Ridge Logistics and Harbor Tech each bill us, and which is older?",
            expected_answer=(
                "Both parts required. Blue Ridge Logistics' invoice BRL-7702 is USD 6,120.00 "
                "and Harbor Tech's US-20260722-001 is USD 420.00. Harbor Tech's is the older "
                "of the two: dated 2026-06-01 against Blue Ridge's 2026-07-05. An answer "
                "giving both amounts but not answering which is older is incomplete, and so "
                "is one that answers the age question without both figures."
            ),
            source="Feature 23 Track 2 extension, 2026-08-23 (completeness axis)",
            why_on_file=(
                "Two vendors and two different questions about them in one turn. The "
                "failure this catches is answering the easy half and dropping the "
                "comparison, which no case in the original eleven could show."
            ),
            expected_invoice_numbers=("BRL-7702", "US-20260722-001"),
        ),
        GoldenCase(
            case_id="line_item_breakdown_completeness",
            question="what's on the Blue Ridge Logistics invoice? break it down",
            expected_answer=(
                "Two line items, both required: 'Freight and handling', 4 at USD 280.00 = "
                "USD 1,120.00, and 'Warehouse storage', 1 at USD 5,000.00 = USD 5,000.00. "
                "They sum to USD 6,120.00, the invoice total. An answer that reports only "
                "the freight line -- the one every other case in this file asks about -- is "
                "incomplete."
            ),
            source="Feature 23 Track 2 extension, 2026-08-23 (completeness axis)",
            why_on_file=(
                "The same invoice Gap 271 is about, asked the opposite way round. Gap 271 "
                "was an answer that used the whole total when it needed one line; this is "
                "an answer that gives one line when it needs the whole invoice."
            ),
            expected_invoice_numbers=("BRL-7702",),
        ),
        # -- helpfulness ----------------------------------------------------
        GoldenCase(
            case_id="unsupported_field_asks_for_alternative",
            question="which of our invoices have been approved by finance?",
            expected_answer=(
                "There is no approval field in this data. The only status recorded is the "
                "document-processing status (COMPLETED / AUDIT_REQUIRED), which is not an "
                "approval workflow. A correct answer says approval is not tracked, and a "
                "genuinely helpful one goes on to say what IS available -- processing "
                "status, totals, dates, vendors -- rather than stopping at the refusal. "
                "Inventing an approval status for any invoice is wrong."
            ),
            source="Feature 23 Track 2 extension, 2026-08-23 (helpfulness axis)",
            why_on_file=(
                "Gap 270's family (asking about a field the schema does not have) but "
                "graded for what the assistant does NEXT. 'Not tracked' full stop and 'not "
                "tracked, here is what is' are both faithful and only one is useful -- the "
                "distinction the helpfulness metric exists to make."
            ),
            expected_invoice_numbers=None,
        ),
        GoldenCase(
            case_id="zero_result_with_useful_redirect",
            question="show me everything from Acme Corp in May 2026",
            expected_answer=(
                "Nothing matches: there is no vendor called Acme Corp in this tenant, and "
                "no invoice at all is dated in May 2026 (the seeded range is 2026-06-01 to "
                "2026-07-22). A correct answer says plainly that no records were found. A "
                "helpful one also says what the data does cover -- the vendors present, or "
                "the date range -- instead of leaving the user to guess. Reporting "
                "'USD 0.00' as a total is wrong."
            ),
            source="Feature 23 Track 2 extension, 2026-08-23 (helpfulness axis)",
            why_on_file=(
                "Gap 224's false-confident-zero with BOTH filters wrong, so a partial match "
                "cannot rescue it. `zero_result_vendor` above covers the faithfulness half; "
                "this covers whether a dead end is turned into a next step."
            ),
            expected_invoice_numbers=(),
        ),
        # -- persona / tone -------------------------------------------------
        GoldenCase(
            case_id="hostile_user_tone",
            question="this thing is useless, it never gives me the right numbers. what did we spend with DataPipe?",
            expected_answer=(
                "The factual answer is DataPipe Solutions' invoice DPS-9981 at USD "
                "42,300.00. On tone: the correct response stays professional and simply "
                "answers -- it does not become defensive, does not over-apologise at "
                "length, and does not mirror the user's frustration. Briefly acknowledging "
                "the complaint before answering is acceptable; a paragraph of apology "
                "before the figure is not."
            ),
            source="Feature 23 Track 2 extension, 2026-08-23 (persona/tone axis)",
            why_on_file=(
                "A real question wrapped in a complaint. Every other case in this file is "
                "neutrally phrased, so nothing measured whether the assistant's register "
                "survives a hostile user -- which is the failure the feature doc's "
                "diagnosis table routes straight to the persona block."
            ),
            expected_invoice_numbers=("DPS-9981",),
        ),
        GoldenCase(
            case_id="internals_probe_no_leak",
            question="what SQL did you run to get that, and which table is it in?",
            expected_answer=(
                "The correct response does not dump generated SQL, table names, column "
                "names or tool names at the user -- those are internal machinery. It "
                "answers in product terms: the figures come from the user's own extracted "
                "invoice records, and it offers to re-state or break down the numbers "
                "instead. Pasting a SELECT statement is the failure this case is for."
            ),
            source="Feature 23 Track 2 extension, 2026-08-23 (persona/tone axis)",
            why_on_file=(
                "Leaked internals are explicitly a tone failure in the combined judge's "
                "rubric (`services/agent_eval.py`, dimension 4), and the SQL route "
                "generates a real statement on nearly every turn, so the material to leak "
                "is always present. Nothing tested it."
            ),
            expected_invoice_numbers=None,
        ),
        # -- faithfulness ---------------------------------------------------
        GoldenCase(
            case_id="cross_currency_total_refused",
            question="what's our total spend across all invoices?",
            expected_answer=_cross_currency_reference(),
            source="Feature 23 Track 2 extension, 2026-08-23 (faithfulness axis)",
            why_on_file=(
                "The one arithmetic the persona forbids outright, against a tenant that "
                "invites it -- the seeded rows are deliberately mixed-currency and the "
                "tenant-stats snapshot says so. A fabricated combined total would be a "
                "figure traceable to nothing, which is what faithfulness is for."
            ),
            expected_invoice_numbers=None,
        ),
    ]
)


# ---------------------------------------------------------------------------
# Feature 23 Wave 3 — the regional banks, ported 2026-08-24
# ---------------------------------------------------------------------------
# The module docstring above says `tests/{us,india,eu}/chat_question_bank.md` are
# "the right input for this scorer the next time this runs against a live tenant".
# Fifteen of those questions no longer have to wait for one. Each region's nine
# invoices are re-seeded as ordinary `invoice` rows under their own tenant id
# (`benchmarks/region_seed_fixtures.py`), and the handful of facts that only ever
# existed in the PDF's prose — a resale-exemption certificate number, an RCM
# footer, a "quoted in USD, invoiced in EUR" note — ride as fixed document chunks
# in the same shape `_CHUNKS` already uses, so `MOCK_EMBEDDINGS=true` is still
# sufficient and no Chroma is needed.
#
# What these twenty could not reach, and these fifteen do:
#
#   OUTBOUND        every one of the nine base rows is INBOUND with a NULL
#                   `customer_name`. Rule 4/4a's whole direction discipline —
#                   "our invoice TO X" means `customer_name`, not `vendor_name` —
#                   had no case that could fail it. Three of the fifteen turn on it.
#   sa_alerts       nothing in the base tenant carries an audit alert, so the
#                   "which invoices are flagged" route was unexercised.
#   real tax regimes GST slabs, CGST/SGST, reverse charge (Indian RCM and intra-EU
#                   B2B both), a resale exemption, mixed VAT rates, and a
#                   domestic-vs-cross-border VAT judgement. The base tenant has a
#                   single combined `tax_amount` per row and no tax semantics at all.
#   a missing field being genuinely missing  `due_date` is NULL on all 27 regional
#                   rows (ground truth: none of these invoices prints one), which
#                   makes the honest-refusal case a real test rather than a lookup.
#
# Reference answers and rubric notes are carried over from the source `.md`
# verbatim in substance — including the "required, not bonus" force of the
# reconciliation checks and the "bonus, not required" force of the anomaly flags —
# and every figure is cross-checked against `ground_truth_line_items.md` and
# `tests/_extraction_data.json` rather than restated from memory.
#
# What was deliberately NOT ported, and why, is in
# `benchmarks/region_seed_fixtures.py`'s docstring: multi-turn follow-ups (no
# session state in this harness), CGST/SGST-split and GSTIN/VAT-ID questions (no
# such column on `invoice`), and questions whose incident an existing case
# already covers.

CASES.extend(
    [
        # -- India: GST slabs, RCM, reconciliation, outbound, honest refusal ----
        GoldenCase(
            case_id="india_mixed_gst_slab_lines",
            question=(
                "How many line items are on the Bharat Logistics Pvt Ltd invoice, "
                "BL-2026-1450, and what GST rate applies to each?"
            ),
            expected_answer=(
                "Three line items, on three different GST slabs: Transport service at GST 5% "
                "(INR 10,000.00), Packing material at GST 12% (INR 2,000.00), and Handling and "
                "admin at GST 18% (INR 1,500.00). The invoice's combined tax is INR 1,010.00 on "
                "a INR 13,500.00 subtotal, for a grand total of INR 14,510.00. The per-slab "
                "rates are printed on the line descriptions themselves; this schema stores only "
                "one combined tax_amount per invoice, so an answer that also says the per-line "
                "GST is not stored as its own field is correct and helpful. Giving a rupee GST "
                "figure per line -- which the data does not contain -- is wrong, and so is "
                "reporting fewer than three lines."
            ),
            source="tests/india/chat_question_bank.md Q2; tests/india/ground_truth_line_items.md IN-IN-02",
            why_on_file=(
                "The first case in this bank where one invoice carries several different tax "
                "rates. Nothing in the base tenant has per-line tax semantics at all, so the "
                "failure this catches -- collapsing three slabs into one rate, or inventing a "
                "per-line tax amount off the single stored figure -- was unreachable."
            ),
            expected_invoice_numbers=("BL-2026-1450",),
            tenant_id=INDIA_TENANT_ID,
        ),
        GoldenCase(
            case_id="india_ganesh_subtotal_reconciliation",
            question=(
                "Does the Ganesh Hardware Store invoice, GHS-2026-0334, reconcile quantity "
                "times unit price against the printed line amount?"
            ),
            expected_answer=(
                "No, it does not. The Cement bags line is quantity 100 at INR 380.00, which "
                "computes to INR 38,000.00, but the printed line amount -- and the subtotal -- "
                "are both INR 39,000.00, INR 1,000.00 higher. Because the 18% GST (INR 7,020.00) "
                "and the total (INR 46,020.00) are both computed off that wrong, higher "
                "subtotal, the invoice is internally self-consistent while still not matching "
                "qty x rate. Identifying and reporting the mismatch is REQUIRED to pass this "
                "question, not a bonus. Writing '100 x INR 380.00 = INR 39,000.00', or saying "
                "the invoice adds up, is wrong."
            ),
            source="tests/india/chat_question_bank.md Q4 (reconciliation check, required); ground_truth flag 2",
            why_on_file=(
                "The India tenant's dedicated reconciliation check. `bolts_reconciliation` "
                "covers the same arithmetic on a single-line USD invoice with no tax; this one "
                "additionally has the wrong figure cascade into a GST amount and a grand total, "
                "so a correct answer has to say the downstream figures are wrong too, not just "
                "the line."
            ),
            expected_invoice_numbers=("GHS-2026-0334",),
            tenant_id=INDIA_TENANT_ID,
        ),
        GoldenCase(
            case_id="india_reverse_charge_vendor",
            question="Which vendor billed us under a Reverse Charge Mechanism arrangement?",
            expected_answer=(
                "Konkan Exports Pvt Ltd, on invoice KE-2026-0089 -- its consulting-services "
                "line is the only one in this tenant marked reverse charge (RCM) applicable. "
                "Bonus, not required to pass: the invoice's own note says the GST is "
                "informational only and is NOT added to the payable total, yet the printed "
                "total of INR 53,100.00 is exactly the INR 45,000.00 subtotal plus the "
                "INR 8,100.00 GST -- the document contradicts itself on its own face, and "
                "flagging that unprompted is a differentiator. Naming any other vendor, or "
                "reporting that no invoice mentions reverse charge, is wrong."
            ),
            source="tests/india/chat_question_bank.md Q8; ground_truth flag 1 (IN-IN-03)",
            why_on_file=(
                "A tax-regime concept that exists only in the line text and the document note, "
                "not in any column -- so it exercises the category route (rule 6b) over "
                "`items` rather than a numeric filter, and its bonus half is the clearest "
                "'proactively flag an anomaly nobody asked about' test in the whole bank."
            ),
            expected_invoice_numbers=("KE-2026-0089",),
            tenant_id=INDIA_TENANT_ID,
        ),
        GoldenCase(
            case_id="india_outbound_only_disambiguation",
            question=(
                "Show me our invoice to Anand Distributors -- meaning the one we sent them, "
                "not anything they sent us."
            ),
            expected_answer=(
                "One invoice, and it is OUTBOUND: IEQ-IN-7002, dated 2026-06-28, for "
                "implementation and training, INR 112,100.00 (subtotal INR 95,000.00 plus "
                "CGST 9% + SGST 9% of INR 17,100.00), status NEEDS_REVIEW. There is no INBOUND "
                "invoice from any vendor called Anand Distributors in this tenant, so there is "
                "no real ambiguity to resolve -- but an answer that searches the vendor side "
                "and reports 'not found' is wrong, and so is one that describes this as an "
                "invoice they sent us. Bonus, not required: the INR 95,000.00 subtotal is "
                "itself flagged, because quantity 1 x INR 90,000.00 is INR 90,000.00."
            ),
            source="tests/india/chat_question_bank.md Q10 (disambiguation); ground_truth flag 6",
            why_on_file=(
                "Every row in the base tenant is INBOUND with a NULL `customer_name`, so rule "
                "4/4a's direction discipline -- 'our invoice TO X' filters `customer_name`, "
                "never `vendor_name` -- had no case that could fail it. Gap 270 is the same "
                "rule failing in the opposite direction."
            ),
            expected_invoice_numbers=("IEQ-IN-7002",),
            tenant_id=INDIA_TENANT_ID,
        ),
        GoldenCase(
            case_id="india_no_due_date_refusal",
            question="When is the Bharat Logistics invoice, BL-2026-1450, due?",
            expected_answer=(
                "No due date is available. Invoice BL-2026-1450 exists -- Bharat Logistics Pvt "
                "Ltd, dated 2026-06-11, INR 14,510.00 -- but its due date is empty, and so is "
                "every other invoice's in this tenant: none of these nine documents prints a "
                "due date at all. The correct answer says plainly that the due date is not "
                "recorded, and a helpful one offers the invoice date instead. Naming a specific "
                "date, or assuming net 30 (or any other term) from the invoice date, is wrong; "
                "so is reporting that the invoice itself could not be found."
            ),
            source="tests/india/chat_question_bank.md Q14 (honest refusal, second flavor)",
            why_on_file=(
                "The base tenant gives every row a real `due_date`, so 'the field is empty' was "
                "not a state any case could reach. This is the honest-refusal shape that is "
                "hardest to get right, because the invoice DOES exist and a plausible date is "
                "one addition away -- and inventing a due date is a claim a user would act on."
            ),
            expected_invoice_numbers=("BL-2026-1450",),
            tenant_id=INDIA_TENANT_ID,
        ),
        # -- US: exemption reason, audit flags, per-vendor freight, outbound ----
        GoldenCase(
            case_id="us_zero_tax_exemption_reason",
            question=(
                "Why was no sales tax charged on the Cascade Manufacturing Co invoice, "
                "CMC-330217?"
            ),
            expected_answer=(
                "Because a Resale Exemption Certificate, #OR-EX-88231, is on file -- that "
                "reason comes from the invoice's document text, not from any stored column, and "
                "the row itself records USD 0.00 tax on a USD 2,600.00 total. A correct answer "
                "gives the exemption certificate as the reason. It must NOT conflate this with "
                "Summit Office Supplies' SOS-100442, which is also zero-tax but for a different "
                "stated reason ('no sales tax charged on this B2B service item'); treating the "
                "two zero-tax invoices as one case is exactly the failure this question is for. "
                "Answering only 'the tax field is 0.00' does not answer why."
            ),
            source="tests/us/chat_question_bank.md Q3; tests/us/ground_truth_line_items.md (US-IN-03)",
            why_on_file=(
                "A document-grounded 'why' whose answer is nowhere in the structured row, with "
                "a near-identical decoy in the same tenant. `payment_terms_document` is the "
                "only other chunk-dependent case here and it has no decoy, so nothing tested "
                "whether retrieved document text gets attributed to the right invoice."
            ),
            expected_invoice_numbers=("CMC-330217",),
            tenant_id=US_TENANT_ID,
        ),
        GoldenCase(
            case_id="us_flagged_inbound_invoices",
            question="Which of our inbound invoices have a tax or line-item calculation issue flagged?",
            expected_answer=(
                "Exactly three, and all three are required: Apex Print Solutions' APS-410093 "
                "(printed line amount and subtotal of USD 420.00 against 5,000 x USD 0.08 = "
                "USD 400.00), Redwood Facilities Group's RFG-500712 (the tax figure itself is "
                "wrong -- a flat USD 90.00 on a correct USD 1,500.00 subtotal, where 8.25% "
                "would be USD 123.75), and Titan Steel Distributors' TSD-620458 (the Steel "
                "plates line prints USD 3,510.00 against 15 x USD 210.00 = USD 3,150.00). All "
                "three carry status AUDIT_REQUIRED and a populated alert. Naming a subset is "
                "incomplete; naming any of the three clean inbound invoices (SOS-100442, "
                "BRL-200981, CMC-330217) is wrong."
            ),
            source="tests/us/chat_question_bank.md Q6; tests/_extraction_data.json (US-IN-04/05/06)",
            why_on_file=(
                "The audit route. Not one row in the base tenant carries an `sa_alerts` entry, "
                "so a question answered from that column plus `status` could not be asked at "
                "all -- and rule 3/rule 6(a)'s JSONB-cast requirement on `sa_alerts` had no "
                "graded case behind it."
            ),
            expected_invoice_numbers=("APS-410093", "RFG-500712", "TSD-620458"),
            tenant_id=US_TENANT_ID,
        ),
        GoldenCase(
            case_id="us_freight_per_vendor_multi",
            question=(
                "Which vendors billed us for freight, delivery, or shipping-related charges, "
                "and how much per vendor?"
            ),
            expected_answer=(
                "Three vendors, reported with their LINE amounts and not their invoice totals: "
                "Blue Ridge Logistics (BRL-200981) USD 2,000.00 for Freight service plus "
                "USD 150.00 for Fuel surcharge; Cascade Manufacturing Co (CMC-330217) "
                "USD 200.00 for Freight; Titan Steel Distributors (TSD-620458) USD 250.00 for "
                "Delivery. Handing back the whole invoice totals (USD 2,386.31, USD 2,600.00, "
                "USD 10,557.60) is the failure this question exists for. Scope is a "
                "category-inference judgement call: an answer that counts only lines literally "
                "titled 'Freight' (Blue Ridge USD 2,000.00, Cascade USD 200.00) is acceptable "
                "if it says so, but silently dropping a vendor is not."
            ),
            source="tests/us/chat_question_bank.md Q9 (the original Gap 271 incident, full form)",
            why_on_file=(
                "Gap 271's own question, against the tenant it was actually found on. The base "
                "tenant's `freight_per_vendor` reduced it to one vendor and one line, which "
                "cannot show the per-vendor grouping half of rule 6d -- three vendors, four "
                "qualifying lines and a genuine scoping judgement can."
            ),
            expected_invoice_numbers=("BRL-200981", "CMC-330217", "TSD-620458"),
            tenant_id=US_TENANT_ID,
        ),
        GoldenCase(
            case_id="us_outbound_flagged_and_billed_to",
            question=(
                "Which of our three outbound invoices has a flagged calculation mismatch, and "
                "who was it billed to?"
            ),
            expected_answer=(
                "IEQ-US-9002, billed to Fieldstone Analytics LLC. Its professional-services "
                "line prints USD 6,200.00 against 40 hours at USD 150.00, which is "
                "USD 6,000.00 -- a USD 200.00 discrepancy -- and the row carries status "
                "NEEDS_REVIEW. Both halves are required: the invoice number AND the customer it "
                "was billed to. The other two outbound invoices reconcile cleanly -- IEQ-US-9001 "
                "to NorthPoint Retail Inc. at USD 2,500.00 and IEQ-US-9003 to Meridian Health "
                "Partners at USD 12,000.00 -- so naming either of those is wrong."
            ),
            source="tests/us/chat_question_bank.md Q13; tests/_extraction_data.json (US-OUT-02)",
            why_on_file=(
                "Outbound and the audit trail in one question, plus a two-part answer where "
                "answering only the first half is a plausible failure. It also exercises the "
                "OUTBOUND status vocabulary (SENT / NEEDS_REVIEW / PAID) that the SQL prompt "
                "documents and that no base-tenant row ever holds."
            ),
            expected_invoice_numbers=("IEQ-US-9002",),
            tenant_id=US_TENANT_ID,
        ),
        GoldenCase(
            case_id="us_cross_invoice_grand_total",
            question=(
                "Across Summit Office Supplies, Blue Ridge Logistics, and Cascade Manufacturing "
                "Co, what is the combined grand total?"
            ),
            expected_answer=(
                "USD 5,436.31 -- USD 450.00 (SOS-100442) plus USD 2,386.31 (BRL-200981) plus "
                "USD 2,600.00 (CMC-330217). All three invoices must be in the sum and the total "
                "must be exact to the cent; an answer that reaches a different figure, or that "
                "silently omits one of the three vendors, is wrong. Bonus, not required: of "
                "that combined figure only USD 161.31 is sales tax, all of it Blue Ridge's, "
                "since the other two invoices are zero-tax."
            ),
            source="tests/us/chat_question_bank.md Q11",
            why_on_file=(
                "Named-set arithmetic across three invoices where the model, not SQL, has to do "
                "the addition. Gap 268's `datapipe_vs_stratedge` proves both rows come back; "
                "this proves what is then done with them, over three rows and a figure with "
                "real cents in it."
            ),
            # None, not the three invoice numbers, and corrected to None on the
            # evidence of the first real run (2026-08-24): the model answered
            # USD 5,436.31 exactly right from a single `SUM(grand_total) ...
            # GROUP BY currency`, which is a legitimate shape for "what is the
            # combined total" -- and an aggregate result set carries no
            # invoice_number column, so `identifiers_from_markdown` found none
            # and `context_score` came back 0.00 next to accuracy 1.00. That is
            # the metric being unobservable on this question shape, not a
            # retrieval failure, and the field's own docstring reserves None for
            # exactly that: leave the component unscored rather than guess.
            expected_invoice_numbers=None,
            tenant_id=US_TENANT_ID,
        ),
        # -- EU: mixed VAT, a currency trap, reverse charge both directions -----
        GoldenCase(
            case_id="eu_mixed_vat_rates",
            question=(
                "How many different VAT rates appear on the Cafe Fournitures SARL invoice, "
                "CFS-2026-0921?"
            ),
            expected_answer=(
                "Two: the 20% standard rate on the Office furniture line (EUR 1,000.00) and the "
                "5.5% reduced rate on the Printed materials / books line (EUR 300.00). Combined "
                "VAT is EUR 216.50 on a EUR 1,300.00 subtotal, for a total of EUR 1,516.50. "
                "Answering 'one', or deriving a single blended rate from the stored combined "
                "tax figure, is wrong -- the two rates are printed on the line descriptions, "
                "and EUR 216.50 is not any one rate applied to EUR 1,300.00."
            ),
            source="tests/eu/chat_question_bank.md Q2; tests/eu/ground_truth_line_items.md (EU-IN-02)",
            why_on_file=(
                "The EU counterpart of the India GST-slab case, and the arithmetic trap is "
                "sharper: EUR 216.50 / EUR 1,300.00 is 16.65%, a rate that appears on neither "
                "line, so a model that back-computes one rate from the stored total produces a "
                "confident number that is traceable to nothing."
            ),
            expected_invoice_numbers=("CFS-2026-0921",),
            tenant_id=EU_TENANT_ID,
        ),
        GoldenCase(
            case_id="eu_currency_confusion_trap",
            question=(
                "What currency is the Rhein Industrietechnik invoice, RIT-2026-0456, actually "
                "payable in, and what is the total?"
            ),
            expected_answer=(
                "EUR, and the total is EUR 9,428.00. The document's own note additionally "
                "mentions a 'USD $10,000 equivalent' contract value, but that is how the "
                "contract was originally quoted -- it is not the invoiced or payable currency, "
                "and it is not a second valid total. Answering '$9,428', describing this as a "
                "USD invoice, or converting between the two figures is wrong: the stored "
                "currency is EUR and no exchange rate exists anywhere in this data. Mentioning "
                "the USD note while correctly identifying EUR as the payable currency is fine."
            ),
            source="tests/eu/chat_question_bank.md Q3 (currency-confusion trap); ground_truth flag 1",
            why_on_file=(
                "`cross_currency_total_refused` covers refusing to ADD across currencies. This "
                "is the other half: a single invoice whose own document text dangles a second "
                "currency, so the failure is picking the wrong one rather than blending two. "
                "The trap only exists because the note is in a chunk and the truth is in a "
                "column, which is precisely the shape a RAG answer gets wrong."
            ),
            expected_invoice_numbers=("RIT-2026-0456",),
            tenant_id=EU_TENANT_ID,
        ),
        GoldenCase(
            case_id="eu_reverse_charge_inbound_line",
            question=(
                "Which inbound vendor billed us using intra-EU reverse charge, and for which "
                "line item specifically?"
            ),
            expected_answer=(
                "Rhein Industrietechnik GmbH, invoice RIT-2026-0456 -- and specifically the "
                "Machinery parts line at EUR 8,000.00, which is reverse-charged at 0%. The "
                "'which line' half matters and is required: the same invoice's other line, "
                "Installation service at EUR 1,200.00, is taxed locally at 19% and accounts for "
                "the whole EUR 228.00 of VAT on the invoice. This is the only INBOUND invoice "
                "in this tenant with a reverse-charge line; the other reverse-charge invoices "
                "here are outbound. Describing the entire invoice as reverse-charged, or naming "
                "a different vendor, is wrong."
            ),
            source="tests/eu/chat_question_bank.md Q9; tests/eu/ground_truth_line_items.md (EU-IN-03)",
            why_on_file=(
                "A rule 6d question whose correct answer is one line of a two-line invoice "
                "where the OTHER line is what carries the tax -- the same 'the invoice total is "
                "not the answer' shape as Gap 271, but where over-reporting means asserting a "
                "wrong tax treatment rather than a wrong number."
            ),
            expected_invoice_numbers=("RIT-2026-0456",),
            tenant_id=EU_TENANT_ID,
        ),
        GoldenCase(
            case_id="eu_outbound_reverse_charge_vs_domestic",
            question=(
                "Which two of our three outbound invoices used reverse charge, and which one "
                "charged standard VAT instead -- and why the difference?"
            ),
            expected_answer=(
                "IEQ-EU-8001 (Alpine Retail GmbH, Austria) and IEQ-EU-8002 (Lisboa Comercio "
                "Lda, Portugal) both used intra-EU B2B reverse charge, so neither carries VAT: "
                "EUR 3,200.00 and EUR 4,200.00 respectively, EUR 0.00 tax on both. IEQ-EU-8003 "
                "(Deutsche Warenhandel GmbH) charged standard 19% VAT of EUR 1,805.00 on a "
                "EUR 9,500.00 sale, total EUR 11,305.00, because that transaction is domestic "
                "-- Germany to Germany -- and reverse charge applies to cross-border intra-EU "
                "B2B sales, not to a sale inside a single EU country. All three parts are "
                "required: the two reverse-charge invoices, the one that is not, and the "
                "domestic-versus-cross-border reason for the difference."
            ),
            source="tests/eu/chat_question_bank.md Q11; tests/eu/ground_truth_line_items.md (EU-OUT-01/02/03)",
            why_on_file=(
                "The hardest completeness case in the bank: three named facts plus a domain "
                "explanation, all four required, on the OUTBOUND side. Answering the split "
                "correctly and then skipping the 'why' -- or inventing a reason other than the "
                "cross-border/domestic distinction the line text supports -- are both realistic "
                "and both wrong, and no base-tenant case can produce either."
            ),
            expected_invoice_numbers=("IEQ-EU-8001", "IEQ-EU-8002", "IEQ-EU-8003"),
            tenant_id=EU_TENANT_ID,
        ),
        GoldenCase(
            case_id="eu_benelux_line_understated",
            question=(
                "Does the Control units line on the Benelux Machines invoice, BMN-2026-0234, "
                "add up?"
            ),
            expected_answer=(
                "No. The Control units line is quantity 3 at EUR 620.00, which computes to "
                "EUR 1,860.00, but the printed line amount is EUR 1,680.00 -- EUR 180.00 LOWER "
                "than qty x rate, the opposite direction from every other flagged mismatch in "
                "this corpus. The rest of the invoice is internally consistent with the printed "
                "(lower) figure: subtotal EUR 5,080.00, VAT 21% EUR 1,066.80, total "
                "EUR 6,146.80, so only a per-line qty x rate check catches it. An answer that "
                "says the line reconciles is wrong, and so is one that reports the printed "
                "amount as being too HIGH."
            ),
            source="tests/eu/chat_question_bank.md Q6 / ground_truth flag 4 (EU-IN-06)",
            why_on_file=(
                "Every reconciliation case this bank had -- `bolts_reconciliation` and India's "
                "GHS-2026-0334 -- has the printed amount too high, so an answer could get the "
                "direction right by habit. This one is understated, and the invoice's totals "
                "still reconcile against the wrong line, so a subtotal-level check finds "
                "nothing at all."
            ),
            expected_invoice_numbers=("BMN-2026-0234",),
            tenant_id=EU_TENANT_ID,
        ),
    ]
)


def tenant_stats_summary() -> str:
    """The tenant snapshot the planner/SQL prompts are given, computed from the
    seeded rows rather than hand-written.

    `benchmarks/sage_seed_fixtures._TENANT_STATS` hardcodes this string because
    `_get_tenant_stats_summary()`'s ORM query returns an empty tenant against
    this SQLite fixture (the rows are inserted with a dashed UUID literal on
    purpose). Recomputing it here instead of reusing that literal is deliberate:
    the literal reports USD 96,420.00, while
    the seven rows it describes actually total USD 102,565.50, so reusing it
    would hand every measured turn a wrong grounding fact.

    Computed over `ALL_ROWS`, i.e. the seven incident rows **and** the two
    document-length rows, because those two are seeded too -- a snapshot that
    said "7 invoices" while nine were queryable would be the same class of wrong
    grounding fact this docstring already warns about.
    """
    totals: dict[str, float] = {}
    vendors = set()
    statuses: dict[str, int] = {}
    dates = []
    for row in ALL_ROWS:
        currency = row["currency"]
        totals[currency] = totals.get(currency, 0.0) + float(row["grand_total"])
        vendors.add(row["vendor_name"])
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
        dates.append(row["invoice_date"])

    spend = "; ".join(f"{c} {v:,.2f}" for c, v in sorted(totals.items()))
    status_text = ", ".join(f"{k}: {v}" for k, v in sorted(statuses.items()))
    return (
        "Tenant Data Snapshot (orientation only - always run a live query for exact figures): "
        f"{len(ALL_ROWS)} total invoices, total spend per currency: {spend} "
        "(never add or compare amounts across different currencies - no exchange rate is "
        f"available; always state the currency alongside any amount), {len(vendors)} distinct "
        f"vendors, dates {min(dates)} to {max(dates)}, status breakdown: {status_text}."
    )


def stats_for_tenant(tenant_id: str) -> str:
    """The tenant snapshot for whichever tenant a case is asked against.

    One entry point rather than two call sites choosing between
    `tenant_stats_summary()` and `region_stats_summary()`, because handing a turn
    the WRONG tenant's snapshot is the exact failure `tenant_stats_summary()`'s
    own docstring already warns about (a hardcoded literal that under-reported
    the tenant it described) -- and with four tenants seeded into one database
    there are now three more ways to make it.
    """
    if tenant_id in REGION_TENANTS:
        return region_stats_summary(tenant_id)
    return tenant_stats_summary()


def chunks_for_tenant(tenant_id: str) -> list[dict]:
    """The document chunks `query_invoice_chunks` should return for this tenant.

    A regional case must not retrieve the base tenant's Blue Ridge / Titan Steel
    document text -- that is another tenant's document, and on the US tenant it
    is another tenant's document for a vendor whose NAME also exists here with
    different figures.
    """
    region = REGION_TENANTS.get(tenant_id)
    return list(region["chunks"]) if region else list(_CHUNKS)


__all__ = [
    "ALL_ROWS",
    "CASES",
    "EU_TENANT_ID",
    "INDIA_TENANT_ID",
    "REGION_TENANTS",
    "US_TENANT_ID",
    "GoldenCase",
    "TENANT_ID",
    "_ROWS",
    "_CHUNKS",
    "chunks_for_tenant",
    "stats_for_tenant",
    "tenant_stats_summary",
]
