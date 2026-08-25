"""Shared, LLM-free helpers for Feature 6's chat route.

This module was written as Feature 21's SAGE tool set (six tools behind
`ENABLE_AGENTIC_SAGE`, driven by `agents/sage_orchestrator.py`). Gap 316 deleted
the orchestrator, the flag and the four tools that only it ever called
(`identify_invoices`, `search_invoices`, `aggregate`, `ask_clarifying_question`)
on 2026-08-25, after the live head-to-head measured the loop slower and dearer
than the default path with no correctness benefit. Full record of that decision:
`docs/be_features_tracker.md`, the Feature 21 section and Gap 316; the code
itself is in git history (`git log -- .../agents/sage_orchestrator.py`).

What is left is what Feature 6's default chat route genuinely uses, and it is
deliberately kept here rather than inlined into `agents/query_agent.py` -- two
copies of one tenant check, or of one summation, is how a bypass path or a
drifting arithmetic rule gets built by accident:

  * `get_full_record` (Gap 310) -- `Invoice.model_dump()` for one id, tenant
    checked, storage-plumbing columns excluded and *reported*. No LLM, no SQL
    generation, no hand-maintained column list: chat kept getting tax and detail
    questions wrong not because the data was missing but because a narrow,
    hand-typed ~19-column schema description was the only thing the SQL-writing
    model ever saw, and extraction grew far past it (`taxes`, `tax_ids`,
    `compliance_metadata`, `payment_instructions`, `references`, `discounts`,
    `deductions` were all real, populated and invisible). Reflecting the live ORM
    row means a column added tomorrow is answerable tomorrow with no prompt edit.
  * `compute` (Gap 315) -- "add these numbers" as a function call rather than an
    instruction in a prompt, per CONVENTIONS.md hard rule 3. Gap 269's live false
    equation ("5000.00 units x USD 0.08 = USD 420.00") is what model-performed
    arithmetic produces.
  * `parse_results_table` / `column_index` / `is_summable_money_column` -- the
    support helpers both of the above lean on.

Both entry points return a small frozen dataclass with an explicit `status`, plus
`to_dict()`. `tenant_id` and `db_session` are ordinary positional parameters and
are never model-controlled.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Optional
from uuid import UUID

from chroma_client import get_all_invoice_chunks

logger = logging.getLogger(__name__)

# Two decimal places is already this codebase's currency precision everywhere
# else it renders money (execute_generated_sql()'s Decimal and float branches
# both quantize to it), so `compute` uses the same and doesn't invent a second
# convention.
_MONEY = Decimal("0.01")

# A currency we could not read off the row. Deliberately its own bucket rather
# than defaulting to USD: the read-time COALESCE(currency,'USD') the dashboard
# and tenant-stats queries use is a display convenience over historical NULLs,
# and doing the same inside an arithmetic tool would silently assert that an
# unlabelled amount is dollars.
UNKNOWN_CURRENCY = "UNKNOWN"

# ---------------------------------------------------------------------------
# Shared helpers — results tables, money columns, tenant ids
# ---------------------------------------------------------------------------

# A column worth totalling. Matched on the header name, because the header is the
# only thing that says what a number *means* -- summing a column of quantities or
# unit prices produces a figure with no referent, which is worse than no figure.
# Lives here rather than beside its caller because it started with two of them
# (the orchestrator's `_grounded_arithmetic()` and `aggregate()`, both deleted by
# Gap 316); today `query_agent._computed_figures_block_for()` is the only one.
_MONEY_COLUMN_WORDS = (
    "total", "amount", "subtotal", "tax", "spend", "balance", "due_amount", "cost",
)
# Checked first and wins. `line_unit_price` contains no money word above, but
# `avg_grand_total` does -- and adding up averages is not a total of anything.
_NEVER_SUM_WORDS = (
    "avg", "average", "mean", "count", "rate", "percent", "unit_price", "qty",
    "quantity", "number", "date", "id",
)


def parse_results_table(markdown: str) -> Optional[tuple[list[str], list[list[str]]]]:
    """Read back the markdown table `execute_generated_sql()` produced.

    Returns `(columns, rows)`, or None when the text is not a table this can
    read with certainty -- a header/row width mismatch returns None for the whole
    table rather than dropping the offending row. Same principle as `compute()`'s
    refusal to silently skip a malformed value: a total computed from most of the
    rows is a wrong number that looks like a right one.
    """
    if not markdown:
        return None
    lines = [line for line in markdown.strip().splitlines() if line.strip()]
    if len(lines) < 3:
        return None
    columns = [c.strip() for c in lines[0].split(" | ")]
    separator = [c.strip() for c in lines[1].split(" | ")]
    if not columns or any(set(cell) - {"-"} for cell in separator) or not separator:
        return None
    if len(separator) != len(columns):
        return None
    rows: list[list[str]] = []
    for line in lines[2:]:
        cells = [c.strip() for c in line.split(" | ")]
        if len(cells) != len(columns):
            return None
        rows.append(cells)
    return columns, rows


def column_index(columns: list[str], name: str) -> Optional[int]:
    lowered = [c.lower() for c in columns]
    return lowered.index(name) if name in lowered else None


def is_summable_money_column(name: str) -> bool:
    lowered = name.lower()
    if any(word in lowered for word in _NEVER_SUM_WORDS):
        return False
    return any(word in lowered for word in _MONEY_COLUMN_WORDS)

def _tenant_uuid(tenant_id) -> Optional[UUID]:
    try:
        return UUID(str(tenant_id))
    except (ValueError, AttributeError, TypeError):
        return None


def _json_safe(value: Any) -> Any:
    """Whatever a row actually carried, in a shape `json.dumps` accepts."""
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Tool 2 — get_full_record
# ---------------------------------------------------------------------------

# The only columns held back from a "full" record, named here so the omission is
# reviewable instead of invisible -- and reported on every result in
# `columns_omitted`. The design this was built to said "every column, no
# curation"; this is a five-column deviation from that and each one is
# non-business content:
#   * file_path / batch_id / file_hash -- storage plumbing. `file_path` is a blob
#     URI that already leaked into a chat answer once, which is why
#     `execute_generated_sql` denies it at render time.
#   * coordinates -- OCR bounding-box geometry.
#   * source_document_json -- the raw Document Intelligence payload, i.e. a second
#     copy of every field below plus page geometry, routinely hundreds of KB. Its
#     structured distillation IS the rest of this record.
# Every business field the feature exists to expose -- taxes, tax_ids,
# compliance_metadata, payment_instructions, references, discounts, deductions,
# addresses, sa_alerts, field_confidence -- is included.
FULL_RECORD_EXCLUDED_COLUMNS = (
    "file_path",
    "batch_id",
    "file_hash",
    "coordinates",
    "source_document_json",
)

# How much document text one full-record fetch may put in front of the model.
#
# NOTE (Gap 316): no live caller passes `include_document_pages=True` today --
# Feature 6's route sets it False, and the orchestrator that used the default was
# deleted. This cap and `bound_document_pages()` are kept as part of the
# function's contract rather than stripped out; the measurements below are why
# the number is what it is, and are what a future caller would need.
#
# Set from measurement, not from intuition (live run 2026-08-21, real gpt-5-mini,
# `scripts/run_agent_eval.py`; full numbers in the tracker's Feature 21 section):
# `chroma_client.get_all_invoice_chunks()` bounds nothing -- one chunk per page,
# whole page text, every page -- and the cost is linear in page count. Measured on
# a real rendered invoice: 1 page = 242 tokens, 5 pages = 5,963, 11 pages =
# 16,010, 22 pages = 30,940. A single `sage.synthesis` prompt carrying an
# 11-page invoice's pages measured 129,818 input tokens against 1,906 for the
# one-page control, and gpt-5-mini list input pricing makes the page dump alone
# ~$0.0040 on that turn -- about 80% of a whole measured baseline turn ($0.0051).
# Unbounded, a 50-page consolidated invoice is ~72k tokens in one prompt.
#
# 20,000 characters is ~6 pages of this shape and ~9,000 tokens: enough that no
# ordinary invoice is touched at all, small enough that a pathological document
# cannot dominate a turn. It is a policy choice recorded in code, not a natural
# constant -- change it here, in one place, and every caller changes with it.
MAX_FULL_RECORD_CHUNK_CHARS = 20_000

# Pages that survive the cap no matter how long they are. On a multi-page invoice
# the totals, payment terms and signature block are on the LAST page and the
# header/invoice number on the first, so a naive "first N pages" cap would
# systematically drop the exact page most detail questions need. Two pages is the
# floor: if the first and last alone exceed the budget they are still both kept,
# because an empty document block is worse than a long one.
FULL_RECORD_ANCHOR_PAGES = 2


def _page_number(chunk: dict) -> float:
    """A sortable page number; unlabelled pages sort last, in arrival order."""
    page = chunk.get("page")
    try:
        return float(page)
    except (TypeError, ValueError):
        return float("inf")


def bound_document_pages(chunks: list[dict]) -> tuple[list[dict], list]:
    """Cap a full record's document text, keeping first and last page.

    Returns `(kept, omitted_pages)`. `omitted_pages` is non-empty **only** when
    something was actually dropped, and the caller reports it on the result the
    same way `columns_omitted` reports the five skipped columns -- a truncation
    the model is not told about is a truncation that gets presented as a complete
    document, which is precisely the silent-data-loss failure this feature exists
    to remove. This is a bound on *how much is shown*, not on what is retrieved:
    `get_all_invoice_chunks()` still returns every page, deliberately, because
    that function's job is complete retrieval.
    """
    ordered = sorted(chunks, key=_page_number)
    total = sum(len(chunk.get("document") or "") for chunk in ordered)
    if total <= MAX_FULL_RECORD_CHUNK_CHARS or len(ordered) <= FULL_RECORD_ANCHOR_PAGES:
        return ordered, []

    kept = [ordered[0], ordered[-1]]
    used = sum(len(chunk.get("document") or "") for chunk in kept)
    for chunk in ordered[1:-1]:
        length = len(chunk.get("document") or "")
        if used + length > MAX_FULL_RECORD_CHUNK_CHARS:
            continue
        kept.append(chunk)
        used += length

    kept_ids = {id(chunk) for chunk in kept}
    omitted = [
        chunk.get("page") for chunk in ordered if id(chunk) not in kept_ids
    ]
    return sorted(kept, key=_page_number), omitted


@dataclass(frozen=True)
class FullRecordResult:
    """One invoice, completely.

    `status` is `"ok"` / `"not_found"` / `"error"`. `record` is the live ORM row
    reflected at call time, so a column added to `models.py` appears here with no
    change to this file and no change to any prompt -- that reflection is the
    actual fix this feature was opened for, not an implementation detail.

    `pages_omitted` names the document pages held back by
    `MAX_FULL_RECORD_CHUNK_CHARS`, and is empty for every invoice short enough
    not to hit it. Same honesty rule as `columns_omitted`: the omission travels
    with the result, so the answer step can say the document was long rather than
    describe a partial document as the whole thing.
    """

    status: str
    invoice_id: Optional[str] = None
    record: dict = field(default_factory=dict)
    chunks: list[dict] = field(default_factory=list)
    columns_omitted: list[str] = field(default_factory=list)
    pages_omitted: list = field(default_factory=list)
    total_document_pages: int = 0
    has_alerts: bool = False
    message: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def get_full_record(
    invoice_id: str,
    tenant_id: str,
    db_session,
    *,
    include_document_pages: bool = True,
) -> FullRecordResult:
    """The complete invoice row plus every indexed page of its document.

    No LLM, no SQL generation, no column list: `Invoice.model_dump()` is the
    schema. The tax question that started this feature ("what CGST did we pay X")
    is answerable from `taxes` here without anyone having remembered to add
    `taxes` to a prompt -- which is exactly what went wrong for `tax_amount`,
    `tax_ids` and `compliance_metadata` before.

    Document context comes from `get_all_invoice_chunks()` -- a direct
    `invoice_id` metadata filter, not a top-k semantic search. Once the invoice is
    known, "the page with the tax table didn't rank high enough" is silent data
    loss, not a relevance decision.

    That retrieval stays complete; what is *shown* is bounded. Measured live on
    2026-08-21 (see `MAX_FULL_RECORD_CHUNK_CHARS`), an 11-page invoice's page
    dump was 16,010 tokens and grows linearly with the page count, so past
    `MAX_FULL_RECORD_CHUNK_CHARS` the first and last page are kept, middle pages
    fill the remaining budget, and the page numbers held back are reported in
    `pages_omitted` -- disclosed on the result exactly like `columns_omitted`,
    never silently dropped.

    Cross-tenant access is refused as `not_found`, never as a distinct error: a
    caller must not be able to learn that an id exists under another tenant.

    `include_document_pages=False` (Gap 310) returns the structured row only and
    skips the Chroma round-trip entirely. Added for Feature 6's chat route, which
    calls this on every turn that identified an invoice: that route already has
    its own document channel (the RAG branch) and its question is always "what
    does the *record* hold", so paying for a page dump measured at up to 16,010
    tokens on an 11-page invoice would be a per-turn cost with no consumer. It is
    the only value any caller passes today — the orchestrator that took the
    `True` default was deleted by Gap 316.
    """
    from models import Invoice

    try:
        wanted = UUID(str(invoice_id))
    except (ValueError, AttributeError, TypeError):
        return FullRecordResult(
            status="error",
            invoice_id=str(invoice_id),
            message=f"{invoice_id!r} is not a valid invoice id.",
        )

    tenant_uuid = _tenant_uuid(tenant_id)
    try:
        invoice = db_session.get(Invoice, wanted)
    except Exception as e:
        logger.warning("Full-record fetch failed for %s: %s", invoice_id, e)
        try:
            db_session.rollback()
        except Exception:
            pass
        return FullRecordResult(status="error", invoice_id=str(wanted), message=str(e))

    if invoice is None or tenant_uuid is None or invoice.tenant_id != tenant_uuid:
        return FullRecordResult(
            status="not_found",
            invoice_id=str(wanted),
            message="No invoice with that id exists for this tenant.",
        )

    dumped = invoice.model_dump()
    record = {
        name: _json_safe(value)
        for name, value in dumped.items()
        if name not in FULL_RECORD_EXCLUDED_COLUMNS
    }

    chunks = [
        {
            "chunk_id": chunk.get("id"),
            "document": chunk.get("document"),
            "page": (chunk.get("metadata") or {}).get("page"),
            "vendor_name": (chunk.get("metadata") or {}).get("vendor_name"),
            "invoice_id": (chunk.get("metadata") or {}).get("invoice_id") or str(wanted),
            "matched_by": chunk.get("matched_by"),
        }
        for chunk in (
            get_all_invoice_chunks(str(wanted), str(tenant_id))
            if include_document_pages
            else []
        )
    ]
    total_pages = len(chunks)
    chunks, pages_omitted = bound_document_pages(chunks)
    if pages_omitted:
        logger.info(
            "get_full_record: %s of %s document pages held back for invoice %s (over %d chars)",
            len(pages_omitted),
            total_pages,
            wanted,
            MAX_FULL_RECORD_CHUNK_CHARS,
        )

    return FullRecordResult(
        status="ok",
        invoice_id=str(wanted),
        record=record,
        chunks=chunks,
        columns_omitted=list(FULL_RECORD_EXCLUDED_COLUMNS),
        pages_omitted=pages_omitted,
        total_document_pages=total_pages,
        # Surfaced as its own field, not left for a reader to notice inside the
        # record: an answer about an amount on a duplicate-flagged invoice should
        # say so rather than treating the figure as clean.
        has_alerts=bool(record.get("sa_alerts")),
    )


# ---------------------------------------------------------------------------
# Tool 5 — compute
# ---------------------------------------------------------------------------

SUM_BY_CURRENCY = "sum_by_currency"
RECONCILE_LINE_ITEMS = "reconcile_line_items"
COMPUTE_OPERATIONS = (SUM_BY_CURRENCY, RECONCILE_LINE_ITEMS)

_NO_EXCHANGE_RATE_NOTE = (
    "Totals are per currency and are never added across currencies -- no exchange "
    "rate is available. State each currency's total separately."
)


@dataclass(frozen=True)
class ComputeResult:
    """Outcome of one `compute` call. `status` is `"ok"` or `"error"`.

    `by_currency` (sum) and `rows`/`mismatches` (reconcile) are the payload;
    `formatted` is the same figures pre-rendered as `"USD 400.00"` strings so a
    caller quoting them into an answer cannot reintroduce a rounding or
    currency-labelling mistake on the way out.
    """

    status: str
    operation: str
    by_currency: dict[str, float] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    rows: list[dict] = field(default_factory=list)
    mismatches: list[dict] = field(default_factory=list)
    formatted: list[str] = field(default_factory=list)
    all_match: Optional[bool] = None
    note: Optional[str] = None
    message: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def _to_decimal(value: Any) -> Decimal:
    """Exact decimal from whatever the row actually carried.

    Via `str()` on purpose: `Decimal(0.08)` is 0.08000000000000000166..., which
    is how a float total picks up the garbage digits this codebase has already
    had to strip out of rendered results twice (Gaps 266, 272). Strings are
    tolerated with thousands separators and a currency symbol stripped, because
    real callers pass values lifted out of a rendered results table.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # bool is an int subclass; never a money value
        raise InvalidOperation("boolean is not a numeric amount")
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("$", "").replace("₹", "").replace("€", "")
        return Decimal(cleaned)
    raise InvalidOperation(f"unsupported numeric value: {value!r}")


