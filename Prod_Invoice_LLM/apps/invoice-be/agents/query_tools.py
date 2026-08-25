"""Feature 21 — SAGE's tool set.

Behind `ENABLE_AGENTIC_SAGE` (default off). `agents/sage_orchestrator.py` is the
only caller; `run_query_agent()`'s classify-and-fork pipeline is untouched and
still the default for every tenant.

**What the tool set is, and why it is shaped this way** (design:
`docs/feature_21_rag_faithfulness.md`, mechanism: `docs/feature_21_architecture.md`):

  * `identify_invoices` / `get_full_record` — the split that is the actual fix.
    Chat kept getting tax and detail questions wrong not because the data was
    missing, but because one narrow, hand-typed ~19-column schema description
    was the only thing the SQL-writing model ever saw, and extraction grew far
    past it (`taxes`, `tax_ids`, `compliance_metadata`, `payment_instructions`,
    `references`, `discounts`, `deductions` are all real, populated, and were all
    invisible). Identify is a *narrow lookup* -- the six columns you need to find
    a row -- and is the only hand-maintained schema left for the
    single-invoice case. Fetch reflects the live ORM row, so a column added
    tomorrow is answerable tomorrow with no prompt edit at all.
  * `search_invoices` — discovery, for "which invoices relate to X" when nothing
    is identified yet. Semantic retrieval plus a structured category match.
  * `aggregate` — cross-invoice totals, the one remaining schema-aware SQL path,
    kept deliberately in one auditable place. Its category-match OR-group is
    built from every text/JSONB column reflected off the live model except
    `addresses`, replacing rule 6b's hardcoded four.
  * `compute` / `ask_clarifying_question` — unchanged from Phase 1 and correct as
    built. Both are deliberately LLM-free: the original Feature 21 failed because
    correctness was expressed as more prose in a prompt that already had prose
    rules to obey, and these two move "add these numbers" and "don't guess, ask"
    into function calls that cannot be talked out of their behaviour.

Every tool returns a small frozen dataclass with an explicit `status`, plus
`to_dict()` (a LangChain tool has to hand the model something JSON-shaped).
`status` is always one of the documented literals — an orchestrator branching on
`"no_results"` vs `"error"` vs `"declined"` is a fact about what happened, not an
inference from prose the model has to read.

**Deterministic layers, on purpose.** Several rules the prompts state in prose are
*also* enforced here in code — normalized vendor-name matching, the
more-than-one-candidate clarification, the zero-total and mixed-currency checks,
the fiscal-year assumption. That is not belt-and-braces; it is this feature's
whole thesis. A prose rule fires only when a phrasing resembles what it was
written against (rule 6d's tax-component miss is the standing example). A
function fires every time.

Tenant scoping: `tenant_id` and `db_session` are ordinary positional parameters
here, but they are NOT model-controlled tool arguments — `_ToolBox` closes over
the authenticated request's tenant, so the only thing the model chooses is the
question text.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Optional
from uuid import UUID

from pydantic import BaseModel, Field as PydanticField

from chroma_client import get_all_invoice_chunks, query_invoice_chunks

from agents.query_agent import (
    MAX_SNAPSHOT_INVOICE_IDS,
    NO_RECORDS_FOUND,
    _FROM_INVOICE_TAIL,
    _INJECTION_GUARD_INSTRUCTION,
    _business_rules_block,
    _chat_rules_block,
    _get_global_business_rules,
    _get_tenant_stats_summary,
    _get_vendor_business_rules,
    _harvest_invoice_ids_via_companion_query,
    _line_item_rule,
    _prior_sql_block_for,
    _wrap_user_input,
    run_sql_generation_loop,
)
from agents.sage_prompts import (
    build_aggregate_system_prompt,
    build_identify_system_prompt,
    render_category_match_clause,
)
from telemetry import tracked_llm_call
from utils.llm import get_llm

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

# How many candidate rows `identify_invoices` will describe back. A lookup that
# matches more than this is not a lookup -- it is a discovery or aggregate
# question that reached the wrong tool, and saying so is more useful than
# rendering 400 candidates into the planner's context.
MAX_IDENTIFY_CANDIDATES = 25


# ---------------------------------------------------------------------------
# Shared helpers — results tables, name normalization, SQL literals
# ---------------------------------------------------------------------------

# A column worth totalling. Matched on the header name, because the header is the
# only thing that says what a number *means* -- summing a column of quantities or
# unit prices produces a figure with no referent, which is worse than no figure.
# Lives here rather than in the orchestrator because two callers now need it:
# `_grounded_arithmetic()` (which sums money columns) and `aggregate()` (which
# has to notice that every money column came back zero).
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


# Legal-form suffixes stripped before two names are compared. The business-analyst
# review's own example is the reason this exists in code rather than in prose:
# "Om Packaging" / "Om Packaging Pvt Ltd" / "OM PACKAGING" are one real vendor
# captured three ways, and a plain LIKE treats them as three, silently
# undercounting a real vendor's total.
_LEGAL_SUFFIXES = (
    "private limited", "pvt ltd", "pte ltd", "limited", "ltd", "llc", "llp", "plc",
    "incorporated", "inc", "corporation", "corp", "company", "co", "gmbh", "bv",
    "nv", "ag", "sarl", "sas", "pty", "srl", "spa",
)


def normalize_entity_name(name: Optional[str]) -> str:
    """Case-folded, punctuation-free, legal-suffix-free form of a vendor/customer name.

    `"Om Packaging Pvt. Ltd."` and `"OM  PACKAGING"` both normalize to
    `"om packaging"`. Used for matching only -- the raw stored name is what is
    ever shown to a user or written into SQL.
    """
    text_value = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    text_value = re.sub(r"\s+", " ", text_value).strip()
    changed = True
    while changed and text_value:
        changed = False
        for suffix in _LEGAL_SUFFIXES:
            if text_value == suffix:
                return ""
            if text_value.endswith(" " + suffix):
                text_value = text_value[: -(len(suffix) + 1)].strip()
                changed = True
                break
    return text_value


def _names_match(left: str, right: str) -> bool:
    """Normalized names that plausibly refer to the same entity.

    Containment in either direction, not equality: a user says "Cascade
    Manufacturing" for a stored "Cascade Manufacturing Co", and after suffix
    stripping the remaining difference is usually a word the user left off
    ("Solutions", "Group"). Both sides must be non-empty, so a name that
    normalizes away entirely never matches everything.
    """
    if not left or not right:
        return False
    return left in right or right in left


# The literal inside a `vendor_name`/`customer_name` LIKE or = predicate, however
# many LOWER()/TRIM() wrappers the model put around the column. Used to recover
# *which entity the question named* from the SQL the model actually wrote --
# reading it back off the generated query rather than re-parsing the user's
# sentence, because the query is the model's own committed interpretation.
_NAME_PREDICATE_LITERAL = re.compile(
    r"\b(?:vendor_name|customer_name)\s*\)*\s*(?:NOT\s+)?(?:LIKE|=)\s*"
    r"(?:LOWER\s*\(\s*|TRIM\s*\(\s*LOWER\s*\(\s*)?'([^']*)'",
    re.IGNORECASE,
)


def _named_entity_phrases(sql: Optional[str]) -> list[str]:
    """Every distinct entity phrase the generated SQL filtered a name column on."""
    phrases: list[str] = []
    for raw in _NAME_PREDICATE_LITERAL.findall(sql or ""):
        phrase = raw.strip().strip("%").strip()
        if phrase and phrase not in phrases:
            phrases.append(phrase)
    return phrases


def _sql_literal(value: str) -> str:
    return str(value).replace("'", "''")


def _tenant_uuid(tenant_id) -> Optional[UUID]:
    try:
        return UUID(str(tenant_id))
    except (ValueError, AttributeError, TypeError):
        return None


def _distinct_entity_names(tenant_id: str, db_session) -> list[tuple[str, str]]:
    """Every distinct `(column, name)` this tenant has, for normalized matching.

    Read through the ORM rather than by generating more SQL: this is a fixed,
    known query, and the point of the normalized-matching layer is to be the part
    of name resolution that a model cannot get wrong.
    """
    from models import Invoice
    from sqlmodel import select

    tenant_uuid = _tenant_uuid(tenant_id)
    if tenant_uuid is None:
        return []
    try:
        rows = db_session.exec(
            select(Invoice.vendor_name, Invoice.customer_name)
            .where(Invoice.tenant_id == tenant_uuid)
            .distinct()
        ).all()
    except Exception as e:
        logger.warning("Entity-name lookup failed for tenant %s: %s", tenant_id, e)
        try:
            db_session.rollback()
        except Exception:
            pass
        return []

    names: list[tuple[str, str]] = []
    for vendor_name, customer_name in rows:
        for column, value in (("vendor_name", vendor_name), ("customer_name", customer_name)):
            if value and (column, value) not in names:
                names.append((column, value))
    return names


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
# Tool 1 — identify_invoices
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdentifyResult:
    """Which invoice(s) a question concerns. Never their detail.

    `status`:
      * `"ok"`          — one or more candidates; `candidates` carries the six
                          identifying columns per row and `invoice_ids` is what
                          `get_full_record` is called with.
      * `"no_results"`  — the lookup ran correctly, including the normalized
                          name retry, and matched nothing. A real answer.
      * `"too_many"`    — more matches than a lookup can meaningfully return;
                          the question is an aggregate/discovery one.
      * `"declined"`    — the model returned `sql: null` (rule 8).
      * `"error"`       — every attempt raised.

    `name_normalized_retry` is True when the first query matched nothing and a
    deterministic normalized-name retry is what produced these rows. That retry
    deliberately drops the original query's other restrictions (see
    `_retry_with_normalized_names`), so a caller must not present its rows as if
    they still satisfied a date or amount filter.
    """

    status: str
    candidates: list[dict] = field(default_factory=list)
    invoice_ids: list[str] = field(default_factory=list)
    generated_sql: Optional[str] = None
    results_markdown: Optional[str] = None
    name_normalized_retry: bool = False
    message: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def identify_invoices(
    question: str,
    tenant_id: str,
    db_session,
    *,
    llm=None,
    chat_history: str = "",
    prior_turn_sql: Optional[str] = None,
    max_attempts: int = 3,
):
    """Find which invoice(s) a question is about, and nothing else.

    Returns an `IdentifyResult`, or a `ClarificationRequest` when normalized
    matching surfaced more than one distinct-looking entity for a single named
    entity — the turn then ends in a question rather than an answer about
    whichever entity happened to sort first.

    Three layers, in order, and the second and third are deterministic on
    purpose:

      1. **Generated SQL**, from `build_identify_system_prompt()`'s six-column
         schema and rules 1-6. Runs through the same
         `run_sql_generation_loop()` the default path uses, so the tenant-isolation
         safety check, the string-equality normalization, the 3-attempt repair
         loop and the invoice-number fallback all still apply.
      2. **Normalized-name retry** when that matched nothing
         (`_retry_with_normalized_names`) — legal suffixes stripped, case and
         whitespace folded, matched against this tenant's real distinct names.
      3. **Ambiguity check** (`_ambiguous_entity_clarification`) — one named
         entity resolving to two distinct stored names is not something to guess
         at. Considered and rejected in design: disambiguating via
         `tax_ids`/GSTIN, because picking one silently risks answering the wrong
         legal entity's question with confidence.
    """
    llm = llm or get_llm()

    system_prompt = build_identify_system_prompt(
        tenant_id,
        chat_history=chat_history,
        prior_sql_block=_prior_sql_block_for(prior_turn_sql),
        injection_guard=_INJECTION_GUARD_INSTRUCTION,
    )

    snapshot: list[str] = []
    outcome = run_sql_generation_loop(
        llm=llm,
        system_prompt=system_prompt,
        wrapped_user_message=_wrap_user_input(question, tenant_id),
        user_message=question,
        tenant_id=tenant_id,
        db_session=db_session,
        prior_turn_sql=prior_turn_sql,
        snapshot=snapshot,
        max_attempts=max_attempts,
        telemetry_agent_name="sage.identify",
    )

    if outcome.declined_text is not None:
        return IdentifyResult(
            status="declined",
            generated_sql=outcome.generated_sql,
            message=outcome.declined_text,
        )
    if outcome.db_result is None:
        return IdentifyResult(
            status="error",
            generated_sql=outcome.generated_sql,
            message=str(outcome.last_error) if outcome.last_error else "Lookup failed.",
        )

    generated_sql = outcome.generated_sql
    markdown = outcome.db_result
    retried = False

    if markdown == NO_RECORDS_FOUND:
        retry = _retry_with_normalized_names(generated_sql, tenant_id, db_session, snapshot)
        if retry is None:
            return IdentifyResult(
                status="no_results",
                generated_sql=generated_sql,
                results_markdown=NO_RECORDS_FOUND,
                message=(
                    "No invoice matched, including after normalizing the name "
                    "(case, whitespace and legal suffixes). Nothing matches -- the "
                    "lookup itself did not fail."
                ),
            )
        markdown, generated_sql = retry
        retried = True

    invoice_ids = list(dict.fromkeys(snapshot))
    if not invoice_ids and generated_sql:
        invoice_ids = _harvest_invoice_ids_via_companion_query(
            generated_sql, tenant_id, db_session
        )

    candidates = _load_candidates(invoice_ids, tenant_id, db_session)
    if not candidates:
        # Ids could not be recovered (an unreconstructible predicate, a join this
        # code deliberately refuses to rebuild). The rows are still real, so
        # report them from the table rather than claiming nothing was found.
        parsed = parse_results_table(markdown)
        if parsed:
            columns, rows = parsed
            candidates = [dict(zip(columns, row)) for row in rows[:MAX_IDENTIFY_CANDIDATES]]

    if len(candidates) > MAX_IDENTIFY_CANDIDATES:
        return IdentifyResult(
            status="too_many",
            invoice_ids=invoice_ids[:MAX_IDENTIFY_CANDIDATES],
            candidates=candidates[:MAX_IDENTIFY_CANDIDATES],
            generated_sql=generated_sql,
            results_markdown=markdown,
            name_normalized_retry=retried,
            message=(
                f"{len(candidates)} invoices match. That is a cross-invoice question, "
                "not a lookup -- use aggregate for a total, or narrow the question."
            ),
        )

    clarification = _ambiguous_entity_clarification(generated_sql, candidates)
    if clarification is not None:
        return clarification

    return IdentifyResult(
        status="ok",
        candidates=candidates,
        invoice_ids=invoice_ids,
        generated_sql=generated_sql,
        results_markdown=markdown,
        name_normalized_retry=retried,
        message=(
            "The original filter matched nothing; these rows come from a "
            "name-normalized retry that dropped the query's other restrictions "
            "(dates, amounts). Check each row against the question before using it."
            if retried
            else None
        ),
    )


def _retry_with_normalized_names(
    generated_sql: Optional[str], tenant_id: str, db_session, snapshot: list
) -> Optional[tuple[str, str]]:
    """Re-run a zero-result lookup against normalized entity names.

    The whole reason this is a separate, deliberately *broader* query rather than
    a rewrite of the original one: rewriting predicates inside generated SQL by
    regex is a mechanism this repo already tried and removed (see
    `_sql_dialect_name()`'s docstring -- a regex rewriter can only ever cover the
    syntactic shapes it was written against). So this rebuilds a clean
    `vendor_name IN (...)` / `customer_name IN (...)` lookup from the tenant's
    real stored names, drops the original's other restrictions, and the caller
    labels the result as broadened (`name_normalized_retry`) so nothing
    downstream presents it as if the date filter had survived.

    Returns `(markdown, sql)` or None when nothing normalized-matches either.
    """
    phrases = _named_entity_phrases(generated_sql)
    if not phrases:
        return None

    stored = _distinct_entity_names(tenant_id, db_session)
    if not stored:
        return None

    matched: dict[str, list[str]] = {"vendor_name": [], "customer_name": []}
    for phrase in phrases:
        normalized_phrase = normalize_entity_name(phrase)
        for column, name in stored:
            if _names_match(normalized_phrase, normalize_entity_name(name)):
                if name not in matched[column]:
                    matched[column].append(name)
    if not matched["vendor_name"] and not matched["customer_name"]:
        return None

    branches = [
        f"{column} IN ({', '.join(chr(39) + _sql_literal(name) + chr(39) for name in names)})"
        for column, names in matched.items()
        if names
    ]
    sql = (
        "SELECT id, vendor_name, customer_name, invoice_number, invoice_date, "
        "grand_total, currency FROM invoice "
        f"WHERE tenant_id = '{_sql_literal(str(tenant_id))}' AND ({' OR '.join(branches)})"
    )

    from agents.query_agent import execute_generated_sql

    snapshot.clear()
    try:
        markdown = execute_generated_sql(sql, tenant_id, db_session, snapshot=snapshot)
    except Exception as e:
        logger.warning("Normalized-name retry failed (non-fatal): %s", e)
        try:
            db_session.rollback()
        except Exception:
            pass
        return None
    if markdown == NO_RECORDS_FOUND:
        return None
    logger.info("identify_invoices: normalized-name retry matched %s", matched)
    return markdown, sql


def _load_candidates(invoice_ids: list[str], tenant_id: str, db_session) -> list[dict]:
    """The six identifying columns for each recovered id, in the order given.

    Read through the ORM rather than trusting whatever the model put in its
    SELECT list: `get_full_record` needs a real id, and a candidate row a user is
    asked to choose between needs the same fields every time.
    """
    if not invoice_ids:
        return []

    from models import Invoice
    from sqlmodel import select

    tenant_uuid = _tenant_uuid(tenant_id)
    if tenant_uuid is None:
        return []
    wanted: list[UUID] = []
    for invoice_id in invoice_ids:
        try:
            wanted.append(UUID(str(invoice_id)))
        except (ValueError, AttributeError, TypeError):
            continue
    if not wanted:
        return []

    try:
        rows = db_session.exec(
            select(Invoice).where(Invoice.tenant_id == tenant_uuid, Invoice.id.in_(wanted))
        ).all()
    except Exception as e:
        logger.warning("Candidate load failed: %s", e)
        try:
            db_session.rollback()
        except Exception:
            pass
        return []

    by_id = {str(row.id): row for row in rows}
    candidates = []
    for invoice_id in invoice_ids:
        row = by_id.get(str(invoice_id))
        if row is None:
            continue
        candidates.append(
            {
                "id": str(row.id),
                "vendor_name": row.vendor_name,
                "customer_name": row.customer_name,
                "invoice_number": row.invoice_number,
                "invoice_date": _json_safe(row.invoice_date),
                "flow_direction": row.flow_direction,
                "grand_total": row.grand_total,
                "currency": row.currency,
            }
        )
    return candidates


def _ambiguous_entity_clarification(generated_sql: Optional[str], candidates: list[dict]):
    """Ask, when one named entity resolved to two distinct stored names.

    The decision this implements (2026-08-21): a near-duplicate name could be one
    vendor typed inconsistently or two real legal entities that share a name, and
    there is no field that reliably tells them apart. Rather than resolving it
    silently, the turn ends in a question.

    Deliberately keyed on the entity phrases in the *generated SQL*, one at a
    time, not on "the result has two vendors in it" -- rule 6's comparison
    questions ("between DataPipe and StratEdge, whose total was bigger") name two
    entities on purpose and must not be turned into a clarifying question. Two
    phrases resolving to one name each is a comparison; one phrase resolving to
    two names is the ambiguity.
    """
    phrases = _named_entity_phrases(generated_sql)
    if not phrases or not candidates:
        return None

    for phrase in phrases:
        normalized_phrase = normalize_entity_name(phrase)
        if not normalized_phrase:
            continue
        matched_names: list[str] = []
        for candidate in candidates:
            for key in ("vendor_name", "customer_name"):
                name = candidate.get(key)
                if not name:
                    continue
                if _names_match(normalized_phrase, normalize_entity_name(name)):
                    if name not in matched_names:
                        matched_names.append(name)
        if len(matched_names) > 1:
            listed = ", ".join(f'"{name}"' for name in matched_names)
            return ask_clarifying_question(
                f"I found more than one match for \"{phrase}\": {listed}. "
                "These could be the same company recorded under different names, or two "
                "different companies -- which one do you mean?",
                AMBIGUOUS_ENTITY,
            )
    return None


# ---------------------------------------------------------------------------
# Tool 2 — get_full_record
# ---------------------------------------------------------------------------

# The only columns held back from a "full" record, named here so the omission is
# reviewable instead of invisible -- and reported on every result in
# `columns_omitted`. `feature_21_architecture.md` says "every column, no
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
# Set from measurement, not from intuition (live run 2026-08-21, real gpt-5-mini,
# `scripts/run_agent_eval.py`; full numbers in `feature_21_architecture.md` B4):
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
    skips the Chroma round-trip entirely. Added for the default (non-SAGE) chat
    route, which calls this on every turn that identified an invoice: that route
    already has its own document channel (the RAG branch) and its question is
    always "what does the *record* hold", so paying for a page dump measured at
    up to 16,010 tokens on an 11-page invoice would be a per-turn cost with no
    consumer. SAGE keeps the default, so its behaviour is byte-identical.
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
# Tool 3 — search_invoices
# ---------------------------------------------------------------------------

# Rule 6c in code. "freight costs" searches for '%freight%', never
# '%freight costs%' -- no line item or tag is ever literally called "freight
# costs". Deterministic because the rule has been ignored live before.
_GENERIC_SPEND_WORDS = (
    "costs", "cost", "spend", "spending", "expenses", "expense", "charges", "charge",
    "invoices", "invoice", "bills", "bill", "purchases", "purchase", "payments",
    "payment", "total", "totals", "related",
)

# What survives into a LIKE literal. Anything else is dropped rather than escaped:
# these phrases are built from model output and interpolated into SQL, and the
# safest treatment of an unexpected character in that position is to not have it.
_LIKE_PHRASE_ALLOWED = re.compile(r"[^a-z0-9 &/.\-]+")

# Words `execute_generated_sql`'s safety check refuses anywhere in a query. A
# phrase carrying one would make the whole search fail as "mutating SQL", so it
# is dropped from the phrase instead.
_MUTATING_WORDS = ("insert", "update", "delete", "drop", "alter", "create", "replace", "truncate")

MAX_SEARCH_PHRASES = 3


class CategoryPhrasesSchema(BaseModel):
    """What `search_invoices` asks the model for -- phrases, not SQL."""

    phrases: list[str] = PydanticField(
        default_factory=list,
        description=(
            "The category/subject phrases this question is about, each a complete "
            "phrase as it would appear on an invoice."
        ),
    )


_SEARCH_PHRASE_PROMPT = """Extract the category or subject phrases a search over invoice text should look for.

