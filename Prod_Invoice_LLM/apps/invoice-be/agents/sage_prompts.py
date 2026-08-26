"""Feature 21 — SAGE's prompt blocks, as named constants rather than one literal.

**What is live here (updated 2026-08-25 by Gap 306): `PERSONA_BLOCK` and the
schema-reflection half.** The orchestrator these blocks were written for is
deleted (Gap 316); the surviving consumer of both live halves is
`agents/query_agent.py`.

  * `PERSONA_BLOCK` -- Feature 6's shared `CHAT_PERSONA_BLOCK` is derived from it
    (Gap 313); the tax-domain, category-judgment and data-honesty knowledge in it
    is real and in use on the one route that answers users.
  * `invoice_columns()`, `CATEGORY_MATCH_EXCLUDED_COLUMNS`,
    `_category_match_columns_typed()`, `category_match_columns()`,
    `category_match_branches()`, `category_match_expression()`,
    `render_category_match_clause()`, `quoted_column()` -- Gap 306's fix imports
    these. When the SQL route's own generated category query comes back empty,
    the chat path re-runs the search over the reflected column set instead of
    reporting a real invoice as "not found". Gap 316 flagged this machinery as a
    founder call on whether the reflected-schema idea was worth keeping for a
    future non-agentic use; Gap 306 is that use, and it answered the question by
    needing it. The founder call it did NOT answer is the one below.

Still orphaned as of 2026-08-25, unchanged by Gap 306 and still a founder call:
`IDENTIFY_*`, `AGGREGATE_*`, `build_identify_system_prompt()`,
`build_aggregate_system_prompt()` and `aggregate_schema_block()` -- the prompt
text SAGE's two SQL-writing tools were assembled from. Those have zero callers
and zero tests, and nothing in Feature 6 asks a model to write an aggregate from
a reflected schema block, so keeping them is a bet on a future non-agentic use,
exactly as Gap 316 recorded. Flagged rather than deleted, the same way Gap 314
first flagged the orphaned ops-digest telemetry -- note that Gap 314 then went on
to delete that telemetry on 2026-08-26, because it had zero callers *and* zero
plausible future use; these five have zero callers but an open founder question
behind them, which is why they stay.

The doc these blocks were transcribed from (`feature_21_sage.md`) was deleted
with the code; the closing record is `docs/be_features_tracker.md`, Feature 21
and Gap 316, and the full text is in git history.

Named blocks rather than one literal was the original requirement, and it is not
a style preference: every schema-drift bug this rewrite
was opened for (Gaps 263/264/285, the SGST regression) lives inside one long
hand-typed prompt string that nobody wanted to hunt through to change one rule.
So each block below is separately named, separately editable and separately
testable, and the assembled string is produced at call time by a builder --
exactly the shape `build_sql_system_prompt()` already uses in
`agents/query_agent.py`.

Two of the blocks are **reflected off the live `Invoice` model at runtime** rather
than typed out:

  * `aggregate_schema_block()` renders every column the model actually has. A
    column added to `models.py` tomorrow is in this prompt tomorrow, with no
    prompt edit -- which is the whole point of the rewrite.
  * `category_match_columns()` / `render_category_match_clause()` build rule 4's
    OR-group from that same reflection, replacing the hardcoded 4-column list
    (`tags`, `items`, `vendor_name`, `customer_name`) that rule 6b has carried
    since it was written. Gap 306 added `category_match_branches()` /
    `category_match_expression()` alongside them: the same group, same columns,
    same cast decisions, as bound SQLAlchemy expressions rather than text -- the
    form you can actually execute against a tenant's rows.

Nothing in here calls an LLM or opens a database session. It renders text and,
since Gap 306, SQL expression objects; running them is the caller's job.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from models import Invoice

# Postgres's identifier preparer, used only to decide whether a column name has
# to be double-quoted in generated SQL. `references` is a RESERVED word in both
# PostgreSQL and SQLite -- `CAST(references AS TEXT)` is a syntax error, not a
# style nit; the old architecture doc's worked example wrote it unquoted. Every
# clause this module renders goes through here, so the quoting is correct by
# construction instead of by memory.
_IDENTIFIER_PREPARER = postgresql.dialect().identifier_preparer


def quoted_column(name: str) -> str:
    """`references` -> `"references"`; `items` -> `items`. Portable across both engines."""
    return _IDENTIFIER_PREPARER.quote(name)


# ---------------------------------------------------------------------------
# The persona block — shared by the planner prompt and the synthesis prompt
# ---------------------------------------------------------------------------

# Verbatim from Feature 21's design (deleted with the doc; see git history).
# Shared by BOTH prompt builders on purpose: the planner decides which tool to
# reach for and the synthesis step decides what the returned data means, and a
# persona present in only one of them is a persona that disagrees with itself
# halfway through a turn.
PERSONA_BLOCK = """You are SAGE, a financial-documents assistant embedded in an accounts-payable/accounts-receivable
platform. Your audience is accounts-payable staff, controllers, and auditors -- professionals who
read your answers against real invoices and real money, and who will catch it if you're vague or wrong.

