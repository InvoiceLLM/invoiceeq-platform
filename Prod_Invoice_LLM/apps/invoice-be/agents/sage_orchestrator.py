"""Feature 21 Phase 2 — the tool-calling orchestrator loop.

Behind `ENABLE_AGENTIC_SAGE` (default off). Nothing here runs for any tenant
until Phase 3's regression suite and live verification say it can; with the flag
off `run_query_agent()` is byte-for-byte the pipeline it was before this file
existed, and `tests/test_agentic_sage.py` proves that against a golden recorded
from the pre-Phase-2 code.

**What this replaces, and why the shape matters.** The live pipeline classifies a
question once into exactly one of SQL/RAG/CHAT, runs that one route, and asks a
single synthesis prompt to get everything right in one shot. Every rule this
product has had to patch -- rule 4a's direction guessing, 6b-vs-6d, the
payment-status guardrail, and the faithfulness mandate that got Feature 21
reverted -- is the same failure: several true instructions crammed into one
prompt, competing, with the newest one winning. That is not fixable by wording.

The loop below fixes it structurally in three places:

  1. **Tool choice replaces classification.** The model picks a tool, sees the
     tool's real `status`, and can pick again -- `identify_invoices` came back
     `no_results` so try `search_invoices`, or it found the row so fetch the full
     record, or the question was ambiguous all along so ask. A one-shot
     classifier has no second move; this does.
  1a. **Identify, then fetch.** The single-invoice case no longer goes through a
     hand-maintained column list at all: `identify_invoices` finds the row from
     six lookup columns and `get_full_record` returns the live ORM row in full.
     A column added to the schema tomorrow is answerable tomorrow, with no prompt
     edit -- which is the class of bug (Gaps 263/264/285) this rewrite exists for.
  2. **Synthesis only ever sees tool output.** `_synthesize_node()` builds a
     fresh prompt from `state["tool_results"]`, not from the planner's own
     earlier reasoning. There is no "don't speculate" mandate anywhere in it,
     because there is nothing in the prompt to speculate from -- which is the
     specific property the reverted design tried and failed to get from prose.
  3. **Arithmetic is computed before the answer is written.** Every total in the
     synthesis prompt comes from `compute()` (see `_grounded_arithmetic()`),
     already rendered as `"USD 400.00"` strings. The model quotes figures; it
     does not produce them. Gap 269's live false equation ("5000.00 units x USD
     0.08 = USD 420.00") is unrenderable from a `reconcile_line_items` result,
     so the failure is structurally absent rather than warned against.

**Tenant scoping.** Phase 1 flagged this and it is honoured here: `tenant_id` and
`db_session` are bound in `_ToolBox`, a closure over the authenticated request.
They are not tool arguments, do not appear in any schema the model sees, and the
model therefore cannot choose or influence them.

**Caching.** The agentic path deliberately neither reads nor writes the Redis
answer cache `run_query_agent()` uses. The two pipelines can answer the same
question differently, and a cache keyed only on `(tenant_id, normalized_query)`
would let one serve the other's answer the moment the flag moves in either
direction. Caching the agentic path is a Phase 3 decision with its own key.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from agents.query_agent import (
    MAX_SNAPSHOT_INVOICE_IDS,
    _business_rules_block,
    _chat_rules_block,
    _get_chat_style_block,
    _get_global_business_rules,
    _get_tenant_stats_summary,
    _get_vendor_business_rules,
    _payment_status_block_for,
    _wrap_user_input,
    get_chat_history,
    get_prior_turn_sql,
)
from agents.query_tools import (
    RECONCILE_LINE_ITEMS,
    SUM_BY_CURRENCY,
    aggregate,
    ask_clarifying_question,
    column_index as _column_index,
    compute,
    get_full_record,
    identify_invoices,
    is_summable_money_column as _is_summable_money_column,
    parse_results_table,
    search_invoices,
)
from agents.sage_prompts import PERSONA_BLOCK
from telemetry import tracked_llm_call
from utils.llm import get_llm

logger = logging.getLogger(__name__)


# How many tool calls one turn may make, in total, across every planner step.
# Four, not unbounded and not "until the model stops": the loop this replaces had
# a hard 3-attempt cap on SQL repair for the same reason, and the genuinely
# useful multi-call shapes observed in this repo's incident history are all two
# or three calls deep (a zero-result query followed by a broader one; a query
# followed by a document search; a clarification instead of either). Past that,
# a model that hasn't converged is looping, not investigating -- and every extra
# call is a real Azure round-trip a user is waiting on.
MAX_TOOL_CALLS = 4

# How many planner round-trips may happen. Distinct from MAX_TOOL_CALLS because
# a planner step can request two tools at once, so the two limits are not the
# same number of LLM calls. Both are hard stops; whichever binds first wins.
MAX_PLANNER_STEPS = 5

TOOL_IDENTIFY_INVOICES = "identify_invoices"
TOOL_GET_FULL_RECORD = "get_full_record"
TOOL_SEARCH_INVOICES = "search_invoices"
TOOL_AGGREGATE = "aggregate"
TOOL_COMPUTE = "compute"
TOOL_ASK_CLARIFYING_QUESTION = "ask_clarifying_question"

# The tools whose result carries a user-facing markdown table. `identify_invoices`
# is deliberately NOT one of them: it is an internal lookup step whose output is
# a row id and enough to disambiguate, and rendering its candidate table under
# the answer would show raw UUIDs for what the user asked as a detail question.
_TABLE_BEARING_TOOLS = (TOOL_AGGREGATE, TOOL_SEARCH_INVOICES)

# What the planner sees of a results table. It is deciding a next move ("did that
# find anything?"), not writing the answer -- the synthesis step gets the full
# table. Keeping the two views different is deliberate: handing a 200-row markdown
# table back into every planner round-trip is how a tool-calling loop quietly
# becomes the most expensive part of a request.
_PLANNER_MARKDOWN_PREVIEW_CHARS = 1200


# ---------------------------------------------------------------------------
# Tool argument schemas — the only things the model gets to choose
# ---------------------------------------------------------------------------


class IdentifyInvoicesArgs(BaseModel):
    """Find WHICH invoice(s) a question is about. Returns ids and just enough to
    tell candidates apart -- never tax detail, line items or any other figure.
    Note what is absent from this schema: tenant."""

    model_config = {"extra": "forbid"}

    question: str = Field(
        description=(
            "A self-contained question naming the invoice(s) to find -- by vendor or "
            "customer name, invoice number, and/or date. It does not have to be the "
            "user's literal words."
        )
    )


class GetFullRecordArgs(BaseModel):
    """Fetch ONE identified invoice completely: every stored field (tax breakdown,
    tax IDs, compliance identifiers, payment instructions, references, discounts,
    deductions, line items, audit alerts) plus every indexed page of its document.
    This is how any question about a specific invoice's detail gets answered."""

    model_config = {"extra": "forbid"}

    invoice_id: str = Field(
        description="The `id` of one invoice, taken from an identify_invoices result."
    )