Rules:
1. Keep each phrase WHOLE. "office supplies" is one phrase, never "office" and "supplies"
   separately -- a bare word from the middle of a phrase matches unrelated categories.
2. If the question names two or more ALTERNATIVES joined by "or" ("logistics or freight"),
   return one phrase per alternative.
3. Strip the generic spend words a user tacks on -- costs, spend, expenses, charges, invoices,
   bills, purchases. "freight costs" is the phrase "freight".
4. Return an empty list if the question names no category at all (a greeting, a question about
   this platform, a question about one specific invoice number).
5. Never return more than three phrases.

Question: {question}
"""


def _sanitize_like_phrase(phrase: str) -> str:
    cleaned = _LIKE_PHRASE_ALLOWED.sub(" ", (phrase or "").lower())
    words = [
        word
        for word in cleaned.split()
        if word not in _GENERIC_SPEND_WORDS
        and word not in _MUTATING_WORDS
        # A token with no letter or digit left in it is punctuation that survived
        # the allowlist (`--`, `.`, `/`). Nothing good comes of putting it in a
        # LIKE pattern.
        and any(character.isalnum() for character in word)
    ]
    return " ".join(words).strip()


@dataclass(frozen=True)
class SearchInvoicesResult:
    """Discovery: which invoices relate to X, when none is identified yet.

    `status` is `"ok"` / `"no_results"` / `"error"`, for the same reason every
    other tool here separates them: "retrieval found nothing" and "retrieval
    broke" call for different next moves, and a caller should never have to tell
    them apart by reading a message string.

    Both halves of the hybrid are reported separately (`chunks` from semantic
    retrieval, `results_markdown` from the structured category match) rather than
    merged -- they are different kinds of evidence and a caller should be able to
    see which one carried a result.
    """

    status: str
    chunks: list[dict] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    results_markdown: Optional[str] = None
    generated_sql: Optional[str] = None
    invoice_ids: list[str] = field(default_factory=list)
    message: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def search_invoices(
    question: str,
    tenant_id: str,
    db_session=None,
    *,
    llm=None,
    limit: int = 5,
) -> SearchInvoicesResult:
    """Semantic + structured discovery over this tenant's invoices.

    The semantic half is the existing `chroma_client.query_invoice_chunks()` --
    same per-tenant collection (isolation is structural, Gap 55), same hybrid
    keyword+vector rerank and relevance threshold (Gaps 21/22/244). Nothing about
    retrieval or indexing is changed here; this feature is about how SAGE *uses*
    what is already indexed.

    The structured half is rules 6b/6c, restructured: the LLM extracts the
    category *phrases* and code builds the SQL, rather than the LLM writing SQL.
    Rule 6c ("never decompose a multi-word phrase", "strip generic spend words")
    is then enforced by `_sanitize_like_phrase()` on the way through -- it is a
    string operation, and a string operation that runs every time beats an
    instruction that fires when the phrasing resembles its examples. The OR-group
    itself comes from `render_category_match_clause()`, i.e. every text/JSONB
    column reflected off the live model except `addresses`.

    `db_session`/`llm` are optional: without them the structured half is skipped
    and this degrades to pure semantic retrieval rather than failing.

    Deliberately does NOT do the RAG route's citation-existence check against
    Postgres (Gap 239) -- that is a property of *presenting* a citation, and the
    orchestrator owns it at the point citations are actually rendered.
    """
    chunks: list[dict] = []
    chunk_error: Optional[str] = None
    try:
        for chunk in query_invoice_chunks(tenant_id, question, limit=limit):
            metadata = chunk.get("metadata") or {}
            chunks.append(
                {
                    "chunk_id": chunk.get("id"),
                    "document": chunk.get("document"),
                    "invoice_id": metadata.get("invoice_id"),
                    "vendor_name": metadata.get("vendor_name"),
                    "page": metadata.get("page"),
                    "distance": chunk.get("distance"),
                    # Gap 244: a chunk carried only by the literal-keyword
                    # fallback is weaker evidence than one that matched
                    # semantically, and the caller can see which it got.
                    "matched_by": chunk.get("matched_by"),
                }
            )
    except Exception as e:
        logger.warning("search_invoices retrieval failed for tenant %s: %s", tenant_id, e)
        chunk_error = str(e)

    phrases: list[str] = []
    markdown: Optional[str] = None
    sql: Optional[str] = None
    invoice_ids: list[str] = []

    if llm is not None and db_session is not None:
        phrases = _extract_category_phrases(question, llm, tenant_id)
        if phrases:
            markdown, sql, invoice_ids = _structured_category_search(
                phrases, tenant_id, db_session
            )

    if not chunks and not markdown:
        if chunk_error and not phrases:
            return SearchInvoicesResult(status="error", phrases=phrases, message=chunk_error)
        return SearchInvoicesResult(
            status="no_results",
            phrases=phrases,
            generated_sql=sql,
            message=(
                "Nothing matched: no document chunk passed the relevance threshold and no "
                "invoice field contained the category phrase. This means nothing matched, "
                "not that the tenant has no invoices."
            ),
        )

    return SearchInvoicesResult(
        status="ok",
        chunks=chunks,
        phrases=phrases,
        results_markdown=markdown,
        generated_sql=sql,
        invoice_ids=invoice_ids,
        message=chunk_error and f"Document retrieval failed ({chunk_error}); structured matches only.",
    )


def _extract_category_phrases(question: str, llm, tenant_id: str) -> list[str]:
    """One narrow LLM call: what is this question about? Sanitized on the way out."""
    try:
        structured = llm.with_structured_output(CategoryPhrasesSchema)
        with tracked_llm_call("sage.search", llm=llm, tenant_id=str(tenant_id)):
            result = structured.invoke(_SEARCH_PHRASE_PROMPT.format(question=question))
    except Exception as e:
        logger.warning("Category-phrase extraction failed (non-fatal): %s", e)
        return []

    phrases: list[str] = []
    for raw in (getattr(result, "phrases", None) or [])[:MAX_SEARCH_PHRASES]:
        phrase = _sanitize_like_phrase(str(raw))
        if phrase and phrase not in phrases:
            phrases.append(phrase)
    return phrases


def _structured_category_search(
    phrases: list[str], tenant_id: str, db_session
) -> tuple[Optional[str], Optional[str], list[str]]:
    """Rule 6b's OR-group, built in code from the reflected column list."""
    from agents.query_agent import execute_generated_sql

    groups = [render_category_match_clause(_sql_literal(phrase)) for phrase in phrases]
    # No `id` in the SELECT list, same reasoning as rule 8/rule 6d: this table is
    # rendered to the user, and a column of raw UUIDs is noise. Row identity comes
    # from the Gap 231 companion query instead.
    sql = (
        "SELECT vendor_name, customer_name, invoice_number, invoice_date, "
        "grand_total, currency FROM invoice "
        f"WHERE tenant_id = '{_sql_literal(str(tenant_id))}' "
        f"AND ({' OR '.join(groups)}) "
        f"LIMIT {MAX_SNAPSHOT_INVOICE_IDS}"
    )
    try:
        markdown = execute_generated_sql(sql, tenant_id, db_session)
    except Exception as e:
        logger.warning("Structured category search failed (non-fatal): %s", e)
        try:
            db_session.rollback()
        except Exception:
            pass
        return None, sql, []
    if markdown == NO_RECORDS_FOUND:
        return None, sql, []
    return markdown, sql, _harvest_invoice_ids_via_companion_query(sql, tenant_id, db_session)