TAX DOMAIN KNOWLEDGE
- CGST + SGST together represent one intra-state Indian GST transaction; by law CGST always equals
  SGST on the same invoice. An invoice showing only IGST is an inter-state transaction -- this is
  correct, not a missing component. Never describe an IGST-only invoice as "missing CGST/SGST."
- GSTIN is India's tax registration ID; VAT number and EIN/TIN serve the equivalent role in the EU
  and US respectively. These are jurisdiction-specific labels for the same underlying concept: whose
  tax registration this transaction is filed against.
- IRN, e-Way Bill number, and Peppol ID are compliance/logistics identifiers, not tax amounts -- IRN
  is the invoice reference number issued by India's invoice registration portal, e-Way Bill authorizes
  goods movement, Peppol ID is an e-invoicing network address. Answer from what they represent, not
  just by echoing the field name.
- Under reverse charge (RCM), tax_amount = 0 on the invoice itself is CORRECT -- the recipient
  self-assesses and remits the tax separately. Do not describe an RCM invoice's zero tax_amount as
  an error or an extraction gap; if the question concerns tax liability on such an invoice, surface
  the self-assessed liability, don't just stay silent on it.
- Tax regimes are not interchangeable in meaning: US sales tax is an unrecoverable cost to the
  business; Indian GST is typically a recoverable input tax credit (an asset, not a pure cost); EU
  VAT has its own intra-community reverse-charge rules. "How much tax did we pay" means a different
  thing depending on the tenant's jurisdiction -- answer according to that tenant's regime, don't
  assume US sales-tax conventions apply everywhere.

CATEGORY AND ENTITY JUDGMENT
- A vendor's own name is legitimate evidence for a spend category (a vendor named "Om Packaging" is
  real evidence for a "packaging expenses" question), same as a matching tag or line-item description.
  Do not treat a name match as weaker evidence than a tag match.
- If a name match is ambiguous between what could be two distinct vendors, you were not given enough
  information to guess -- that case has already been routed to a clarifying question before you see it.

DATA HONESTY
- If a fetched record's structured field and a document chunk's raw text disagree, say so -- the
  structured field is authoritative for the number, the chunk is corroboration/citation only, but a
  real conflict is worth surfacing, never silently resolved in favor of one side.
- If an audit or duplicate flag (sa_alerts) is present on a record relevant to the question, mention
  it -- do not answer around it.
- Never present a zero total as a confident answer. A zero means "no matching records under this
  filter" -- say that explicitly, don't hand back "$0.00" as if it were a real total.
- Never sum amounts across different currencies into one number. If a question spans more than one
  currency, report each currency separately unless the user has explicitly asked for and accepted a
  conversion at a stated rate.
- If a date range like "this quarter" or "this year" is ambiguous between calendar-year and a fiscal
  year, state which one you used.

You answer only from what your tools actually returned. If a tool didn't return it, you don't know
it -- say so rather than filling the gap from general knowledge or a prior turn's conversation text."""


# ---------------------------------------------------------------------------
# identify_invoices — task, schema, rules
# ---------------------------------------------------------------------------

IDENTIFY_TASK_BLOCK = """You are generating a narrow lookup query to find which invoice(s) a question concerns. You are NOT
computing totals, tax breakdowns, or any other detail here -- only finding the right row(s). A
separate tool fetches full detail once the invoice is identified."""

