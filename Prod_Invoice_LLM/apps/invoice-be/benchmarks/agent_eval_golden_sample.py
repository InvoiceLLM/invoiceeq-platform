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
`tests/run_agentic_sage_live.py` — the same seven incident-history invoices that
harness already seeds. Duplicating them would let the two drift.

`tests/us|india|eu/chat_question_bank.md` are the repo's *real* answer-bearing
question banks (question + reference answer + grading rubric, ~15 questions per
region). They are deliberately not used here: each needs its region's tenant
seeded into live Postgres with real Chroma embeddings (see
`tests/us/run_chat_live_test.py`'s docstring), and no local Postgres/Chroma/Redis
is running. They are the right input for this scorer the next time this runs
against a live tenant, and that is Feature 21 Phase 3's job.
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
            "There is no CGST figure stored. The Rajesh Steel invoice INDIA-20260722-003 records "
            "one combined tax_amount of INR 18,000.00 on a grand total of INR 118,000.00, with no "
            "per-component (CGST/SGST/IGST) breakdown anywhere in the data. A correct answer says "
            "the CGST component is not separately recorded and gives the combined INR 18,000.00 "
            "tax figure instead; it must not invent a CGST number (e.g. half of the total tax)."
        ),
        source="tests/test_chat_sql_quality.py:878; tests/run_agentic_sage_live.py (gap263)",
        why_on_file=(
            "Gaps 263/264: this schema stores one combined tax_amount, so a CGST lookup is "
            "guaranteed to find nothing -- and the live failure was a fabricated SGST/CGST split."
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


def tenant_stats_summary() -> str:
    """The tenant snapshot the planner/SQL prompts are given, computed from the
    seeded rows rather than hand-written.

    `tests/run_agentic_sage_live.py` hardcodes this string because
    `_get_tenant_stats_summary()`'s ORM query returns an empty tenant against
    this SQLite fixture (the rows are inserted with a dashed UUID literal on
    purpose -- see that file's docstring). Recomputing it here instead of
    reusing that literal is deliberate: the literal reports USD 96,420.00, while
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


__all__ = [
    "ALL_ROWS",
    "CASES",
    "GoldenCase",
    "TENANT_ID",
    "_ROWS",
    "_CHUNKS",
    "tenant_stats_summary",
]