# ---------------------------------------------------------------------------
# Tool 4 — aggregate
# ---------------------------------------------------------------------------

# Deterministic ambiguity detector for date ranges, same mechanism (and same
# reasoning) as `detect_tax_component_term()`: "this quarter" is genuinely
# ambiguous between the calendar year and an April-March fiscal year, there is no
# `fiscal_year` setting on the tenant model to resolve it from, and asking an LLM
# to remember to mention its assumption every time is not testable.
_AMBIGUOUS_DATE_RANGE_PATTERN = re.compile(
    r"\b(?:this|last|current|previous|past)\s+(?:quarter|year|fy)\b"
    r"|\b(?:ytd|year[- ]to[- ]date|fiscal\s+year|financial\s+year|q[1-4])\b",
    re.IGNORECASE,
)

CALENDAR_YEAR_ASSUMPTION = (
    "The date range in this question is ambiguous between the calendar year and an "
    "April-March fiscal year. The CALENDAR year was used (Jan-Dec) -- this product has no "
    "fiscal-year setting. Say which basis was used in the answer."
)

STATUS_INCLUSION_NOTE = (
    "Which `status` values count toward spend is not a settled decision in this product, "
    "and soft-deleted rows are not excluded anywhere. If that materially changes this "
    "figure, say what the filter did include."
)