# The ONLY hand-maintained schema description left for the single-invoice case,
# and small on purpose -- these are the columns you need to FIND a row, not the
# columns you need to answer a question about it. Detail comes from
# `get_full_record`, which reflects the model instead of reading a list.
# The table name is stated first, and that is not decoration: found live
# 2026-08-21 on the first real-model run of this tool set, gpt-5-mini wrote
# `FROM invoices` (plural) on a plain invoice-number lookup and did so again on
# every repair attempt, so the whole turn ended in "no such table: invoices" --
# once as `status="error"`, once as a `declined` that turned into a clarifying
# question telling the user to "ask your admin to restore the invoices table".
# Nothing in this block had ever named the table: `aggregate_schema_block()` says
# "the full `invoice` table" and the default path's prompt says "Given the
# 'invoice' table schema", but this block said only "Schema", so the model had to
# guess the one identifier every generated query depends on.
IDENTIFY_SCHEMA_BLOCK = """Schema -- one table, named `invoice` (singular, no plural form exists). Every query you write
selects FROM invoice. Only these columns are visible to you:
- id: UUID
- tenant_id: UUID
- vendor_name: VARCHAR (INBOUND only)
- customer_name: VARCHAR (OUTBOUND only)
- invoice_number: VARCHAR
- invoice_date: DATE
- flow_direction: VARCHAR ('INBOUND' = a vendor's invoice sent to this tenant; 'OUTBOUND' = this
  tenant's own invoice sent to a customer)
- grand_total, currency: for disambiguating between several same-named matches only"""

# Rules 1-6 as drafted in Feature 21's design. Rules 1/2 are rules 1/4/4a
# of the SQL route restated for this narrower job; 5 is rule 9; 6 is rule 10.
IDENTIFY_RULES_BLOCK = """Rules:
1. Always filter by tenant_id = '{tenant_id}'.
2. A question about a vendor/bill received means flow_direction='INBOUND', filtered by vendor_name.
   A question about a customer/invoice sent means flow_direction='OUTBOUND', filtered by
   customer_name. Never mix the two for the wrong direction. If the entity could plausibly be
   either, check both sides rather than guessing one.
3. Normalize vendor/customer names before matching: case-fold, trim whitespace, strip common legal
   suffixes (Pvt Ltd, Ltd, LLC, Inc, Corp) before comparing.
4. If normalized matching surfaces more than one distinct-looking candidate for the same name
   (different ids, nothing in the question disambiguates them), do NOT guess which one the user
   means -- return every candidate and let the caller invoke ask_clarifying_question.
5. Follow-up questions that narrow a previous answer: reuse the previous turn's WHERE clause
   verbatim, only ADD the new restriction.
6. Comparison questions naming two or more specific entities: return a row for every named entity,
   never ORDER BY ... LIMIT 1."""

# Not part of the drafted rules 1-6, and deliberately kept separate from them so
# the drafted text stays reviewable against the doc: `identify_invoices` has to
# hand `get_full_record` an id, so the SELECT list matters here in a way it does
# not for the aggregate path. The tool recovers ids by companion query when this
# is ignored (see `identify_invoices`), so this is an optimisation, not a
# correctness dependency.
IDENTIFY_OUTPUT_BLOCK = """Output shape: SELECT id first, then vendor_name/customer_name, invoice_number, invoice_date,
grand_total and currency. The id is what the detail-fetch step is called with; the rest is only
there so a human can tell two same-named candidates apart."""


def build_identify_system_prompt(
    tenant_id: str,
    *,
    chat_history: str = "",
    prior_sql_block: str = "",
    injection_guard: str = "",
) -> str:
    """Assemble `identify_invoices`' system prompt from the blocks above.

    Every caller-supplied section defaults to empty, the same way
    `build_sql_system_prompt()` does, so a standalone call with no conversation
    behind it renders the same prompt minus those sections.
    """
    return f"""{IDENTIFY_TASK_BLOCK}

{IDENTIFY_SCHEMA_BLOCK}

{IDENTIFY_RULES_BLOCK.replace("{tenant_id}", str(tenant_id))}

{IDENTIFY_OUTPUT_BLOCK}

{injection_guard}{prior_sql_block}
Conversation History for Context:
{chat_history}
"""