class SearchInvoicesArgs(BaseModel):
    """Discovery: which invoices relate to a subject, when none has been identified
    yet. Searches document text and every invoice field."""

    model_config = {"extra": "forbid"}

    question: str = Field(
        description=(
            "What to look for, in the wording that would appear on an invoice or in "
            "its document text."
        )
    )


class AggregateArgs(BaseModel):
    """Cross-invoice totals, counts and breakdowns -- spend over a period, by
    vendor, by category, owed vs. owed to us. Use this instead of fetching many
    records when the answer is a figure across more than a few invoices."""

    model_config = {"extra": "forbid"}

    question: str = Field(
        description=(
            "The aggregation question, in plain English, including any period, "
            "direction or category it depends on."
        )
    )


class ComputeValue(BaseModel):
    """One value for `compute`. Which fields matter depends on the operation:
    `sum_by_currency` reads `amount`/`currency`; `reconcile_line_items` reads
    `quantity`/`unit_price`/`amount` (and optionally `description`/`currency`)."""

    model_config = {"extra": "forbid"}

    amount: Optional[float] = Field(default=None, description="The stored/printed amount.")
    currency: Optional[str] = Field(default=None, description="ISO 4217 code, e.g. 'USD'.")
    quantity: Optional[float] = Field(default=None, description="Line-item quantity.")
    unit_price: Optional[float] = Field(default=None, description="Line-item unit price.")
    description: Optional[str] = Field(default=None, description="Line-item description.")


class ComputeArgs(BaseModel):
    model_config = {"extra": "forbid"}

    operation: str = Field(
        description=f"One of: {SUM_BY_CURRENCY}, {RECONCILE_LINE_ITEMS}."
    )
    values: list[ComputeValue] = Field(
        description="The rows to operate on, taken from a tool result you already have."
    )


class AskClarifyingQuestionArgs(BaseModel):
    model_config = {"extra": "forbid"}

    question: str = Field(description="The question to put to the user. Must be answerable in one line.")
    reason: str = Field(
        description=(
            "Why the turn cannot proceed. One of: AMBIGUOUS_DIRECTION, AMBIGUOUS_ENTITY, "
            "AMBIGUOUS_TIME_RANGE, AMBIGUOUS_METRIC, MULTIPLE_CURRENCIES, UNSUPPORTED_FIELD, "
            "NO_RESULTS, OTHER."
        )
    )


_TOOL_SCHEMAS = {
    TOOL_IDENTIFY_INVOICES: IdentifyInvoicesArgs,
    TOOL_GET_FULL_RECORD: GetFullRecordArgs,
    TOOL_SEARCH_INVOICES: SearchInvoicesArgs,
    TOOL_AGGREGATE: AggregateArgs,
    TOOL_COMPUTE: ComputeArgs,
    TOOL_ASK_CLARIFYING_QUESTION: AskClarifyingQuestionArgs,
}


def bind_tool_schemas(llm):
    """Bind the six tool schemas under their real names.

    `bind_tools` names a tool after the schema class, so the names are set
    explicitly here rather than letting the model see `IdentifyInvoicesArgs`.
    """
    return llm.bind_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": (schema.__doc__ or "").strip() or name,
                    "parameters": schema.model_json_schema(),
                },
            }
            for name, schema in _TOOL_SCHEMAS.items()
        ]
    )


# ---------------------------------------------------------------------------
# The planner persona
# ---------------------------------------------------------------------------