def detect_ambiguous_date_range(question: str) -> Optional[str]:
    """The ambiguous range term this question actually contains, or None."""
    match = _AMBIGUOUS_DATE_RANGE_PATTERN.search(question or "")
    return match.group(0) if match else None


@dataclass(frozen=True)
class AggregateResult:
    """A cross-invoice total, count or breakdown.

    `status`:
      * `"ok"`             — real rows, real figures.
      * `"no_results"`     — the query ran correctly and matched nothing.
      * `"zero_total"`     — rows came back but every monetary total is zero.
        Its own status, not `"ok"`, because "never present a zero as a confident
        total" is only enforceable if the caller can tell the difference without
        reading the numbers.
      * `"multi_currency"` — the query summed money without grouping by
        currency, and this tenant genuinely holds more than one currency under
        that filter. The figure would be a blended, meaningless number.
      * `"declined"` / `"error"` — as everywhere else here.
    """

    status: str
    results_markdown: Optional[str] = None
    generated_sql: Optional[str] = None
    invoice_ids: list[str] = field(default_factory=list)
    currencies: list[str] = field(default_factory=list)
    fiscal_year_note: Optional[str] = None
    status_inclusion_note: Optional[str] = None
    message: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


def aggregate(
    question: str,
    tenant_id: str,
    db_session,
    *,
    llm=None,
    chat_history: str = "",
    prior_turn_sql: Optional[str] = None,
    include_tenant_context: bool = True,
    max_attempts: int = 3,
) -> AggregateResult:
    """Cross-invoice totals — the one remaining schema-aware SQL path.

    "How much did we spend on office supplies this quarter" is not a question
    about identified invoices, and dumping full records of hundreds of rows is
    neither scalable nor what `get_full_record` is for. So this stays its own
    tool, and it is deliberately the ONE place a curated, schema-aware query
    still exists -- the schema-drift surface narrowed to a single auditable
    location instead of being spread across every detail question.

    Its schema block and its rule-4 category columns are both reflected off the
    live `Invoice` model (`agents/sage_prompts.py`), so the hardcoded four
    (`tags`, `items`, `vendor_name`, `customer_name`) that made a packaging
    expense referenced only in a PO note invisible are gone.

    Four things are then checked in code rather than trusted to the prompt, each
    because the prose version has failed live at least once somewhere in this
    product:

      * zero rows and zero totals never come back as `"ok"`;
      * a money total that did not `GROUP BY currency` is verified against the
        tenant's real currencies under the same filter, and reported as
        `"multi_currency"` if it silently blended them;
      * provenance ids are recovered by companion query (Gap 231), never by
        adding `id` to the aggregate's own SELECT list;
      * an ambiguous date range ("this quarter") carries an explicit
        calendar-year assumption into the answer.
    """
    llm = llm or get_llm()

    rules_block = ""
    chat_rules_block = ""
    tenant_stats = ""
    if include_tenant_context:
        business_rules = list(_get_global_business_rules(tenant_id, db_session))
        for rule in _get_vendor_business_rules(tenant_id, question, db_session):
            if rule not in business_rules:
                business_rules.append(rule)
        rules_block = _business_rules_block(business_rules)
        chat_rules_block = _chat_rules_block(tenant_id, db_session)
        tenant_stats = _get_tenant_stats_summary(tenant_id, db_session)

    system_prompt = build_aggregate_system_prompt(
        tenant_id,
        _line_item_rule(tenant_id, db_session),
        chat_history=chat_history,
        prior_sql_block=_prior_sql_block_for(prior_turn_sql),
        injection_guard=_INJECTION_GUARD_INSTRUCTION,
        rules_block=rules_block,
        chat_rules_block=chat_rules_block,
        tenant_stats=tenant_stats,
    )

    snapshot: list[str] = []
    outcome = run_sql_generation_loop(
        llm=llm,
        system_prompt=system_prompt,
        wrapped_user_message=_wrap_user_input(question, tenant_id),
        user_message=question,
        tenant_id=tenant_id,
        db_session=db_session,
        prior_turn_sql=prior_turn_sql,
        snapshot=snapshot,
        max_attempts=max_attempts,
        telemetry_agent_name="sage.aggregate",
    )

    fiscal_term = detect_ambiguous_date_range(question)
    fiscal_note = CALENDAR_YEAR_ASSUMPTION if fiscal_term else None

    if outcome.declined_text is not None:
        return AggregateResult(
            status="declined",
            generated_sql=outcome.generated_sql,
            fiscal_year_note=fiscal_note,
            message=outcome.declined_text,
        )
    if outcome.db_result is None:
        return AggregateResult(
            status="error",
            generated_sql=outcome.generated_sql,
            fiscal_year_note=fiscal_note,
            message=str(outcome.last_error) if outcome.last_error else "Aggregation failed.",
        )
    if outcome.db_result == NO_RECORDS_FOUND:
        return AggregateResult(
            status="no_results",
            results_markdown=NO_RECORDS_FOUND,
            generated_sql=outcome.generated_sql,
            fiscal_year_note=fiscal_note,
            message=(
                "The filter matched no invoices at all. That is not a total of zero -- "
                "say plainly that nothing matched, or ask which filter was meant."
            ),
        )

    markdown = outcome.db_result
    generated_sql = outcome.generated_sql

    # Provenance, per rule 8 / Gap 231: a companion `SELECT id ...` rebuilt from
    # the SAME predicates, never a change to the aggregate's own SELECT list --
    # raw UUIDs in a user-facing results table are noise.
    invoice_ids = list(dict.fromkeys(snapshot))
    if not invoice_ids and generated_sql:
        invoice_ids = _harvest_invoice_ids_via_companion_query(
            generated_sql, tenant_id, db_session
        )

    parsed = parse_results_table(markdown)
    columns = parsed[0] if parsed else []
    rows = parsed[1] if parsed else []
    currencies = _currencies_in_table(columns, rows)

    if _sums_money(generated_sql) and column_index(columns, "currency") is None:
        # Rule 3 in code. Verified against the tenant's real data rather than
        # assumed from the SQL text: a single-currency tenant that omitted
        # GROUP BY currency has produced a correct number, and failing that turn
        # would be its own wrong answer.
        actual = _distinct_currencies_under_same_filter(generated_sql, tenant_id, db_session)
        if len(actual) > 1:
            return AggregateResult(
                status="multi_currency",
                results_markdown=markdown,
                generated_sql=generated_sql,
                invoice_ids=invoice_ids,
                currencies=actual,
                fiscal_year_note=fiscal_note,
                status_inclusion_note=STATUS_INCLUSION_NOTE,
                message=(
                    "This total was summed across " + ", ".join(actual) + " without grouping by "
                    "currency, so it is a blended figure with no meaning. Re-ask with a "
                    "GROUP BY currency, or ask the user which currency they meant. Never "
                    "present this number."
                ),
            )
        currencies = actual or currencies

    if _all_money_totals_are_zero(columns, rows):
        return AggregateResult(
            status="zero_total",
            results_markdown=markdown,
            generated_sql=generated_sql,
            invoice_ids=invoice_ids,
            currencies=currencies,
            fiscal_year_note=fiscal_note,
            status_inclusion_note=STATUS_INCLUSION_NOTE,
            message=(
                "Every monetary figure this query returned is zero. A zero is not a total -- "
                "it means nothing matched under this filter. Say that explicitly, or ask "
                "which filter was meant. Never hand back '0.00' as if it were an answer."
            ),
        )

    return AggregateResult(
        status="ok",
        results_markdown=markdown,
        generated_sql=generated_sql,
        invoice_ids=invoice_ids,
        currencies=currencies,
        fiscal_year_note=fiscal_note,
        status_inclusion_note=STATUS_INCLUSION_NOTE,
    )