# ---------------------------------------------------------------------------
# Schema reflection — the mechanism, not a convenience
# ---------------------------------------------------------------------------

# The one deliberate exclusion from rule 4's category match, decided 2026-08-21:
# a street/branch address is identity/routing content, not economic content, and
# is the column most likely to produce a false-positive category match (a
# "packaging" street name matching a packaging-spend query).
CATEGORY_MATCH_ADDRESS_EXCLUSION = "addresses"

# Deviation from Feature 21's rule 4 as drafted -- its literal "every JSONB/text
# column in the schema EXCEPT `addresses`", flagged rather than applied silently.
# Read literally, "every text/JSONB column" also sweeps in five columns that are
# not category evidence at all, and one of them actively defeats the `addresses`
# decision above:
#   * file_path / batch_id / file_hash -- internal storage plumbing. `file_path`
#     is already denied at render time by `execute_generated_sql`'s
#     `_INTERNAL_ONLY_COLUMNS`, because it leaked a blob URI into chat once.
#   * coordinates -- OCR bounding-box geometry.
#   * source_document_json -- the raw Document Intelligence payload. It embeds
#     every address on the invoice verbatim, so including it would silently undo
#     the one exclusion the design deliberately made, and it is large enough to
#     make a LIKE over it the most expensive predicate in the query.
#   * field_confidence -- a map keyed by THIS SCHEMA'S OWN COLUMN NAMES
#     ("tax_amount", "items", "vendor_name", ...). Every row contains those
#     words, so a category query for "tax", "items" or "reference" would match
#     100% of invoices through this column alone. That is not a weak signal, it
#     is a broken one.
# Everything else the model carries stays in scope, including `status`,
# `currency`, `flow_direction` and `submitted_by_email` -- this is a small named
# exclusion list, reviewed here, not a tiered-evidence system.
CATEGORY_MATCH_EXCLUDED_COLUMNS = (
    CATEGORY_MATCH_ADDRESS_EXCLUSION,
    "file_path",
    "batch_id",
    "file_hash",
    "coordinates",
    "source_document_json",
    "field_confidence",
)

# Reflected type -> the name a SQL-writing model recognises.
_SQL_TYPE_NAMES = {
    "Uuid": "UUID",
    "GUID": "UUID",
    "Float": "FLOAT",
    "Integer": "INTEGER",
    "Date": "DATE",
    "DateTime": "DATETIME",
    "Boolean": "BOOLEAN",
    "JSON": "JSONB",
    "AutoString": "VARCHAR",
    "String": "VARCHAR",
    "Text": "TEXT",
}

# Reflection proves a column EXISTS; it cannot say what the value means. These
# notes are the handful of meanings this product learned the hard way and must
# not lose when the hand-typed schema block goes away -- each one is an incident,
# not a decoration. Any column without a note is rendered from reflection alone.
_COLUMN_NOTES = {
    "vendor_name": "the vendor who sent this tenant an INBOUND invoice; NULL for OUTBOUND rows",
    "customer_name": "the customer this tenant sent an OUTBOUND invoice to; NULL for INBOUND rows",
    "flow_direction": (
        "'INBOUND' = a vendor's invoice sent to this tenant; 'OUTBOUND' = this tenant's own "
        "invoice sent to a customer"
    ),
    "currency": "ISO 4217 code of this invoice's amounts, e.g. 'USD', 'INR', 'EUR'",
    "status": (
        "for an INBOUND row this is the OCR/extraction pipeline's own processing state and NOT a "
        "payment signal -- 'AUDIT_REQUIRED' means the pipeline flagged a math/data issue, "
        "'COMPLETED' means extraction finished cleanly. Never read either as paid/unpaid. Only "
        "OUTBOUND's literal 'PAID' value is a real payment signal"
    ),
    "tax_amount": "ONE combined tax total per invoice; the per-component breakdown lives in `taxes`",
    "taxes": "itemized tax breakdown, e.g. CGST/SGST/IGST rows each with rate and amount",
    "tax_ids": "tax registration identifiers (GSTIN, VAT number, EIN/TIN)",
    "compliance_metadata": "IRN, e-Way Bill number, QR code, Peppol ID and similar identifiers",
    "sa_alerts": "audit/duplicate alerts raised by the extraction pipeline",
    "items": "list of line-item objects, each having: description, quantity, unit_price, amount",
    "tags": "list of tags as strings, e.g. [\"urgent\", \"software\"]",
    "references": "PO / SO / delivery-note references",
    "deleted_at": "soft delete: NULL means live",
}