def build_planner_prompt(tenant_stats: str = "", chat_history: str = "") -> str:
    """The one system prompt that governs tool choice — and only tool choice.

    Deliberately free of the SQL rules. The identify/aggregate rules live inside
    those tools' own prompts (`agents/sage_prompts.py`); repeating any of them
    here would recreate the exact failure this feature exists to remove -- two
    copies of a rule in two prompts, drifting apart, competing at the point of
    use. What this prompt decides is *which tool to reach for*, nothing else.

    `PERSONA_BLOCK` is prepended, and the same block is prepended to the
    synthesis prompt: the planner has to know that an IGST-only invoice is
    complete in order to not go hunting for a missing CGST row, and the answer
    step has to know it in order to not describe one as missing. A persona
    present in only one of the two is a persona that disagrees with itself
    halfway through the turn.
    """
    return f"""{PERSONA_BLOCK}

Right now you are PLANNING, not answering. Choose the tool that will get the
facts; a separate step composes the answer from exactly what the tools returned.

You do not know anything about this tenant's invoices except what a tool returns
to you. Never answer an invoice question from memory or from the conversation
history -- the history records what was said, not what is true.

YOUR TOOLS

- {TOOL_IDENTIFY_INVOICES}(question): find WHICH invoice(s) a question is about,
  by vendor/customer name, invoice number and/or date. It returns ids plus just
  enough to tell candidates apart -- never detail. Status: `ok`, `no_results`
  (the lookup ran correctly, including a name-normalized retry, and matched
  nothing -- a real answer, not a failure), `too_many` (this is really an
  aggregate question), `declined`, `error`.
- {TOOL_GET_FULL_RECORD}(invoice_id): the complete invoice -- EVERY stored field,
  including the itemized tax breakdown (`taxes`), tax registration IDs, IRN /
  e-Way Bill / Peppol identifiers, payment instructions, PO/SO references,
  discounts, deductions, line items and audit alerts -- plus every indexed page
  of the document. Any question about one invoice's detail is
  {TOOL_IDENTIFY_INVOICES} then this. Do not try to answer a detail question
  from the identify result; it does not contain the detail.
- {TOOL_SEARCH_INVOICES}(question): discovery -- which invoices relate to a
  subject, when none is identified yet. Searches document text and every invoice
  field.
- {TOOL_AGGREGATE}(question): cross-invoice totals, counts and breakdowns --
  spend over a period, per vendor, per category, owed vs. owed to us. Use this
  rather than fetching many full records. Statuses worth acting on:
  `zero_total` and `no_results` mean nothing matched (never report either as a
  total), and `multi_currency` means the figure blended currencies and must not
  be used -- re-ask grouped by currency, or ask the user which currency.
- {TOOL_COMPUTE}(operation, values): deterministic arithmetic. `sum_by_currency`
  totals amounts per currency and never across currencies. `reconcile_line_items`
  checks a stored amount against quantity x unit_price. Never do arithmetic in
  your head; that is what this tool is for.
- {TOOL_ASK_CLARIFYING_QUESTION}(question, reason): stop and ask the user. This
  ends the turn -- no answer is given. Use it when the question could reasonably
  mean two different things AND the two readings would give different answers,
  so that guessing would produce a confident wrong answer rather than an
  incomplete one.

HOW TO WORK

1. Decide whether the question is answerable as asked. If it is genuinely
   ambiguous in a way that changes the answer, call
   {TOOL_ASK_CLARIFYING_QUESTION} first, before spending a query on a guess.
2. One invoice, or a few named ones -> {TOOL_IDENTIFY_INVOICES}, then
   {TOOL_GET_FULL_RECORD} for each id you need. A figure across many invoices ->
   {TOOL_AGGREGATE}. Not sure which invoices are even involved ->
   {TOOL_SEARCH_INVOICES}.
3. Read each status. If a tool found nothing, consider one broader or
   differently-phrased attempt, or a different tool, before concluding there is
   nothing there.
4. When you have what you need, stop calling tools and reply with no tool call.
   Do not write the final answer yourself.
5. You have a hard budget of {MAX_TOOL_CALLS} tool calls for this turn. Spend
   them on getting the right data, not on re-asking the same question.

A greeting, a thank-you, or a question about this platform's own features needs
no tool at all -- reply with no tool call and let the answer step handle it. A
request to write code, do general programming or solve an unrelated problem is
out of scope for this assistant; make no tool call, and it will be declined.

{tenant_stats}

Conversation History for Context (a record of what was said, not a data source):
{chat_history}
"""


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------


class SageState(TypedDict):
    """Everything one turn carries. `db_session`/`tenant_id` are deliberately NOT
    here -- they live in the `_ToolBox` closure, out of the model's reach."""

    question: str
    messages: list
    planner_steps: int
    tool_calls_made: int
    # One entry per executed tool call: {"tool", "args", "result"} where `result`
    # is the tool's own `to_dict()`. This, not the message list, is what the
    # synthesis step reads.
    tool_results: list[dict]
    clarification: Optional[dict]
    answer: str
    generated_sql: Optional[str]
    citations: list[dict]
    result_invoice_ids: list[str]
    stop_reason: Optional[str]


# ---------------------------------------------------------------------------
# Results-table parsing and deterministic arithmetic
# ---------------------------------------------------------------------------

# `parse_results_table`, `_column_index` and `_is_summable_money_column` moved to
# `agents/query_tools.py` (imported above, re-exported here so existing callers
# and tests keep working): `aggregate()` needs the same money-column judgement to
# notice that every figure it got back is zero, and two copies of that word list
# is exactly the drift this feature exists to remove.

# What a `compute` result is called in the synthesis prompt. Never the operation
# name: `sum_by_currency` is this codebase's word, not an auditor's.
_COMPUTE_LABELS = {
    SUM_BY_CURRENCY: "total, per currency",
    RECONCILE_LINE_ITEMS: "each line, checked against quantity x unit price",
}


def _all_parse_as_numbers(values: list[str]) -> bool:
    seen_any = False
    for value in values:
        if value == "":
            continue
        try:
            Decimal(value.replace(",", ""))
        except (InvalidOperation, ValueError):
            return False
        seen_any = True
    return seen_any


def _grounded_arithmetic(columns: list[str], rows: list[list[str]]) -> list[dict]:
    """Run `compute()` over a results table, before anything writes an answer.

    This is the mechanism, not a convenience. The reverted Feature 21 failed
    because "be careful with numbers" was prose in a prompt that already had
    prose; here the numbers are already added up by the time the answer step is
    invoked, and its job is to quote `formatted` strings rather than to perform
    arithmetic it might get wrong.

    Two shapes:
      * rule 6d's line-item table (`line_qty`/`line_unit_price`/`line_amount`) ->
        `reconcile_line_items` plus a per-currency total of the line amounts. The
        reconcile call is what makes Gap 269's live false equation
        ("5000.00 units x USD 0.08 = USD 420.00") impossible to restate.
      * any other table with more than one row -> `sum_by_currency` per money
        column. Single-row tables are skipped: there is no arithmetic to do, and
        "summing" one already-aggregated row would label a figure as a total that
        the query had already totalled.
    """
    currency_index = _column_index(columns, "currency")

    def currency_of(row: list[str]) -> Optional[str]:
        return row[currency_index] if currency_index is not None else None

    grounded: list[dict] = []

    qty_i = _column_index(columns, "line_qty")
    price_i = _column_index(columns, "line_unit_price")
    amount_i = _column_index(columns, "line_amount")
    desc_i = _column_index(columns, "line_description")
    if None not in (qty_i, price_i, amount_i) and rows:
        values = [
            {
                "description": row[desc_i] if desc_i is not None else None,
                "currency": currency_of(row),
                "quantity": row[qty_i],
                "unit_price": row[price_i],
                "amount": row[amount_i],
            }
            for row in rows
        ]
        result = compute(RECONCILE_LINE_ITEMS, values)
        grounded.append({"label": "each line, checked against quantity x unit price", "result": result.to_dict()})
        if len(rows) > 1:
            total = compute(
                SUM_BY_CURRENCY,
                [{"amount": row[amount_i], "currency": currency_of(row)} for row in rows],
            )
            grounded.append({"label": "total of the line amounts, per currency", "result": total.to_dict()})
        return grounded

    if len(rows) < 2:
        return grounded

    for index, name in enumerate(columns):
        if not _is_summable_money_column(name):
            continue
        column_values = [row[index] for row in rows]
        if not _all_parse_as_numbers(column_values):
            continue
        result = compute(
            SUM_BY_CURRENCY,
            [
                {"amount": row[index], "currency": currency_of(row)}
                for row in rows
                if row[index] != ""
            ],
        )
        grounded.append({"label": f"total of `{name}` across the {len(rows)} rows above", "result": result.to_dict()})
    return grounded