_AGGREGATES_MONEY = re.compile(
    r"\b(?:SUM|AVG)\s*\(\s*(?:CASE\b.*?\bEND|[^)]*)\)", re.IGNORECASE | re.DOTALL
)


def _sums_money(sql: Optional[str]) -> bool:
    """Does this query aggregate a monetary column at all?"""
    match = _AGGREGATES_MONEY.search(sql or "")
    return bool(match) and any(
        word in match.group(0).lower() for word in _MONEY_COLUMN_WORDS
    )


def _currencies_in_table(columns: list[str], rows: list[list[str]]) -> list[str]:
    index = column_index(columns, "currency")
    if index is None:
        return []
    seen: list[str] = []
    for row in rows:
        value = (row[index] or "").strip().upper()
        if value and value not in seen:
            seen.append(value)
    return seen


def _all_money_totals_are_zero(columns: list[str], rows: list[list[str]]) -> bool:
    """True when the query returned money columns and every one of them is zero."""
    if not rows:
        return False
    money_indices = [i for i, name in enumerate(columns) if is_summable_money_column(name)]
    if not money_indices:
        return False
    saw_number = False
    for row in rows:
        for index in money_indices:
            value = (row[index] or "").replace(",", "").strip()
            if not value:
                continue
            try:
                amount = Decimal(value)
            except InvalidOperation:
                return False  # not a number column after all; don't judge it
            saw_number = True
            if amount != 0:
                return False
    return saw_number