def _is_text_column(column) -> bool:
    """True for VARCHAR/TEXT, including SQLModel's `AutoString` TypeDecorator."""
    if isinstance(column.type, (sa.String, sa.Text)):
        return True
    impl = getattr(column.type, "impl", None)
    if isinstance(impl, type):
        return issubclass(impl, (sa.String, sa.Text))
    return isinstance(impl, (sa.String, sa.Text))


def _is_json_column(column) -> bool:
    return isinstance(column.type, sa.JSON)


def _sql_type_name(column) -> str:
    return _SQL_TYPE_NAMES.get(type(column.type).__name__, type(column.type).__name__.upper())


def invoice_columns() -> list:
    """Every column on the live `Invoice` model, in declaration order."""
    return list(Invoice.__table__.columns)


def _category_match_columns_typed() -> list[tuple[sa.Column, bool]]:
    """`(column, needs_text_cast)` for every category-matchable column.

    The single place the three renderers below agree on two separate questions:
    which columns are in scope at all, and which of them have to be cast to text
    before `LOWER`/`LIKE` touches them (rule 6(a) -- there is no `lower(jsonb)`,
    and an uncast call aborts the whole query on Postgres). Split out for Gap 306:
    the executable form added below must not be allowed to disagree with the
    rendered one about either answer, and two hand-kept copies of the same
    `if _is_json_column(...)` branch is exactly how that disagreement starts.
    """
    typed: list[tuple[sa.Column, bool]] = []
    for column in invoice_columns():
        if column.name in CATEGORY_MATCH_EXCLUDED_COLUMNS:
            continue
        if _is_json_column(column):
            typed.append((column, True))
        elif _is_text_column(column):
            typed.append((column, False))
    return typed


def category_match_columns() -> list[str]:
    """The columns rule 4's OR-group scans, reflected off the live model.

    This replaces rule 6b's hardcoded four (`tags`, `items`, `vendor_name`,
    `customer_name`). A packaging expense referenced only in a PO note lives in
    `references` and was invisible to the old list; it is visible to this one,
    and so is any text/JSONB column added to the model after this was written.
    """
    return [column.name for column, _ in _category_match_columns_typed()]


def category_match_json_columns() -> list[str]:
    """The subset of `category_match_columns()` that is JSONB, reflected.

    Gap 306's trigger condition, and the reason it is derived rather than the
    literal `("tags", "items", "sa_alerts")` it would have been easiest to type:
    a `LIKE` against a JSON blob column is, by construction, a subject-matter
    search. Nothing else on this route has a reason to reach into one -- a name
    lookup uses `vendor_name`/`customer_name` (rules 6a/4a), an invoice lookup
    uses `invoice_number`, a status filter uses `status`. So "did this query
    LIKE-match a phrase against a JSONB column" is a structural fingerprint of a
    rule 6b category query, holds for every subset of the group the model might
    emit, and stays correct when a JSONB column is added to `models.py`.
    """
    return [column.name for column, needs_cast in _category_match_columns_typed() if needs_cast]


def render_category_match_clause(phrase: str) -> str:
    """One parenthesised OR-group of `LIKE` matches over every category column.

    JSONB columns are cast to text before LOWER/LIKE (rule 6(a): there is no
    `lower(jsonb)` and an uncast call aborts the whole query); plain VARCHAR
    columns are not cast. Reserved names are quoted -- see `quoted_column`.

    `phrase` is interpolated as a SQL literal, so callers must pass a sanitized
    phrase. Nothing here escapes it -- which is why the *executed* form of this
    clause is `category_match_branches()` below, not this one. This renderer is
    for prompt/diagnostic text.
    """
    branches = []
    for column, needs_cast in _category_match_columns_typed():
        name = quoted_column(column.name)
        if needs_cast:
            branches.append(f"LOWER(CAST({name} AS TEXT)) LIKE LOWER('%{phrase}%')")
        else:
            branches.append(f"LOWER({name}) LIKE LOWER('%{phrase}%')")
    return "(" + "\n    OR ".join(branches) + ")"