def render_grounded_arithmetic(grounded: list[dict]) -> str:
    """The computed-figures block for the synthesis prompt.

    Every line in the list is a **fact** -- a figure, a label naming what it is
    the figure of. No instruction is mixed in among them, and this is not a
    stylistic preference: the first live run of this block put the mismatch
    instruction ("state both figures and the difference, never an '=' equation")
    inside the list, and gpt-5-mini reproduced the whole block, parenthetical
    instruction included, straight into the user's answer. An instruction sitting
    where data sits reads as data. All the instructing happens in the header,
    once, above the list.
    """
    if not grounded:
        return ""
    lines = []
    has_mismatch = False
    for entry in grounded:
        result = entry["result"]
        if result.get("status") != "ok":
            continue
        formatted = result.get("formatted") or []
        if not formatted:
            continue
        lines.append(f"- {entry['label']}:")
        lines.extend(f"    {line}" for line in formatted)
        if result.get("operation") == RECONCILE_LINE_ITEMS and result.get("mismatches"):
            has_mismatch = True
    if not lines:
        return ""

    header = (
        "\n\nCOMPUTED FIGURES -- working notes for you, NOT text to show the user. "
        "These numbers came from the `compute` tool rather than from a model, so "
        "they are correct: use them, and do not add, subtract, average or "
        "re-derive any figure yourself. Never combine currencies -- no exchange "
        "rate exists in this product. Write your answer as your own prose "
        "sentences; do not reproduce this block, its bullet list or its labels."
    )
    if has_mismatch:
        header += (
            " One or more lines below do not reconcile: for those, state the printed "
            "amount and the computed amount and the difference. Never write such a "
            "line as an 'x = y' equation, which would be a false statement."
        )
    return f"{header}\n" + "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Citations
# ---------------------------------------------------------------------------


def verified_citations(chunks: list[dict], tenant_id: str, db_session) -> list[dict]:
    """Chunk citations, minus any whose invoice no longer exists (Gap 239).

    Phase 1 left this out of `search_invoices` on purpose -- it needs a DB
    session the tool does not take, and it is a property of *presenting* a
    citation rather than of retrieving a chunk. This is the point where citations
    are actually rendered, so it belongs here. Existence only, deliberately not
    `invoice_not_deleted()`: a soft-deleted invoice is still a legitimate
    citation; a genuinely absent row is the bug.
    """
    citations = []
    seen = set()
    for chunk in chunks:
        key = (chunk.get("invoice_id"), chunk.get("page"))
        if key in seen:
            continue
        seen.add(key)
        citations.append(
            {
                "invoice_id": chunk.get("invoice_id"),
                "vendor_name": chunk.get("vendor_name"),
                "page": chunk.get("page"),
            }
        )
    if not citations:
        return []

    from uuid import UUID as _UUID

    from models import Invoice
    from sqlmodel import select

    cited_uuids = set()
    for citation in citations:
        try:
            cited_uuids.add(_UUID(str(citation["invoice_id"])))
        except (ValueError, AttributeError, TypeError):
            continue
    if not cited_uuids:
        return []
    try:
        rows = db_session.exec(
            select(Invoice.id).where(
                Invoice.tenant_id == _UUID(str(tenant_id)),
                Invoice.id.in_(cited_uuids),
            )
        ).all()
    except Exception as e:
        logger.warning("Citation existence check failed; dropping citations: %s", e)
        return []
    existing = {str(row) for row in rows}
    kept = [c for c in citations if str(c.get("invoice_id")) in existing]
    dropped = len(citations) - len(kept)
    if dropped:
        logger.warning("Dropped %d citation(s) with no matching Invoice row", dropped)
    return kept


def render_citation_links(citations: list[dict]) -> str:
    if not citations:
        return ""
    links = [
        f"[Source: {c['vendor_name']} (Page {c['page']})](file:///api/v1/invoices/{c['invoice_id']}/pdf)"
        for c in citations
    ]
    return "\n\n**Citations:**\n" + ", ".join(links)


# ---------------------------------------------------------------------------
# The tools, bound to one authenticated request
# ---------------------------------------------------------------------------


class _ToolBox:
    """The six tools with `tenant_id`/`db_session` closed over.

    The model never sees these two values and cannot pass them: `dispatch()`
    takes only the arguments named in the schemas above and supplies the rest
    itself. That is the whole reason this is a class holding request state rather
    than six free functions the graph calls directly.
    """

    def __init__(self, tenant_id: str, db_session, llm, *, chat_history: str = "", prior_turn_sql=None):
        self.tenant_id = str(tenant_id)
        self.db_session = db_session
        self.llm = llm
        self.chat_history = chat_history
        self.prior_turn_sql = prior_turn_sql

    def dispatch(self, name: str, args: dict):
        if name == TOOL_IDENTIFY_INVOICES:
            return identify_invoices(
                args.get("question") or "",
                self.tenant_id,
                self.db_session,
                llm=self.llm,
                chat_history=self.chat_history,
                prior_turn_sql=self.prior_turn_sql,
            )
        if name == TOOL_GET_FULL_RECORD:
            return get_full_record(
                args.get("invoice_id") or "", self.tenant_id, self.db_session
            )
        if name == TOOL_SEARCH_INVOICES:
            return search_invoices(
                args.get("question") or "",
                self.tenant_id,
                self.db_session,
                llm=self.llm,
            )
        if name == TOOL_AGGREGATE:
            return aggregate(
                args.get("question") or "",
                self.tenant_id,
                self.db_session,
                llm=self.llm,
                chat_history=self.chat_history,
                prior_turn_sql=self.prior_turn_sql,
            )
        if name == TOOL_COMPUTE:
            return compute(args.get("operation") or "", args.get("values") or [])
        if name == TOOL_ASK_CLARIFYING_QUESTION:
            return ask_clarifying_question(args.get("question") or "", args.get("reason") or "")
        raise KeyError(f"unknown tool: {name}")