def _money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY, rounding=ROUND_HALF_UP)


def _currency_of(entry: Any, fallback: Any = None) -> str:
    raw = fallback
    if isinstance(entry, dict):
        raw = entry.get("currency", fallback)
    code = str(raw).strip().upper() if raw is not None else ""
    return code or UNKNOWN_CURRENCY


def _amount_and_currency(entry: Any) -> tuple[Decimal, str]:
    """Accept `{"amount": ..., "currency": ...}` or a plain `(amount, currency)` pair."""
    if isinstance(entry, dict):
        if "amount" not in entry:
            raise KeyError("each value needs an 'amount'")
        return _to_decimal(entry["amount"]), _currency_of(entry)
    if isinstance(entry, (list, tuple)):
        if len(entry) != 2:
            raise ValueError("a pair must be exactly (amount, currency)")
        return _to_decimal(entry[0]), _currency_of(None, entry[1])
    raise TypeError(f"unsupported value: {entry!r}")


def compute(operation: str, values: Iterable[Any]) -> ComputeResult:
    """Deterministic arithmetic over amounts the turn has already retrieved.

    No LLM call, no prompt, no judgment: this exists so that "add these up" and
    "does this line reconcile?" are function calls with one right answer, instead
    of instructions an LLM weighs against every other instruction in its prompt.
    That is the specific failure the original Feature 21 shipped — a
    faithfulness mandate that made the model hedge on arithmetic it should simply
    have done — and it is not fixable by wording.

    Two operations:

    `sum_by_currency` — values are `{"amount": ..., "currency": ...}` mappings or
    `(amount, currency)` pairs. Totals are grouped by currency and **never**
    combined across currencies; there is no exchange rate anywhere in this
    product, and the existing SQL summary prompt already states that rule in
    prose. Here it is structural: there is no field on the result that could hold
    a cross-currency total. An amount with no readable currency lands in its own
    `UNKNOWN` bucket rather than being assumed to be USD.

    `reconcile_line_items` — values are line-item mappings with `quantity`,
    `unit_price` and the stored `amount` (plus optional `description` and
    `currency`). Returns, per row, the stored amount, the computed
    `quantity x unit_price`, whether they agree, and the difference. This is the
    shape the SQL summary prompt's "EXCEPTION -- reconciliation/mismatch
    questions" paragraph describes: found live (US tenant test, Q4/Q10), the
    model printed "5000.00 units x USD 0.08 = USD 420.00" — a false equation,
    since 5000 x 0.08 is 400.00. A caller with this result cannot state that
    equation, because `matches` is False and both figures are right there.

    Any malformed input returns `status="error"` with a message naming the
    problem. It never silently skips an entry: a dropped amount is a wrong total
    that looks like a right one.
    """
    op = (operation or "").strip().lower()
    if op not in COMPUTE_OPERATIONS:
        return ComputeResult(
            status="error",
            operation=operation,
            message=f"Unknown operation {operation!r}. Supported: {', '.join(COMPUTE_OPERATIONS)}.",
        )

    entries = list(values or [])
    if op == SUM_BY_CURRENCY:
        totals: dict[str, Decimal] = {}
        counts: dict[str, int] = {}
        for index, entry in enumerate(entries):
            try:
                amount, currency = _amount_and_currency(entry)
            except (KeyError, ValueError, TypeError, InvalidOperation) as e:
                return ComputeResult(
                    status="error",
                    operation=op,
                    message=f"value at index {index} could not be read as an amount: {e}",
                )
            totals[currency] = totals.get(currency, Decimal("0")) + amount
            counts[currency] = counts.get(currency, 0) + 1

        ordered = sorted(totals.items(), key=lambda kv: kv[0])
        return ComputeResult(
            status="ok",
            operation=op,
            by_currency={code: float(_money(total)) for code, total in ordered},
            counts={code: counts[code] for code, _ in ordered},
            formatted=[f"{code} {_money(total):,.2f}" for code, total in ordered],
            note=_NO_EXCHANGE_RATE_NOTE,
        )

    rows: list[dict] = []
    mismatches: list[dict] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            return ComputeResult(
                status="error",
                operation=op,
                message=f"value at index {index} must be a mapping with quantity/unit_price/amount",
            )
        try:
            quantity = _to_decimal(entry["quantity"])
            unit_price = _to_decimal(entry["unit_price"])
            stated = _to_decimal(entry["amount"])
        except KeyError as e:
            return ComputeResult(
                status="error",
                operation=op,
                message=f"value at index {index} is missing {e}",
            )
        except (ValueError, TypeError, InvalidOperation) as e:
            return ComputeResult(
                status="error",
                operation=op,
                message=f"value at index {index} could not be read as a number: {e}",
            )

        computed = _money(quantity * unit_price)
        stated = _money(stated)
        difference = _money(stated - computed)
        currency = _currency_of(entry)
        row = {
            "description": entry.get("description"),
            "currency": currency,
            "quantity": float(quantity),
            "unit_price": float(unit_price),
            "stated_amount": float(stated),
            "computed_amount": float(computed),
            "matches": difference == 0,
            "difference": float(difference),
        }
        rows.append(row)
        if not row["matches"]:
            mismatches.append(row)

    return ComputeResult(
        status="ok",
        operation=op,
        rows=rows,
        mismatches=mismatches,
        all_match=not mismatches,
        formatted=[
            (
                f"{row['description'] or 'line'}: {row['currency']} {row['stated_amount']:,.2f} stated, "
                f"{row['quantity']:g} x {row['currency']} {row['unit_price']:,.2f} computes to "
                f"{row['currency']} {row['computed_amount']:,.2f} -- "
                f"{row['currency']} {abs(row['difference']):,.2f} mismatch"
            )
            if not row["matches"]
            else (
                f"{row['description'] or 'line'}: {row['quantity']:g} x {row['currency']} "
                f"{row['unit_price']:,.2f} = {row['currency']} {row['stated_amount']:,.2f}"
            )
            for row in rows
        ],
    )