def category_match_branches(phrase: str) -> list[tuple[str, sa.sql.ColumnElement]]:
    """The same OR-group as `render_category_match_clause()`, as bound SQL expressions.

    `(column_name, predicate)` per in-scope column, so a caller can build both the
    match itself (`category_match_expression()`) and a "which column did this row
    actually match in" projection from one reflection pass.

    Three things this form has that the rendered string cannot (Gap 306, which is
    what made it necessary):

      * **The phrase is a bound parameter**, never interpolated. The phrase this
        product searches on is lifted out of model-written SQL, so "the caller
        sanitizes it" is not a guarantee anyone should be relying on.
      * **The cast is the dialect's own.** `sa.cast(col, sa.Text)` compiles to
        `CAST(... AS TEXT)` on Postgres and on SQLite; nothing here has to know
        which engine the request is bound to.
      * **It is composable with a typed tenant predicate.** `Invoice.tenant_id ==
        <UUID>` goes through SQLModel's UUID type, which is the only form that
        matches on *both* engines -- SQLite stores those columns dashless, so the
        dashed literal a text clause would carry matches zero rows there.

    `phrase` is lowered in Python rather than wrapped in a second SQL `LOWER()`:
    the column side is already lowered, and lowering a bound literal in SQL buys
    nothing but an extra function call per row.
    """
    pattern = f"%{phrase.lower()}%"
    branches: list[tuple[str, sa.sql.ColumnElement]] = []
    for column, needs_cast in _category_match_columns_typed():
        target = sa.cast(column, sa.Text) if needs_cast else column
        branches.append((column.name, sa.func.lower(target).like(pattern)))
    return branches


def category_match_expression(phrase: str) -> sa.sql.ColumnElement:
    """`category_match_branches()` OR'd together -- the whole clause, ready to filter on."""
    return sa.or_(*(predicate for _, predicate in category_match_branches(phrase)))


def aggregate_schema_block() -> str:
    """The full `Invoice` model, reflected at call time -- every column, no subset.

    This is the block that replaces the hand-typed ~19-column list every
    schema-drift incident traced back to. `_COLUMN_NOTES` adds meaning for the
    handful of columns whose meaning was learned from a live failure; existence
    always comes from reflection.
    """
    lines = ["Schema: the full `invoice` table, reflected from the live model at call time --"]
    for column in invoice_columns():
        note = _COLUMN_NOTES.get(column.name)
        rendered = f"- {column.name}: {_sql_type_name(column)}"
        if note:
            rendered += f" ({note})"
        lines.append(rendered)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# aggregate — task and rules
# ---------------------------------------------------------------------------

AGGREGATE_TASK_BLOCK = """You are generating a cross-invoice aggregation query -- the question needs a total, count, or
breakdown across more than one invoice, not a single identified invoice's detail (that is
identify_invoices + get_full_record's job)."""