def planner_view(name: str, result: dict) -> dict:
    """What the planner is shown of a tool result.

    Status first and always, in full: the whole point of the tools returning a
    closed `status` vocabulary is that the next move is a branch on a fact, not
    an inference from prose. The bulky part (a results table) is previewed, since
    the planner is deciding whether to call again, not writing the answer -- the
    synthesis step reads the untruncated result.
    """
    view = {"status": result.get("status")}
    if result.get("ends_turn"):
        # A clarification, whichever tool produced it (`identify_invoices` can
        # raise one itself). Passed through whole: the loop is about to end the
        # turn on it, and a summarised view of it would be the one place a
        # clarification could quietly lose its question.
        return dict(result)
    if name == TOOL_IDENTIFY_INVOICES:
        # Candidates in full, deliberately: they are small, and the next move
        # (which id to fetch, or whether these are really two different vendors)
        # is decided from exactly these fields.
        view["candidates"] = result.get("candidates") or []
        view["invoice_ids"] = result.get("invoice_ids") or []
        view["name_normalized_retry"] = result.get("name_normalized_retry")
        if result.get("message"):
            view["message"] = result["message"]
    elif name == TOOL_GET_FULL_RECORD:
        # The record itself is NOT previewed back to the planner. It is large,
        # the planner's job is to decide whether anything else is needed, and the
        # synthesis step reads the untruncated record. What the planner needs is
        # which fields actually carried a value.
        record = result.get("record") or {}
        view["invoice_id"] = result.get("invoice_id")
        view["fields_present"] = sorted(k for k, v in record.items() if v not in (None, [], {}, ""))
        view["document_pages"] = len(result.get("chunks") or [])
        if result.get("pages_omitted"):
            # The planner decides whether anything else is needed, so it has to
            # know the document was longer than what the answer step will see --
            # otherwise "document_pages: 6" reads as a complete 6-page document.
            view["document_pages_total"] = result.get("total_document_pages")
            view["document_pages_omitted"] = result.get("pages_omitted")
        view["has_alerts"] = result.get("has_alerts")
        if result.get("message"):
            view["message"] = result["message"]
    elif name in (TOOL_AGGREGATE, TOOL_SEARCH_INVOICES):
        markdown = result.get("results_markdown") or ""
        view["generated_sql"] = result.get("generated_sql")
        view["row_count"] = _row_count(markdown)
        view["results_preview"] = markdown[:_PLANNER_MARKDOWN_PREVIEW_CHARS]
        if len(markdown) > _PLANNER_MARKDOWN_PREVIEW_CHARS:
            view["results_preview"] += "\n... (truncated; the answer step sees every row)"
        for key in ("currencies", "phrases", "fiscal_year_note"):
            if result.get(key):
                view[key] = result[key]
        if name == TOOL_SEARCH_INVOICES:
            view["chunk_count"] = len(result.get("chunks") or [])
            view["chunks"] = [
                {
                    "document": (chunk.get("document") or "")[:400],
                    "vendor_name": chunk.get("vendor_name"),
                    "page": chunk.get("page"),
                    "matched_by": chunk.get("matched_by"),
                }
                for chunk in (result.get("chunks") or [])
            ]
        if result.get("message"):
            view["message"] = result["message"]
    else:
        view = dict(result)
    return view


def _row_count(markdown: str) -> int:
    parsed = parse_results_table(markdown)
    return len(parsed[1]) if parsed else 0