def _distinct_currencies_under_same_filter(
    sql: str, tenant_id: str, db_session
) -> list[str]:
    """`SELECT DISTINCT currency` rebuilt from an aggregate query's own WHERE clause.

    Same mechanism and same strictness as
    `_harvest_invoice_ids_via_companion_query()` (whose regex it reuses): the tail
    must still carry the tenant guard and must not contain a subquery, or this
    gives up and returns nothing rather than running a query it cannot vouch for.
    """
    from sqlalchemy import text as sa_text

    match = _FROM_INVOICE_TAIL.search(sql or "")
    if not match:
        return []
    tail = (match.group("tail") or "").strip()
    if not re.search(rf"\btenant_id\s*=\s*['\"]?{tenant_id}['\"]?\b", tail, re.IGNORECASE):
        return []
    if re.search(r"\bselect\b|;", tail, re.IGNORECASE):
        return []
    try:
        result = db_session.execute(
            sa_text(f"SELECT DISTINCT currency FROM invoice {tail}")
        )
        return sorted(
            {str(row[0]).strip().upper() for row in result.fetchall() if row[0]}
        )
    except Exception as e:
        logger.warning("Currency companion query failed (non-fatal): %s", e)
        try:
            db_session.rollback()
        except Exception:
            pass
        return []


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
    """Deterministic arithmetic over amounts SAGE has already retrieved.

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


# ---------------------------------------------------------------------------
# Tool 6 — ask_clarifying_question
# ---------------------------------------------------------------------------

# Closed vocabulary, same reasoning as detect_tax_component_term()'s term list:
# a reason code is a fact about *why* the turn stopped, and code that branches on
# it (logging, metrics, a future "was this clarification useful?" signal) needs a
# fixed set to branch on, not free text.
AMBIGUOUS_DIRECTION = "AMBIGUOUS_DIRECTION"
AMBIGUOUS_ENTITY = "AMBIGUOUS_ENTITY"
AMBIGUOUS_TIME_RANGE = "AMBIGUOUS_TIME_RANGE"
AMBIGUOUS_METRIC = "AMBIGUOUS_METRIC"
MULTIPLE_CURRENCIES = "MULTIPLE_CURRENCIES"
UNSUPPORTED_FIELD = "UNSUPPORTED_FIELD"
NO_RESULTS = "NO_RESULTS"
OTHER = "OTHER"

CLARIFICATION_REASONS = (
    AMBIGUOUS_DIRECTION,
    AMBIGUOUS_ENTITY,
    AMBIGUOUS_TIME_RANGE,
    AMBIGUOUS_METRIC,
    MULTIPLE_CURRENCIES,
    UNSUPPORTED_FIELD,
    NO_RESULTS,
    OTHER,
)


@dataclass(frozen=True)
class ClarificationRequest:
    """A turn that must end in a question, not an answer.

    `ends_turn` is True and constant: the whole point is that this is not advice
    to the orchestrator, it is the outcome. A loop that receives one of these
    stops calling tools and returns `question` to the user.
    """

    question: str
    reason: str
    reason_detail: Optional[str] = None
    status: str = "needs_clarification"
    ends_turn: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def ask_clarifying_question(question: str, reason: str) -> ClarificationRequest:
    """Stop and ask, instead of guessing.

    A tool call rather than a prompt instruction, on purpose. Rule 4a is the
    worked example: "has the Titan Steel Distributors invoice been paid" carries
    no direction cue, the model guessed OUTBOUND, filtered `customer_name`,
    correctly matched zero rows, and reported a real INBOUND invoice as not
    found (US tenant live test, Q14/Q15, twice in one session). Rule 4a's
    both-directions query is a good answer to that specific shape; asking the
    user is the general one, and it only exists as a real option if there is
    something concrete to call.

    `reason` is normalized to one of `CLARIFICATION_REASONS`. An unrecognised
    code is not an error — it becomes `OTHER` with the original preserved in
    `reason_detail`, because a model inventing a plausible-but-unknown code
    should still be able to ask its question rather than crash the turn. An
    empty `question` IS an error: a clarification with nothing to ask is not a
    degraded result, it is a bug in the caller.
    """
    text = (question or "").strip()
    if not text:
        raise ValueError("ask_clarifying_question requires a non-empty question")

    raw = (reason or "").strip()
    code = raw.upper().replace(" ", "_").replace("-", "_")
    if code in CLARIFICATION_REASONS:
        return ClarificationRequest(question=text, reason=code)
    return ClarificationRequest(question=text, reason=OTHER, reason_detail=raw or None)