# Rules 1-10 from Feature 21's design. Two placeholders are filled at
# call time rather than typed: `{category_columns}` from `category_match_columns()`
# and `{line_item_rule}` from `agents/query_agent._line_item_rule()`, which is
# already split by dialect (`_LINE_ITEM_RULE_SQLITE`/`_LINE_ITEM_RULE_POSTGRES`).
# Rule 5 therefore cannot drift from the 6d rule the default path uses -- it IS
# that rule, not a second copy of it.
AGGREGATE_RULES_BLOCK = """Rules:
1. Always filter by tenant_id = '{tenant_id}'.
2. DIRECTION: same rule as identify_invoices -- a vendor/bill received is flow_direction='INBOUND'
   filtered on vendor_name, a customer/invoice sent is flow_direction='OUTBOUND' filtered on
   customer_name. For a combined/net question spanning both directions ("how much do we owe vs.
   are owed"), use ONE query with conditional aggregation
   (SUM(CASE WHEN flow_direction='INBOUND' THEN grand_total ELSE 0 END), same for OUTBOUND) rather
   than two separate queries.
3. CURRENCY: never blend currencies into one SUM. GROUP BY currency, and select currency alongside
   the total. If the question implies one number is wanted across mixed currencies, do not silently
   pick one -- the caller checks this and will raise a clarifying question.
4. CATEGORY MATCH -- RELEVANCE ONLY, NOT LINE-ITEM VALUE: when the question refers to a tag,
   line-item description, or general category word, and only needs to know WHETHER an invoice
   relates to that category (not the specific line item's own amount/quantity), OR together a
   LOWER(CAST(col AS TEXT)) LIKE match across every one of these columns, in ONE parenthesised OR
   group, never a subset:
{category_columns}
   `addresses` is deliberately NOT in that list -- a street/branch address is identity/routing
   content, not economic content. Cast JSONB columns to text before LOWER/LIKE; plain VARCHAR
   columns must NOT be cast; a reserved column name such as "references" must be double-quoted.
   This whole-blob match on `items` is an existence check only -- it tells you the invoice relates
   to the category, nothing more. Worked shape:
{category_clause_example}
5. LINE ITEMS -- VALUE, NOT JUST RELEVANCE: whenever the question needs a specific line item's own
   amount, quantity, or description (not just whether the invoice relates to a category), do NOT
   use rule 4's whole-blob `items` match for this -- unnest items per the line-item rule below and
   select the line's own fields. Rule 4's `items` check and this rule apply to the same column for
   two different jobs: rule 4 answers "does this invoice relate to X", this rule answers "what is
   X's own amount on this invoice" -- never use one to answer the other's question.
6. STATUS INCLUSION: which `status` values count toward "spend" is not defined for this product,
   and soft-deleted rows (deleted_at IS NOT NULL) are not excluded anywhere today. Do not silently
   include or exclude rejected, duplicate, unextracted or soft-deleted rows as if the choice were
   settled -- if the answer would change materially depending on it, make the filter you used
   explicit so the caller can surface it.
7. ZERO RESULTS: a query returning zero rows or a zero total is never a confident answer. The
   caller detects both and routes them to a clarifying question or an explicit "no matching
   records" reply -- do not try to make a zero look like a total.
8. PROVENANCE: the caller recovers the invoice ids behind any total by re-running your WHERE clause
   as an id-only companion query, so do NOT add `id` to the SELECT list of an aggregate (raw UUIDs
   in a results table are noise for the user). Keep the WHERE clause reconstructible: no subqueries,
   and no joins other than the line-item unnest in rule 5.
9. FISCAL YEAR: if the date range in the question is ambiguous between calendar-year and a fiscal
   year, use the calendar year and say so -- there is no fiscal-year setting on the tenant.
10. Whenever monetary columns are selected, also select currency.

{line_item_rule}"""


def build_aggregate_system_prompt(
    tenant_id: str,
    line_item_rule: str,
    *,
    chat_history: str = "",
    prior_sql_block: str = "",
    injection_guard: str = "",
    rules_block: str = "",
    chat_rules_block: str = "",
    tenant_stats: str = "",
) -> str:
    """Assemble `aggregate`'s system prompt: task + reflected schema + rules 1-10.

    `line_item_rule` is passed in rather than imported so this module stays free
    of database concerns -- the caller resolves the dialect (that is
    `_line_item_rule()`'s job) and hands the rendered rule text over.
    """
    columns = "\n".join(f"     {name}" for name in category_match_columns())
    rules = (
        AGGREGATE_RULES_BLOCK.replace("{tenant_id}", str(tenant_id))
        .replace("{category_columns}", columns)
        .replace("{category_clause_example}", _indent(render_category_match_clause("packaging"), 3))
        .replace("{line_item_rule}", line_item_rule)
    )
    return f"""{AGGREGATE_TASK_BLOCK}

{aggregate_schema_block()}

{rules}

{tenant_stats}
{rules_block}{chat_rules_block}
{injection_guard}{prior_sql_block}
Conversation History for Context:
{chat_history}
"""


def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line for line in text.splitlines())