def call_signature(name: str, args: dict) -> tuple:
    """Identity of one tool call, for "have I already run exactly this?".

    Any argument that parses as a UUID is canonicalised first. That is not
    tidiness: measured live 2026-08-21, gpt-5-mini asked for `get_full_record` on
    `'9bfa2804-35c8-44ef-a1be-1ad6566b874e'` and then on
    `'9bfa280435c844efa1be1ad6566b874e'` in the same turn -- the same invoice,
    written two ways, which a plain string comparison reads as two different
    calls. Everything else compares verbatim, so `aggregate` asked a genuinely
    different question is still a different call.
    """
    from uuid import UUID as _UUID

    normalized: dict = {}
    for key, value in (args or {}).items():
        if isinstance(value, str):
            try:
                normalized[key] = str(_UUID(value))
                continue
            except (ValueError, AttributeError, TypeError):
                pass
        normalized[key] = value
    return name, json.dumps(normalized, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def _plan_node(state: SageState, *, planner_llm, tenant_id: str = "") -> dict:
    """Ask the model which tool to reach for next (or for none, meaning 'answer').

    `tenant_id` is Feature 23 Phase 1 telemetry attribution only; it is not put
    into the state and the planner never sees it.
    """
    steps = state["planner_steps"] + 1
    budget_left = MAX_TOOL_CALLS - state["tool_calls_made"]

    messages = list(state["messages"])
    if budget_left <= 0:
        # Hard stop, enforced here rather than trusted to the prompt's stated
        # budget: an unbounded tool loop is a cost and latency incident, and this
        # is the one place that can guarantee it cannot happen.
        return {"planner_steps": steps, "stop_reason": "tool_call_budget_exhausted"}
    if steps > MAX_PLANNER_STEPS:
        return {"planner_steps": steps, "stop_reason": "planner_step_budget_exhausted"}

    try:
        # Feature 23 Phase 1: one event per planner step. `planner_step` is on the
        # event because a multi-step loop is the cost risk this agent carries --
        # the step count is what the budget guards above exist to bound.
        with tracked_llm_call(
            "sage.planner",
            llm=planner_llm,
            tenant_id=tenant_id,
            planner_step=steps,
            tool_calls_made=state["tool_calls_made"],
        ):
            reply = planner_llm.invoke(messages)
    except Exception as e:
        logger.error("SAGE planner step failed: %s", e)
        return {"planner_steps": steps, "stop_reason": f"planner_error: {e}"}

    return {"planner_steps": steps, "messages": messages + [reply]}


def _route_after_plan(state: SageState) -> str:
    if state.get("stop_reason"):
        return "synthesize"
    messages = state["messages"]
    last = messages[-1] if messages else None
    if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
        return "act"
    return "synthesize"


def _act_node(state: SageState, *, toolbox: _ToolBox) -> dict:
    """Run every tool the planner asked for, in order, inside the turn's budget."""
    last = state["messages"][-1]
    calls = list(getattr(last, "tool_calls", []) or [])

    messages = list(state["messages"])
    tool_results = list(state["tool_results"])
    calls_made = state["tool_calls_made"]
    clarification = None
    stop_reason = None

    # What has already been run this turn, keyed on tool + exact arguments.
    # Found live 2026-08-21, on the first real-model run of this tool set: in all
    # three identify->fetch turns of the golden sample, the planner asked for
    # `get_full_record` on the SAME invoice id three times in a row and spent the
    # entire tool-call budget doing it. Each repeat re-rendered the whole record
    # and every document page into the synthesis prompt, so one 11-page invoice
    # produced a 129,703-token synthesis call where a single fetch would have
    # been ~43,000. Re-running an identical call cannot produce new information
    # (the tools are reads), so it is answered from what the turn already has.
    # Keyed on exact arguments on purpose: `aggregate` legitimately gets called
    # more than once with *different* questions (the broaden-after-nothing move),
    # and that must keep working.
    already_run = {
        call_signature(entry["tool"], entry.get("args") or {}): entry["result"]
        for entry in tool_results
    }

    for call in calls:
        name = call.get("name")
        args = call.get("args") or {}
        call_id = call.get("id") or name
        signature = call_signature(name, args)

        if calls_made >= MAX_TOOL_CALLS:
            messages.append(
                ToolMessage(
                    content=json.dumps(
                        {
                            "status": "skipped",
                            "message": (
                                f"Tool-call budget of {MAX_TOOL_CALLS} for this turn is spent. "
                                "Answer from what you already have."
                            ),
                        }
                    ),
                    tool_call_id=call_id,
                )
            )
            stop_reason = "tool_call_budget_exhausted"
            continue

        calls_made += 1

        if signature in already_run:
            # Answered from the turn's own results, and NOT appended to
            # `tool_results` a second time -- synthesis renders one section per
            # entry, so a duplicate entry is a duplicate copy of the whole record
            # and every page of its document in the prompt. The call still counts
            # against the budget: the budget is a hard bound on how long a turn
            # can go on, and a planner that keeps re-asking the same question is
            # exactly the case it exists to stop.
            logger.info("SAGE tool %s called again with identical arguments; reusing result", name)
            view = planner_view(name, already_run[signature])
            view["duplicate_of_earlier_call"] = True
            view["message"] = (
                "You already called this tool with these exact arguments in this turn. "
                "This is the same result, not a new one. Use it, or call a different tool."
            )
            messages.append(ToolMessage(content=json.dumps(view, default=str), tool_call_id=call_id))
            continue

        try:
            result = toolbox.dispatch(name, args)
            result_dict = result.to_dict()
        except Exception as e:
            # A tool raising is a fact about this turn, not a reason to lose it:
            # the planner is told, and can still answer from whatever else it
            # has. `ask_clarifying_question` raising on an empty question (a
            # caller bug by Phase 1's contract) lands here too.
            logger.warning("SAGE tool %s raised: %s", name, e)
            result_dict = {"status": "error", "message": str(e)}
            messages.append(ToolMessage(content=json.dumps(result_dict), tool_call_id=call_id))
            tool_results.append({"tool": name, "args": args, "result": result_dict})
            continue

        tool_results.append({"tool": name, "args": args, "result": result_dict})
        already_run[signature] = result_dict
        messages.append(
            ToolMessage(
                content=json.dumps(planner_view(name, result_dict), default=str),
                tool_call_id=call_id,
            )
        )

        # `ends_turn` short-circuit. Phase 1 made this a constant True field on
        # ClarificationRequest precisely so it would be a fact to branch on here
        # rather than advice the loop could weigh: a turn that decided to ask a
        # question does not then go on to answer it.
        if result_dict.get("ends_turn"):
            clarification = result_dict
            stop_reason = "clarification_requested"
            break

    update: dict = {
        "messages": messages,
        "tool_results": tool_results,
        "tool_calls_made": calls_made,
    }
    if clarification:
        update["clarification"] = clarification
    if stop_reason:
        update["stop_reason"] = stop_reason
    return update


def _route_after_act(state: SageState) -> str:
    if state.get("clarification"):
        return "clarify"
    if state.get("stop_reason") == "tool_call_budget_exhausted":
        return "synthesize"
    return "plan"


def _clarify_node(state: SageState) -> dict:
    """The turn's answer is the question. No synthesis runs at all."""
    clarification = state["clarification"] or {}
    logger.info(
        "SAGE turn ended in a clarifying question (reason=%s)", clarification.get("reason")
    )
    return {"answer": clarification.get("question") or ""}


def _synthesize_node(state: SageState, *, llm, deps: dict) -> dict:
    """Compose the answer from tool output and nothing else.

    The prompt below is built from `state["tool_results"]`, never from the
    planner's own messages. There is no "answer only from the context" mandate in
    it, because there is no other context in it to answer from -- which is the
    difference between this design and the one that was reverted.
    """
    question = state["question"]
    tool_results = state["tool_results"]

    generated_sql = None
    result_invoice_ids: list[str] = []
    chunks: list[dict] = []
    sections: list[str] = []
    grounded_all: list[dict] = []

    for entry in tool_results:
        name = entry["tool"]
        result = entry["result"]
        status = result.get("status")

        asked = (entry.get("args") or {}).get("question") or question

        if name == TOOL_IDENTIFY_INVOICES:
            for invoice_id in result.get("invoice_ids") or []:
                if invoice_id not in result_invoice_ids:
                    result_invoice_ids.append(invoice_id)
            if status == "ok":
                rendered = json.dumps(result.get("candidates") or [], indent=2, default=str)
                note = (
                    "\n(These rows came from a name-normalized retry after the original "
                    "filter matched nothing, so any date/amount restriction in the question "
                    "was NOT applied to them.)"
                    if result.get("name_normalized_retry")
                    else ""
                )
                sections.append(
                    f"INVOICES IDENTIFIED for \"{asked}\" (identity only -- no detail):"
                    f"\n{rendered}{note}"
                )
            elif status == "no_results":
                sections.append(
                    f"INVOICE LOOKUP for \"{asked}\": matched no rows, including after "
                    "normalizing the name (case, whitespace, legal suffixes). This means "
                    "nothing matches, not that the lookup failed."
                )
            else:
                sections.append(
                    f"INVOICE LOOKUP for \"{asked}\" returned {status}: {result.get('message')}"
                )

        elif name == TOOL_GET_FULL_RECORD:
            invoice_id = result.get("invoice_id")
            if invoice_id and invoice_id not in result_invoice_ids:
                result_invoice_ids.append(invoice_id)
            if status == "ok":
                chunks.extend(result.get("chunks") or [])
                # The whole record, verbatim. This block is the fix: there is no
                # curated field list between the stored row and the answer, so a
                # tax-breakdown or compliance-identifier question is answered from
                # the data rather than from whatever a prompt happened to mention.
                record = json.dumps(result.get("record") or {}, indent=2, default=str)
                document_text = "\n".join(
                    f"--- PAGE {chunk.get('page')} ---\n{chunk.get('document')}"
                    for chunk in result.get("chunks") or []
                )
                section = f"COMPLETE RECORD for invoice {invoice_id} (every stored field):\n{record}"
                pages_omitted = result.get("pages_omitted") or []
                if document_text:
                    total_pages = result.get("total_document_pages") or len(
                        result.get("chunks") or []
                    )
                    heading = (
                        "EVERY INDEXED PAGE OF THIS INVOICE'S DOCUMENT"
                        if not pages_omitted
                        else (
                            f"{len(result.get('chunks') or [])} OF THIS INVOICE'S "
                            f"{total_pages} INDEXED PAGES (the document is long; the first and "
                            "last page are always included)"
                        )
                    )
                    section += f"\n\n{heading}:\n{document_text}"
                if pages_omitted:
                    # Disclosed, not hidden -- same rule as `columns_omitted`
                    # below. An answer written off a truncated document must be
                    # able to say the document was truncated.
                    section += (
                        "\n\n(Page(s) "
                        + ", ".join(str(page) for page in pages_omitted)
                        + " of this document are NOT shown above -- the document exceeded the "
                        "size a single answer can carry. Every stored field of the invoice "
                        "itself, including its line items, IS above. If the question turns on "
                        "text that would only appear on an omitted page, say which pages were "
                        "not read rather than answering as if the whole document were here.)"
                    )
                omitted = result.get("columns_omitted") or []
                if omitted:
                    section += (
                        "\n\n(Storage-plumbing columns not included and not needed for any "
                        f"answer: {', '.join(omitted)}.)"
                    )
                sections.append(section)
            else:
                sections.append(
                    f"FULL RECORD fetch returned {status}: {result.get('message')}"
                )

        elif name == TOOL_AGGREGATE:
            if result.get("generated_sql"):
                generated_sql = result["generated_sql"]
            for invoice_id in result.get("invoice_ids") or []:
                if invoice_id not in result_invoice_ids:
                    result_invoice_ids.append(invoice_id)
            if status == "ok":
                markdown = result.get("results_markdown") or ""
                sections.append(f"AGGREGATE RESULTS for \"{asked}\":\n{markdown}")
                parsed = parse_results_table(markdown)
                if parsed:
                    grounded_all.extend(_grounded_arithmetic(*parsed))
            elif status in ("no_results", "zero_total", "multi_currency"):
                # Every one of these is a fact the answer must state plainly, not
                # a number to report. The tool's own message says which.
                sections.append(f"AGGREGATE for \"{asked}\" ({status}): {result.get('message')}")
            elif status == "declined":
                sections.append(
                    f"AGGREGATION for \"{asked}\" was not possible: {result.get('message')}"
                )
            else:
                sections.append(
                    f"AGGREGATION for \"{asked}\" failed with an error: {result.get('message')}"
                )
            for key in ("fiscal_year_note", "status_inclusion_note"):
                if result.get(key):
                    sections.append(result[key])

        elif name == TOOL_SEARCH_INVOICES:
            if result.get("generated_sql"):
                generated_sql = generated_sql or result["generated_sql"]
            for invoice_id in result.get("invoice_ids") or []:
                if invoice_id not in result_invoice_ids:
                    result_invoice_ids.append(invoice_id)
            if status == "ok":
                chunks.extend(result.get("chunks") or [])
                rendered = "\n".join(
                    f"--- CHUNK (matched_by={chunk.get('matched_by')}) ---\n{chunk.get('document')}"
                    for chunk in result.get("chunks") or []
                )
                if rendered:
                    sections.append(f"DOCUMENT EXCERPTS:\n{rendered}")
                if result.get("results_markdown"):
                    sections.append(
                        f"INVOICES MATCHING \"{asked}\" on their own fields:\n"
                        f"{result['results_markdown']}"
                    )
            else:
                sections.append(
                    f"SEARCH for \"{asked}\" returned nothing usable: {result.get('message')}"
                )

        elif name == TOOL_COMPUTE:
            # Labelled in the user's terms, not ours: the first live run showed
            # gpt-5-mini echoing a label reading "`compute` (sum_by_currency)
            # requested by the planner" into the answer. Internal vocabulary in a
            # data block is internal vocabulary in the reply.
            grounded_all.append({"label": _COMPUTE_LABELS.get(result.get("operation"), "computed figures"), "result": result})

    computed_block = render_grounded_arithmetic(grounded_all)
    data_block = "\n\n".join(sections) if sections else (
        "NO TOOL WAS CALLED FOR THIS TURN. You therefore have no invoice data at all. "
        "Answer conversationally about this assistant or the platform if that is what was "
        "asked, decline politely if the request is outside invoices/this platform (writing "
        "code, general programming or maths), and state no fact about any invoice."
    )

    prompt = f"""{PERSONA_BLOCK}

Compose the answer to the user's question using ONLY what the tools returned below.
{deps.get('style_block', '')}
Answer in your own complete sentences. Be direct. Do not describe how you looked
it up, which tool you used, or how a query was built. Do not restate every row --
the results table is shown to the user immediately after your answer. The blocks
below are working material handed to you; never copy their headings, labels or
bracketed notes into your reply.

CRITICAL CURRENCY RULE: use the currency of the row you are talking about (INR/₹,
EUR/€, USD/$ ...) -- never default to '$', and never add amounts across different
currencies.
{deps.get('payment_status_block', '')}
{data_block}
{computed_block}
{deps.get('rules_block', '')}{deps.get('chat_rules_block', '')}
User Question: {deps.get('wrapped_user_message', question)}
"""

    try:
        # Feature 23 Phase 1
        with tracked_llm_call(
            "sage.synthesis",
            llm=llm,
            tenant_id=str(deps.get("tenant_id") or ""),
            tool_calls_made=state.get("tool_calls_made", 0),
        ):
            reply = llm.invoke(prompt)
        answer = reply.content
    except Exception as e:
        logger.error("SAGE synthesis failed: %s", e)
        return {
            "answer": f"Failed to compose an answer: {e}",
            "generated_sql": generated_sql,
            "citations": [],
            "result_invoice_ids": result_invoice_ids,
            "stop_reason": state.get("stop_reason") or "synthesis_error",
        }

    citations = verified_citations(chunks, deps["tenant_id"], deps["db_session"])
    if citations:
        answer += render_citation_links(citations)
        for citation in citations:
            invoice_id = citation.get("invoice_id")
            if invoice_id and str(invoice_id) not in result_invoice_ids:
                result_invoice_ids.append(str(invoice_id))

    # One results table, appended once, the same way the SQL route does it -- one
    # blank line before the heading and one after, because the table itself
    # starts directly with its header row.
    last_ok_table = next(
        (
            entry["result"].get("results_markdown")
            for entry in reversed(tool_results)
            if entry["tool"] in _TABLE_BEARING_TOOLS
            and entry["result"].get("status") == "ok"
            and entry["result"].get("results_markdown")
        ),
        None,
    )
    if last_ok_table:
        answer += f"\n\n### Query Results\n\n{last_ok_table}"

    return {
        "answer": answer,
        "generated_sql": generated_sql,
        "citations": citations,
        "result_invoice_ids": result_invoice_ids,
    }


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------


def build_sage_graph(*, planner_llm, llm, toolbox: _ToolBox, deps: dict):
    """Compile the loop for one request.

    Compiled per request rather than once at import (which is what
    `extraction_agent.py` does) because the nodes close over this request's
    tenant and DB session -- a module-level graph would have to take them through
    the state, where the model could see them.
    """
    builder = StateGraph(SageState)
    builder.add_node(
        "plan",
        lambda state: _plan_node(
            state, planner_llm=planner_llm, tenant_id=str(deps.get("tenant_id") or "")
        ),
    )
    builder.add_node("act", lambda state: _act_node(state, toolbox=toolbox))
    builder.add_node("clarify", _clarify_node)
    builder.add_node("synthesize", lambda state: _synthesize_node(state, llm=llm, deps=deps))
    builder.set_entry_point("plan")
    builder.add_conditional_edges(
        "plan", _route_after_plan, {"act": "act", "synthesize": "synthesize"}
    )
    builder.add_conditional_edges(
        "act", _route_after_act, {"plan": "plan", "clarify": "clarify", "synthesize": "synthesize"}
    )
    builder.add_edge("clarify", END)
    builder.add_edge("synthesize", END)
    return builder.compile()


def run_agentic_sage(session_id: str, user_message: str, tenant_id: str, db_session) -> dict:
    """The `ENABLE_AGENTIC_SAGE` entry point. Same signature and same return shape
    as `run_query_agent()`, so `routers/chat.py` and the trainer's QA-test mode
    need no change when the flag moves.

    Returns `{"content", "generated_sql", "citations", "result_invoice_ids"}`,
    plus `"agentic"` metadata (tool calls made, why the loop stopped, the
    clarification reason if any) that the existing callers ignore and Phase 3's
    regression suite reads.
    """
    logger.info("Executing agentic SAGE for session %s, tenant %s", session_id, tenant_id)

    chat_history = get_chat_history(session_id, db_session)
    prior_turn_sql = get_prior_turn_sql(session_id, db_session)

    business_rules = list(_get_global_business_rules(tenant_id, db_session))
    for rule in _get_vendor_business_rules(tenant_id, user_message, db_session):
        if rule not in business_rules:
            business_rules.append(rule)

    deps = {
        "tenant_id": str(tenant_id),
        "db_session": db_session,
        "rules_block": _business_rules_block(business_rules),
        "chat_rules_block": _chat_rules_block(tenant_id, db_session),
        "style_block": _get_chat_style_block(tenant_id, db_session),
        # Gap 267: the payment-status guardrail has to reach the prompt that
        # writes the answer, not only the one that writes SQL -- injecting it into
        # generation alone is exactly what made its first fix fail live.
        "payment_status_block": _payment_status_block_for(user_message),
        "wrapped_user_message": _wrap_user_input(user_message, tenant_id),
    }
    tenant_stats = _get_tenant_stats_summary(tenant_id, db_session)

    llm = get_llm()
    toolbox = _ToolBox(
        tenant_id, db_session, llm, chat_history=chat_history, prior_turn_sql=prior_turn_sql
    )
    graph = build_sage_graph(
        planner_llm=bind_tool_schemas(llm), llm=llm, toolbox=toolbox, deps=deps
    )

    initial_state: SageState = {
        "question": user_message,
        "messages": [
            SystemMessage(content=build_planner_prompt(tenant_stats, chat_history)),
            HumanMessage(content=deps["wrapped_user_message"]),
        ],
        "planner_steps": 0,
        "tool_calls_made": 0,
        "tool_results": [],
        "clarification": None,
        "answer": "",
        "generated_sql": None,
        "citations": [],
        "result_invoice_ids": [],
        "stop_reason": None,
    }

    final_state = graph.invoke(initial_state)

    clarification = final_state.get("clarification") or {}
    return {
        "content": final_state.get("answer") or "",
        "generated_sql": final_state.get("generated_sql"),
        "citations": final_state.get("citations") or [],
        "result_invoice_ids": (final_state.get("result_invoice_ids") or [])[
            :MAX_SNAPSHOT_INVOICE_IDS
        ],
        "agentic": {
            "tool_calls_made": final_state.get("tool_calls_made", 0),
            "tools_called": [entry["tool"] for entry in final_state.get("tool_results") or []],
            "stop_reason": final_state.get("stop_reason"),
            "clarification_reason": clarification.get("reason"),
        },
    }
