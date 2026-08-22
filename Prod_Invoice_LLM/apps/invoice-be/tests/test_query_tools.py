"""Feature 21 — per-tool unit tests for `agents/query_tools.py`.

Scope note, stated up front the same way `test_chat_sql_quality.py` does: the
tools that contain an LLM call (`identify_invoices`, `aggregate`,
`search_invoices`) are mocked at that boundary here, so these tests prove
*mechanics* — that the reflected schema really reaches the prompt, that the
tenant-isolation guard still fires, that the deterministic layers (normalized
name matching, the ambiguity clarification, the zero-total and mixed-currency
checks, rule 6c's phrase sanitizing) do what they claim regardless of what a
model returns. They cannot prove prompt behaviour against a real model; that is
Phase 3's live-verification job, and this repo has an explicit precedent (Gap
226, and Feature 21's own revert) for why the distinction matters.

`get_full_record`, `compute` and `ask_clarifying_question` are different: none of
them contains an LLM call at all, so their tests are exhaustive over the
behaviour that matters rather than indicative. That is the point of moving "fetch
the whole row", "add these numbers" and "ask, don't guess" out of prose and into
functions.

Question phrasings below are the real historical ones from this repo's own
tracker, not invented: rule 4a's Titan Steel Distributors / Redwood Facilities
Group cases (Gap 270), rule 6d's Rajesh Steel CGST case (Gaps 263/264), rule 10's
DataPipe Solutions vs. StratEdge Partners comparison (Gap 268), rule 6b's
freight/delivery per-vendor case (Gap 271), the 5000 x 0.08 = 420.00 false
equation (Gap 269), and the Om Packaging name-variant case from this feature's
own business-analyst review.
"""
import os
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

os.environ["MOCK_EMBEDDINGS"] = "true"

from dependencies import MOCK_TENANT_ID
from models import Invoice
from agents.query_agent import NO_RECORDS_FOUND
from agents.sage_prompts import (
    CATEGORY_MATCH_EXCLUDED_COLUMNS,
    aggregate_schema_block,
    category_match_columns,
    render_category_match_clause,
)
from agents.query_tools import (
    CLARIFICATION_REASONS,
    FULL_RECORD_EXCLUDED_COLUMNS,
    MAX_FULL_RECORD_CHUNK_CHARS,
    aggregate,
    ask_clarifying_question,
    bound_document_pages,
    compute,
    detect_ambiguous_date_range,
    get_full_record,
    identify_invoices,
    normalize_entity_name,
    search_invoices,
    _sanitize_like_phrase,
)

sqlite_url = "sqlite:///:memory:"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


def _seed_invoice(db_session, **kwargs):
    defaults = dict(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/inv.pdf",
        flow_direction="INBOUND",
        status="COMPLETED",
        currency="USD",
    )
    defaults.update(kwargs)
    inv = Invoice(**defaults)
    db_session.add(inv)
    db_session.commit()
    return inv


class _RecordingLLM:
    """Records every SQL-generation prompt and replays scripted structured
    results. `summary_prompts` stays empty for every test in this file -- no tool
    here makes a synthesis call (see
    test_no_tool_composes_prose_or_makes_a_summary_call)."""

    def __init__(self, sql_results):
        self._sql_results = list(sql_results)
        self.prompts = []
        self.summary_prompts = []

    def with_structured_output(self, schema):
        outer = self

        class _Structured:
            def invoke(self, prompt):
                outer.prompts.append(prompt)
                if not outer._sql_results:
                    raise AssertionError("SQL generation called more times than scripted")
                return outer._sql_results.pop(0)

        return _Structured()

    def invoke(self, prompt):
        self.summary_prompts.append(prompt)
        return MagicMock(content="unused")


def _sql(select_list="id, vendor_name, invoice_number, invoice_date, grand_total, currency",
         where_extra="", tenant=None):
    tenant = tenant or str(MOCK_TENANT_ID)
    return f"SELECT {select_list} FROM invoice WHERE tenant_id = '{tenant}'{where_extra}"


def _identify(db_session, llm, question, **kwargs):
    return identify_invoices(question, MOCK_TENANT_ID.hex, db_session, llm=llm, **kwargs)


# ── the reflected schema: the actual fix, asserted directly ─────────────────


def test_every_business_column_the_old_prompt_missed_is_in_the_reflected_schema():
    """The whole feature in one assertion. The hand-typed ~19-column schema block
    the SQL route uses names none of these, which is why a tax-breakdown or
    compliance-identifier question could not be answered however it was phrased.
    Reflection means the list cannot fall behind the model again."""
    block = aggregate_schema_block()
    for column in (
        "taxes", "tax_ids", "compliance_metadata", "payment_instructions",
        "references", "discounts", "deductions", "addresses", "subtotal",
        "discount_percent", "discount_amount", "deleted_at", "paid_at", "sent_at",
    ):
        assert f"- {column}:" in block, f"{column} missing from the reflected schema"


def test_the_reflected_schema_keeps_the_incident_learned_meanings():
    """Reflection proves a column exists; it cannot say what the value means. The
    handful of meanings this product learned from live failures -- above all that
    an INBOUND `status` is not a payment signal (found live twice, both
    directions) -- must survive the switch away from the hand-typed block."""
    block = aggregate_schema_block()
    assert "Never read either as paid/unpaid" in block
    assert "ONE combined tax total per invoice" in block
    assert "CGST/SGST/IGST" in block


def test_category_match_scans_far_more_than_rule_6bs_original_four():
    columns = category_match_columns()
    for original in ("tags", "items", "vendor_name", "customer_name"):
        assert original in columns
    # The ones a packaging expense referenced only in a PO note needed.
    for added in ("references", "payment_instructions", "compliance_metadata",
                  "discounts", "deductions", "taxes", "tax_ids", "sa_alerts"):
        assert added in columns


def test_addresses_is_the_deliberate_exclusion_and_so_is_every_non_business_blob():
    """`addresses` is the design's one deliberate exclusion (identity/routing, not
    economic content). The rest are this implementation's flagged deviation from
    'every text/JSONB column', each for a concrete reason -- `field_confidence`
    is keyed by the schema's own column names, so leaving it in would match 100%
    of invoices for a query about 'tax' or 'items'."""
    columns = category_match_columns()
    assert "addresses" not in columns
    for excluded in CATEGORY_MATCH_EXCLUDED_COLUMNS:
        assert excluded not in columns


def test_the_reserved_column_name_is_quoted_in_the_generated_clause():
    """`references` is a RESERVED word in both PostgreSQL and SQLite --
    `CAST(references AS TEXT)` is a syntax error, and the architecture doc's
    worked example writes it unquoted. Every clause this code renders quotes it."""
    clause = render_category_match_clause("packaging")
    assert 'CAST("references" AS TEXT)' in clause
    assert "CAST(references AS TEXT)" not in clause
    # JSONB cast on JSON columns, no cast on VARCHAR ones (rule 6(a)).
    assert "LOWER(CAST(items AS TEXT))" in clause
    assert "LOWER(vendor_name)" in clause
    assert "LOWER(CAST(vendor_name" not in clause


def test_the_generated_category_clause_actually_runs_on_this_engine(db_session):
    """A clause that reads correctly but does not parse is worth nothing. This
    executes the reflected OR-group against a real database."""
    from sqlalchemy import text

    clause = render_category_match_clause("packaging")
    rows = db_session.execute(
        text(f"SELECT COUNT(*) FROM invoice WHERE {clause}")
    ).fetchall()
    assert rows[0][0] == 0


# ── identify_invoices ───────────────────────────────────────────────────────


def test_identify_prompt_is_narrow_and_carries_only_its_own_rules(db_session):
    """The identify prompt is deliberately NOT the SQL route's rules 1-11: it is
    the six lookup columns and rules 1-6. Carrying the full rule set here would
    recreate the drift this feature removes -- and carrying the tax-component or
    line-item rules would invite the tool to answer detail questions it is not
    for."""
    llm = _RecordingLLM([MagicMock(sql=_sql(tenant=MOCK_TENANT_ID.hex), explanation_or_error=None)])
    _identify(db_session, llm, "what did we pay Om Packaging in July")

    prompt = llm.prompts[0]
    assert "You are NOT" in prompt and "computing totals, tax breakdowns" in prompt
    # The table name is stated, and that is load-bearing: the first live run of
    # this tool (2026-08-21) had gpt-5-mini write `FROM invoices` on every
    # attempt, because this block named columns but never the table.
    assert "named `invoice` (singular" in prompt
    assert "Only these columns are visible to you:" in prompt
    assert "- vendor_name: VARCHAR (INBOUND only)" in prompt
    for absent in ("6d. LINE-ITEM LEVEL EXTRACTION", "6b. CATEGORY / SUBJECT-MATTER",
                   "- taxes:", "- items:", "- sa_alerts:"):
        assert absent not in prompt
    assert "Always filter by tenant_id = '" in prompt
    assert "never ORDER BY ... LIMIT 1" in prompt
    assert "<<<USER_QUESTION_START>>>" in prompt  # injection wrapping survives


def test_identify_returns_ids_and_the_six_identifying_columns(db_session):
    invoice = _seed_invoice(
        db_session, vendor_name="Titan Steel Distributors", invoice_number="TSD-620458",
        grand_total=18450.0,
    )
    llm = _RecordingLLM([MagicMock(sql=_sql(tenant=MOCK_TENANT_ID.hex), explanation_or_error=None)])
    result = _identify(db_session, llm, "the Titan Steel Distributors invoice")

    assert result.status == "ok"
    assert result.invoice_ids == [str(invoice.id)]
    candidate = result.candidates[0]
    assert candidate["vendor_name"] == "Titan Steel Distributors"
    assert candidate["invoice_number"] == "TSD-620458"
    assert candidate["flow_direction"] == "INBOUND"
    assert candidate["grand_total"] == 18450.0
    # Identity only: no tax, no line items, no status.
    assert set(candidate) == {
        "id", "vendor_name", "customer_name", "invoice_number", "invoice_date",
        "flow_direction", "grand_total", "currency",
    }


def test_identify_recovers_ids_even_when_the_model_did_not_select_them(db_session):
    """`get_full_record` needs a real id. Rather than depending on the model's
    SELECT list, ids are recovered by the same Gap 231 companion query the
    aggregate path uses."""
    invoice = _seed_invoice(db_session, vendor_name="Redwood Facilities Group")
    llm = _RecordingLLM([
        MagicMock(sql=_sql("vendor_name, invoice_date", tenant=MOCK_TENANT_ID.hex),
                  explanation_or_error=None)
    ])
    result = _identify(db_session, llm, "when is the Redwood Facilities Group invoice due")

    assert result.status == "ok"
    assert result.invoice_ids == [str(invoice.id)]


def test_identify_normalizes_a_name_the_generated_sql_missed(db_session):
    """The business-analyst review's own case: one real vendor captured as "OM
    PACKAGING", asked about as "Om Packaging Pvt Ltd". The generated LIKE finds
    nothing; the deterministic normalized retry (case-fold, strip legal suffixes)
    finds the row. This is in code, not prose, because a prompt rule to normalize
    fires only when the model remembers to."""
    invoice = _seed_invoice(db_session, vendor_name="OM PACKAGING", grand_total=4200.0)
    llm = _RecordingLLM([
        MagicMock(
            sql=_sql(
                tenant=MOCK_TENANT_ID.hex,
                where_extra=" AND LOWER(vendor_name) LIKE LOWER('%om packaging pvt ltd%')",
            ),
            explanation_or_error=None,
        )
    ])
    result = _identify(db_session, llm, "what did we pay Om Packaging Pvt Ltd")

    assert result.status == "ok"
    assert result.name_normalized_retry is True
    assert result.invoice_ids == [str(invoice.id)]
    # And it says so: the retry drops the original query's other restrictions.
    assert "dropped the query's other restrictions" in result.message


def test_identify_asks_when_one_name_resolves_to_two_distinct_vendors(db_session):
    """The 2026-08-21 decision, enforced structurally. Two stored names that
    normalize alike could be one vendor typed twice or two real legal entities;
    disambiguating via tax_ids/GSTIN was considered and rejected, because picking
    one silently risks answering the wrong entity's question with confidence. So
    the turn ends in a question."""
    _seed_invoice(db_session, vendor_name="Om Packaging", grand_total=1000.0)
    _seed_invoice(db_session, vendor_name="Om Packaging Pvt Ltd", grand_total=2000.0)
    llm = _RecordingLLM([
        MagicMock(
            sql=_sql(
                tenant=MOCK_TENANT_ID.hex,
                where_extra=" AND LOWER(vendor_name) LIKE LOWER('%om packaging%')",
            ),
            explanation_or_error=None,
        )
    ])
    result = _identify(db_session, llm, "what did we pay Om Packaging")

    assert result.status == "needs_clarification"
    assert result.ends_turn is True
    assert result.reason == "AMBIGUOUS_ENTITY"
    assert "Om Packaging" in result.question and "Om Packaging Pvt Ltd" in result.question


def test_identify_does_not_ask_on_a_two_entity_comparison(db_session):
    """Rule 10/Gap 268's shape must not be turned into a clarifying question: two
    named entities resolving to one vendor each is a comparison the user asked
    for, not an ambiguity. The check is per named phrase for exactly this
    reason."""
    _seed_invoice(db_session, vendor_name="DataPipe Solutions", grand_total=42300.0)
    _seed_invoice(db_session, vendor_name="StratEdge Partners", grand_total=27950.0)
    llm = _RecordingLLM([
        MagicMock(
            sql=_sql(
                tenant=MOCK_TENANT_ID.hex,
                where_extra=(
                    " AND (LOWER(vendor_name) LIKE LOWER('%datapipe solutions%')"
                    " OR LOWER(vendor_name) LIKE LOWER('%stratedge partners%'))"
                ),
            ),
            explanation_or_error=None,
        )
    ])
    result = _identify(
        db_session, llm,
        "between DataPipe Solutions and StratEdge Partners, whose invoice had the bigger total",
    )

    assert result.status == "ok"
    assert len(result.candidates) == 2


def test_identify_reports_no_results_distinctly_from_an_error(db_session):
    _seed_invoice(db_session, vendor_name="Cascade Manufacturing Co")
    llm = _RecordingLLM([
        MagicMock(
            sql=_sql(
                tenant=MOCK_TENANT_ID.hex,
                where_extra=" AND LOWER(vendor_name) LIKE LOWER('%nonexistent holdings%')",
            ),
            explanation_or_error=None,
        )
    ])
    result = _identify(db_session, llm, "what did we spend with Nonexistent Holdings")

    assert result.status == "no_results"
    assert "including after normalizing the name" in result.message


def test_identify_still_refuses_sql_without_a_tenant_predicate(db_session):
    """Rule 1 is enforced in code (`execute_generated_sql`'s safety check), not
    only in the prompt. Reached through this tool, a cross-tenant query must
    still be refused on every attempt and end as an error, never as results."""
    llm = _RecordingLLM([
        MagicMock(sql="SELECT id, vendor_name FROM invoice", explanation_or_error=None)
        for _ in range(3)
    ])
    result = _identify(db_session, llm, "show me every invoice in the system")

    assert result.status == "error"
    assert "tenant isolation" in (result.message or "")
    assert len(llm.prompts) == 3


def test_identify_surfaces_a_declined_question_as_its_own_status(db_session):
    llm = _RecordingLLM([
        MagicMock(sql=None, explanation_or_error="Nothing in this schema names an approver.")
    ])
    result = _identify(db_session, llm, "which invoices did Sandra approve")

    assert result.status == "declined"
    assert "approver" in result.message


def test_identify_calls_a_huge_match_an_aggregate_question(db_session):
    from agents.query_tools import MAX_IDENTIFY_CANDIDATES

    for index in range(MAX_IDENTIFY_CANDIDATES + 2):
        _seed_invoice(db_session, vendor_name=f"Vendor {index}", grand_total=10.0)
    llm = _RecordingLLM([MagicMock(sql=_sql(tenant=MOCK_TENANT_ID.hex), explanation_or_error=None)])
    result = _identify(db_session, llm, "our invoices")

    assert result.status == "too_many"
    assert "not a lookup" in result.message


def test_identify_emits_its_own_telemetry_event(db_session):
    """Feature 23 Phase 1: one event per LLM round-trip, named for the tool that
    made it -- not nested inside `chat.sql_generation`, which would emit two
    events for one call and report zero tokens on the outer one."""
    llm = _RecordingLLM([MagicMock(sql=_sql(tenant=MOCK_TENANT_ID.hex), explanation_or_error=None)])
    with patch("telemetry.track_agent_call") as tracked:
        _identify(db_session, llm, "the Titan Steel invoice")

    assert [call.args[0] for call in tracked.call_args_list] == ["sage.identify"]


# ── get_full_record ─────────────────────────────────────────────────────────


def test_full_record_returns_every_business_field_including_the_tax_breakdown(db_session):
    """Gaps 263/264/285 in one test. Nothing curates this row, so the itemized
    `taxes` breakdown, the GSTIN in `tax_ids` and the IRN in
    `compliance_metadata` are all present without any prompt having mentioned
    them."""
    invoice = _seed_invoice(
        db_session,
        vendor_name="Rajesh Steel",
        currency="INR",
        grand_total=118000.0,
        tax_amount=18000.0,
        taxes=[
            {"type": "CGST", "rate": 9, "amount": 9000.0},
            {"type": "SGST", "rate": 9, "amount": 9000.0},
        ],
        tax_ids=[{"type": "GSTIN", "value": "29ABCDE1234F1Z5"}],
        compliance_metadata=[{"type": "IRN", "value": "abc123"}],
        payment_instructions=[{"bank": "HDFC", "account": "0001"}],
        references=[{"type": "PO", "value": "PO-88"}],
    )
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=[]):
        result = get_full_record(str(invoice.id), str(MOCK_TENANT_ID), db_session)

    assert result.status == "ok"
    record = result.record
    assert record["taxes"] == [
        {"type": "CGST", "rate": 9, "amount": 9000.0},
        {"type": "SGST", "rate": 9, "amount": 9000.0},
    ]
    assert record["tax_ids"][0]["value"] == "29ABCDE1234F1Z5"
    assert record["compliance_metadata"][0]["value"] == "abc123"
    assert record["payment_instructions"] and record["references"]
    # And the rest of the row, uncurated.
    for column in ("subtotal", "discount_amount", "deductions", "addresses", "due_date",
                   "status", "flow_direction", "deleted_at"):
        assert column in record


def test_full_record_omits_only_storage_plumbing_and_says_which(db_session):
    """A five-column deviation from the doc's "every column, no curation", made
    visible on every result rather than hidden: none of them is business data,
    and `file_path` is a blob URI that leaked into a chat answer once."""
    invoice = _seed_invoice(db_session, vendor_name="Harbor Tech")
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=[]):
        result = get_full_record(str(invoice.id), str(MOCK_TENANT_ID), db_session)

    for omitted in FULL_RECORD_EXCLUDED_COLUMNS:
        assert omitted not in result.record
    assert result.columns_omitted == list(FULL_RECORD_EXCLUDED_COLUMNS)
    assert "file_path" in result.columns_omitted


def test_full_record_is_json_serializable(db_session):
    """The record goes into a prompt and into a `ToolMessage`; a raw UUID or date
    in it is a crash at the JSON boundary, not a formatting nit."""
    import json
    from datetime import date

    invoice = _seed_invoice(db_session, vendor_name="Harbor Tech", invoice_date=date(2026, 7, 2))
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=[]):
        result = get_full_record(str(invoice.id), str(MOCK_TENANT_ID), db_session)

    payload = json.dumps(result.to_dict())
    assert "2026-07-02" in payload
    assert str(invoice.id) in payload


def test_full_record_pulls_every_page_by_metadata_filter_not_by_search(db_session):
    """Once the invoice is identified, "the page with the tax table didn't rank
    high enough" is silent data loss, not a relevance decision -- so this is a
    direct `invoice_id` filter and every page comes back."""
    invoice = _seed_invoice(db_session, vendor_name="Harbor Tech")
    pages = [
        {"id": f"{invoice.id}_page_{n}", "document": f"page {n} text",
         "metadata": {"invoice_id": str(invoice.id), "page": n, "vendor_name": "Harbor Tech"},
         "matched_by": "invoice_id"}
        for n in (1, 2, 3)
    ]
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=pages) as fetch:
        result = get_full_record(str(invoice.id), str(MOCK_TENANT_ID), db_session)

    fetch.assert_called_once_with(str(invoice.id), str(MOCK_TENANT_ID))
    assert [chunk["page"] for chunk in result.chunks] == [1, 2, 3]
    assert all(chunk["matched_by"] == "invoice_id" for chunk in result.chunks)


def _long_pages(invoice_id, count: int, chars: int = 3_200) -> list[dict]:
    """`count` page chunks of roughly real size (a rendered A4 invoice page of
    line items measured ~3,200 characters, live run 2026-08-21)."""
    return [
        {
            "id": f"{invoice_id}_page_{n}",
            "document": f"[Page {n}]\n" + f"line {n} " * (chars // 8),
            "metadata": {"invoice_id": str(invoice_id), "page": n, "vendor_name": "Meridian"},
            "matched_by": "invoice_id",
        }
        for n in range(1, count + 1)
    ]


def test_a_short_document_is_never_touched_by_the_page_cap(db_session):
    """The cap exists for pathological documents. An ordinary invoice must come
    back whole, with `pages_omitted` empty -- otherwise every answer would carry
    a truncation disclaimer that is not true."""
    invoice = _seed_invoice(db_session, vendor_name="Harbor Tech")
    pages = _long_pages(invoice.id, 3)
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=pages):
        result = get_full_record(str(invoice.id), str(MOCK_TENANT_ID), db_session)

    assert [chunk["page"] for chunk in result.chunks] == [1, 2, 3]
    assert result.pages_omitted == []
    assert result.total_document_pages == 3


def test_a_long_document_is_capped_keeping_the_first_and_last_page(db_session):
    """Measured 2026-08-21: an 11-page invoice's page dump is 16,010 tokens and
    grows linearly, so past `MAX_FULL_RECORD_CHUNK_CHARS` pages are held back.
    The LAST page is kept on purpose -- totals, payment terms and the signature
    block live there, so a plain "first N pages" cap would drop the page most
    detail questions actually need."""
    invoice = _seed_invoice(db_session, vendor_name="Meridian Industrial Supply")
    pages = _long_pages(invoice.id, 11)
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=pages):
        result = get_full_record(str(invoice.id), str(MOCK_TENANT_ID), db_session)

    shown = [chunk["page"] for chunk in result.chunks]
    assert shown == sorted(shown)
    assert shown[0] == 1 and shown[-1] == 11
    assert result.total_document_pages == 11
    assert result.pages_omitted, "an 11-page document of this size must hit the cap"
    assert set(shown) & set(result.pages_omitted) == set()
    assert len(shown) + len(result.pages_omitted) == 11
    total_chars = sum(len(chunk["document"]) for chunk in result.chunks)
    assert total_chars <= MAX_FULL_RECORD_CHUNK_CHARS


def test_the_page_cap_never_empties_a_two_page_document(db_session):
    """Both anchor pages survive even when they alone exceed the budget: an empty
    document block is a worse answer than a long one."""
    invoice = _seed_invoice(db_session, vendor_name="Meridian Industrial Supply")
    pages = _long_pages(invoice.id, 2, chars=MAX_FULL_RECORD_CHUNK_CHARS)
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=pages):
        result = get_full_record(str(invoice.id), str(MOCK_TENANT_ID), db_session)

    assert [chunk["page"] for chunk in result.chunks] == [1, 2]
    assert result.pages_omitted == []


def test_bound_document_pages_orders_by_page_and_tolerates_an_unlabelled_page():
    """Chunks arrive from Chroma in whatever order `collection.get()` returns
    them; page order is imposed here, and a chunk with no page number sorts last
    rather than crashing the comparison."""
    pages = [
        {"page": 3, "document": "c"},
        {"page": None, "document": "d"},
        {"page": 1, "document": "a"},
    ]
    kept, omitted = bound_document_pages(pages)
    assert [chunk["document"] for chunk in kept] == ["a", "c", "d"]
    assert omitted == []


def test_full_record_surfaces_an_audit_flag_as_its_own_signal(db_session):
    """An answer about an amount on a duplicate-flagged invoice should say so
    rather than treating the figure as clean, so the flag is a field on the
    result and not something a reader has to notice inside the record."""
    invoice = _seed_invoice(
        db_session, vendor_name="Harbor Tech", status="AUDIT_REQUIRED",
        sa_alerts=[{"type": "DUPLICATE", "detail": "matches US-20260722-001"}],
    )
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=[]):
        result = get_full_record(str(invoice.id), str(MOCK_TENANT_ID), db_session)

    assert result.has_alerts is True
    assert result.record["sa_alerts"][0]["type"] == "DUPLICATE"


def test_full_record_refuses_another_tenants_invoice_as_not_found(db_session):
    """Not as a distinct error: a caller must not be able to learn that an id
    exists under another tenant."""
    other = _seed_invoice(db_session, tenant_id=uuid4(), vendor_name="Someone Else")
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=[]):
        result = get_full_record(str(other.id), str(MOCK_TENANT_ID), db_session)

    assert result.status == "not_found"
    assert result.record == {}
    assert "Someone Else" not in (result.message or "")


def test_full_record_rejects_a_malformed_id_without_touching_the_database(db_session):
    result = get_full_record("not-a-uuid", str(MOCK_TENANT_ID), db_session)
    assert result.status == "error"
    assert "not a valid invoice id" in result.message


def test_full_record_survives_an_unreachable_document_index(db_session):
    """A Chroma outage degrades the answer to "structured record only"; it does
    not take the turn down."""
    invoice = _seed_invoice(db_session, vendor_name="Harbor Tech")
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=[]):
        result = get_full_record(str(invoice.id), str(MOCK_TENANT_ID), db_session)

    assert result.status == "ok"
    assert result.chunks == []


# ── search_invoices ─────────────────────────────────────────────────────────


_CHUNK = {
    "id": "chunk-1",
    "document": "Titan Steel Distributors -- Invoice TSD-620458 -- steel bolts, 5000 units",
    "metadata": {"invoice_id": "11111111-1111-1111-1111-111111111111",
                 "vendor_name": "Titan Steel Distributors", "page": 1},
    "distance": 0.38,
    "keyword_score": 1,
    "matched_by": "vector",
}


def test_search_flattens_chroma_chunks_into_a_tool_shape():
    with patch("agents.query_tools.query_invoice_chunks", return_value=[_CHUNK]) as mocked:
        result = search_invoices("do we have any steel or materials related invoices", "tenant-1")

    mocked.assert_called_once_with(
        "tenant-1", "do we have any steel or materials related invoices", limit=5
    )
    assert result.status == "ok"
    chunk = result.chunks[0]
    assert chunk["invoice_id"] == "11111111-1111-1111-1111-111111111111"
    assert chunk["page"] == 1
    # Gap 244's channel signal is passed through -- a keyword-only match is
    # weaker evidence than a semantic one, and the caller can see which it got.
    assert chunk["matched_by"] == "vector"


def test_search_runs_the_structured_half_over_the_reflected_columns(db_session):
    """The half that is new: rule 6b's category match, built in code from the
    reflected column list rather than written as SQL by the model. A vendor
    identifiable only by a PO reference is found here and was not before."""
    invoice = _seed_invoice(
        db_session, vendor_name="Generic Trading", references=[{"type": "PO", "value": "packaging supplies Q3"}],
    )
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = MagicMock(
        phrases=["packaging"]
    )
    with patch("agents.query_tools.query_invoice_chunks", return_value=[]):
        result = search_invoices(
            "which invoices relate to packaging", MOCK_TENANT_ID.hex, db_session, llm=llm
        )

    assert result.status == "ok"
    assert result.phrases == ["packaging"]
    assert result.invoice_ids == [str(invoice.id)]
    assert "Generic Trading" in result.results_markdown


def test_search_reports_nothing_matching_as_no_results(db_session):
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = MagicMock(phrases=["quantum widgets"])
    with patch("agents.query_tools.query_invoice_chunks", return_value=[]):
        result = search_invoices(
            "anything about quantum widgets", MOCK_TENANT_ID.hex, db_session, llm=llm
        )

    assert result.status == "no_results"
    assert "not that the tenant has no invoices" in result.message


def test_search_degrades_to_semantic_only_without_a_session_or_llm():
    with patch("agents.query_tools.query_invoice_chunks", return_value=[_CHUNK]):
        result = search_invoices("steel invoices", "tenant-1")
    assert result.status == "ok"
    assert result.phrases == []
    assert result.results_markdown is None


def test_search_reports_a_retrieval_failure_as_an_error():
    with patch("agents.query_tools.query_invoice_chunks", side_effect=RuntimeError("chroma unreachable")):
        result = search_invoices("steel invoices", "tenant-1")

    assert result.status == "error"
    assert "chroma unreachable" in result.message
    assert result.chunks == []


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Rule 6c, as code: generic spend words stripped, phrase kept whole.
        ("freight costs", "freight"),
        ("office supplies", "office supplies"),
        ("cloud related spend", "cloud"),
        ("Printing Expenses", "printing"),
        # SQL-dangerous input never reaches a literal. ("invoice" also goes, as a
        # generic spend word; "drop" as a mutating keyword; the quote, semicolon
        # and comment marker as characters that are simply not in the allowlist.)
        ("packaging'; DROP TABLE invoice --", "packaging table"),
        ("100% legit", "100 legit"),
    ],
)
def test_search_phrase_sanitizing_enforces_rule_6c_and_sql_safety(raw, expected):
    assert _sanitize_like_phrase(raw) == expected


def test_search_emits_its_own_telemetry_event(db_session):
    llm = MagicMock()
    llm.with_structured_output.return_value.invoke.return_value = MagicMock(phrases=["packaging"])
    with patch("agents.query_tools.query_invoice_chunks", return_value=[]), \
         patch("telemetry.track_agent_call") as tracked:
        search_invoices("packaging spend", MOCK_TENANT_ID.hex, db_session, llm=llm)

    assert [call.args[0] for call in tracked.call_args_list] == ["sage.search"]


# ── aggregate ───────────────────────────────────────────────────────────────


def _aggregate(db_session, llm, question, **kwargs):
    kwargs.setdefault("include_tenant_context", False)
    return aggregate(question, MOCK_TENANT_ID.hex, db_session, llm=llm, **kwargs)


def test_aggregate_prompt_carries_the_reflected_schema_and_the_category_columns(db_session):
    llm = _RecordingLLM([
        MagicMock(sql=_sql("SUM(grand_total) AS total, currency", tenant=MOCK_TENANT_ID.hex)
                  + " GROUP BY currency", explanation_or_error=None)
    ])
    _aggregate(db_session, llm, "how much did we spend on packaging")

    prompt = llm.prompts[0]
    assert "reflected from the live model at call time" in prompt
    assert "- taxes: JSONB" in prompt and "- references: JSONB" in prompt
    assert 'CAST("references" AS TEXT)' in prompt          # the worked shape, correctly quoted
    assert "`addresses` is deliberately NOT in that list" in prompt
    # The rule 4 / rule 5 boundary, which is the Gap-287-shaped collision.
    assert "CATEGORY MATCH -- RELEVANCE ONLY, NOT LINE-ITEM VALUE" in prompt
    assert "LINE ITEMS -- VALUE, NOT JUST RELEVANCE" in prompt
    assert "never use one to answer the other's question" in prompt
    # And rule 5 IS the default path's 6d rule, not a second copy of it.
    assert "6d. LINE-ITEM LEVEL EXTRACTION & AGGREGATION" in prompt


def test_aggregate_returns_totals_with_provenance_ids(db_session):
    """Rule 8 / Gap 231: a GROUP BY/SUM query carries no row identity, so the ids
    behind the figure come from a companion query over the same WHERE clause --
    never from adding `id` to the aggregate's own SELECT list."""
    invoice = _seed_invoice(db_session, vendor_name="Blue Ridge Logistics", grand_total=6120.0)
    llm = _RecordingLLM([
        MagicMock(sql=_sql("SUM(grand_total) AS total_spend, currency", tenant=MOCK_TENANT_ID.hex)
                  + " GROUP BY currency", explanation_or_error=None)
    ])
    result = _aggregate(db_session, llm, "what did we spend in total")

    assert result.status == "ok"
    assert result.invoice_ids == [str(invoice.id)]
    assert "id" not in (result.results_markdown or "").split("\n")[0]
    assert result.currencies == ["USD"]


def test_aggregate_refuses_to_hand_back_a_zero_as_a_total(db_session):
    """"Never present a zero total as a confident answer" made structural: a zero
    comes back under its own status, so no caller has to notice it by reading the
    number."""
    _seed_invoice(db_session, vendor_name="Harbor Tech", grand_total=0.0)
    llm = _RecordingLLM([
        MagicMock(sql=_sql("SUM(grand_total) AS total_spend, currency", tenant=MOCK_TENANT_ID.hex)
                  + " GROUP BY currency", explanation_or_error=None)
    ])
    result = _aggregate(db_session, llm, "what did we spend on packaging this quarter")

    assert result.status == "zero_total"
    assert "A zero is not a total" in result.message


def test_aggregate_reports_no_rows_as_no_results_not_as_zero(db_session):
    _seed_invoice(db_session, vendor_name="Harbor Tech", grand_total=100.0)
    llm = _RecordingLLM([
        MagicMock(
            sql=_sql("SUM(grand_total) AS total, currency", tenant=MOCK_TENANT_ID.hex,
                     where_extra=" AND LOWER(vendor_name) LIKE LOWER('%nobody%')")
            + " GROUP BY currency",
            explanation_or_error=None,
        )
    ])
    result = _aggregate(db_session, llm, "what did we spend with Nobody Ltd")

    assert result.status == "no_results"
    assert "not a total of zero" in result.message


def test_aggregate_catches_a_silently_blended_multi_currency_total(db_session):
    """Verified against rule 5's own live example: its conditional aggregation
    sums `grand_total` across every currency present, unconditionally. A tenant
    holding both USD and INR gets one meaningless number. The check runs against
    the tenant's real data, not against the SQL text."""
    _seed_invoice(db_session, vendor_name="Harbor Tech", currency="USD", grand_total=100.0)
    _seed_invoice(db_session, vendor_name="Rajesh Steel", currency="INR", grand_total=118000.0)
    llm = _RecordingLLM([
        MagicMock(sql=_sql("SUM(grand_total) AS total_spend", tenant=MOCK_TENANT_ID.hex),
                  explanation_or_error=None)
    ])
    result = _aggregate(db_session, llm, "what did we spend in total")

    assert result.status == "multi_currency"
    assert result.currencies == ["INR", "USD"]
    assert "Never present this number" in result.message


def test_aggregate_accepts_an_ungrouped_total_for_a_single_currency_tenant(db_session):
    """The other half of that check, and why it reads the data rather than the
    SQL: a single-currency tenant that skipped GROUP BY produced a correct
    number, and failing that turn would be its own wrong answer."""
    _seed_invoice(db_session, vendor_name="Harbor Tech", currency="USD", grand_total=100.0)
    _seed_invoice(db_session, vendor_name="Metro Office", currency="USD", grand_total=250.0)
    llm = _RecordingLLM([
        MagicMock(sql=_sql("SUM(grand_total) AS total_spend", tenant=MOCK_TENANT_ID.hex),
                  explanation_or_error=None)
    ])
    result = _aggregate(db_session, llm, "what did we spend in total")

    assert result.status == "ok"
    assert result.currencies == ["USD"]


def test_aggregate_states_the_calendar_year_assumption_on_an_ambiguous_range(db_session):
    """"This quarter" is genuinely ambiguous between the calendar year and an
    April-March fiscal year, and no fiscal-year setting exists on the tenant
    model. Faithfulness by construction applies to date-range assumptions too."""
    _seed_invoice(db_session, vendor_name="Harbor Tech", grand_total=100.0)
    llm = _RecordingLLM([
        MagicMock(sql=_sql("SUM(grand_total) AS total, currency", tenant=MOCK_TENANT_ID.hex)
                  + " GROUP BY currency", explanation_or_error=None)
    ])
    result = _aggregate(db_session, llm, "how much did we spend this quarter")

    assert "CALENDAR year was used" in result.fiscal_year_note
    assert result.status_inclusion_note and "soft-deleted" in result.status_inclusion_note


@pytest.mark.parametrize(
    "question,expected",
    [
        ("how much did we spend this quarter", "this quarter"),
        ("total for this year", "this year"),
        ("spend YTD", "YTD"),
        ("what did we spend in Q3", "Q3"),
        ("how much did we spend in July 2026", None),
        ("how much did we spend between 2026-01-01 and 2026-03-31", None),
    ],
)
def test_ambiguous_date_range_detection_is_deterministic(question, expected):
    assert detect_ambiguous_date_range(question) == expected


def test_aggregate_emits_its_own_telemetry_event(db_session):
    llm = _RecordingLLM([
        MagicMock(sql=_sql("SUM(grand_total) AS total, currency", tenant=MOCK_TENANT_ID.hex)
                  + " GROUP BY currency", explanation_or_error=None)
    ])
    with patch("telemetry.track_agent_call") as tracked:
        _aggregate(db_session, llm, "what did we spend in total")

    assert [call.args[0] for call in tracked.call_args_list] == ["sage.aggregate"]


def test_aggregate_includes_tenant_context_blocks_when_asked(db_session):
    """The trainer/chat-rule/tenant-stats blocks are the same ones the live route
    injects; the tool can opt out of the round-trips but must render them
    identically when it doesn't."""
    llm = _RecordingLLM([
        MagicMock(sql=_sql("SUM(grand_total) AS total, currency", tenant=MOCK_TENANT_ID.hex)
                  + " GROUP BY currency", explanation_or_error=None)
    ])
    with patch("agents.query_tools._get_global_business_rules", return_value=["tax_amount is CGST+SGST summed"]), \
         patch("agents.query_tools._get_vendor_business_rules", return_value=[]), \
         patch("agents.query_tools._chat_rules_block", return_value=""), \
         patch("agents.query_tools._get_tenant_stats_summary", return_value="Tenant Data Snapshot: 4 total invoices"):
        aggregate("what is our total spend", MOCK_TENANT_ID.hex, db_session, llm=llm,
                  include_tenant_context=True)

    prompt = llm.prompts[0]
    assert "tax_amount is CGST+SGST summed" in prompt
    assert "Tenant Data Snapshot: 4 total invoices" in prompt


def test_no_tool_composes_prose_or_makes_a_summary_call(db_session):
    """Deliberate, documented difference from the live route: a tool returns data
    and stops. Composing prose is the orchestrator's job -- a tool that answers in
    prose is the one-shot shape this feature exists to replace."""
    _seed_invoice(db_session, vendor_name="Harbor Tech", grand_total=100.0)
    llm = _RecordingLLM([
        MagicMock(sql=_sql("SUM(grand_total) AS total, currency", tenant=MOCK_TENANT_ID.hex)
                  + " GROUP BY currency", explanation_or_error=None),
        MagicMock(sql=_sql(tenant=MOCK_TENANT_ID.hex), explanation_or_error=None),
    ])
    _aggregate(db_session, llm, "what is our total spend")
    _identify(db_session, llm, "the Harbor Tech invoice")

    assert llm.summary_prompts == []


# ── name normalization, on its own ──────────────────────────────────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Om Packaging", "om packaging"),
        ("Om Packaging Pvt Ltd", "om packaging"),
        ("OM  PACKAGING  ", "om packaging"),
        ("Om Packaging Pvt. Ltd.", "om packaging"),
        ("Cascade Manufacturing Co", "cascade manufacturing"),
        ("Acme Inc.", "acme"),
        ("Globex Corporation", "globex"),
        ("Initech LLC", "initech"),
        (None, ""),
    ],
)
def test_entity_name_normalization(raw, expected):
    assert normalize_entity_name(raw) == expected


# ── compute: per-currency arithmetic ────────────────────────────────────────


def test_compute_sums_amounts_within_one_currency():
    result = compute("sum_by_currency", [
        {"amount": 1200.00, "currency": "USD"},
        {"amount": 250.00, "currency": "USD"},
        {"amount": 2000.00, "currency": "USD"},
    ])

    assert result.status == "ok"
    assert result.by_currency == {"USD": 3450.00}
    assert result.counts == {"USD": 3}
    assert result.formatted == ["USD 3,450.00"]


def test_compute_never_combines_different_currencies():
    """The same rule the SQL summary prompt states in prose ('never one total
    added across different currencies -- no exchange rate is available'), made
    structural: there is no field on the result that could hold a combined
    total, so no caller can produce one by mistake."""
    result = compute("sum_by_currency", [
        {"amount": 100.00, "currency": "USD"},
        {"amount": 5000.00, "currency": "INR"},
        {"amount": 40.00, "currency": "EUR"},
        {"amount": 25.00, "currency": "usd"},  # casing must not fork the bucket
    ])

    assert result.status == "ok"
    assert result.by_currency == {"EUR": 40.00, "INR": 5000.00, "USD": 125.00}
    assert 5165.00 not in result.by_currency.values()
    assert "no exchange rate is available" in result.note
    assert not hasattr(result, "total")


def test_compute_puts_an_unlabelled_amount_in_its_own_bucket_not_usd():
    """A missing currency is a fact about the data, not an invitation to assume
    dollars -- assuming it is exactly the kind of confident wrong financial claim
    this feature exists to make harder."""
    result = compute("sum_by_currency", [
        {"amount": 10.00, "currency": "USD"},
        {"amount": 90.00, "currency": None},
        {"amount": 5.00},
    ])

    assert result.by_currency == {"UNKNOWN": 95.00, "USD": 10.00}


def test_compute_accepts_plain_amount_currency_pairs():
    result = compute("sum_by_currency", [(732.57, "USD"), (29302.94, "USD")])
    assert result.by_currency == {"USD": 30035.51}


def test_compute_does_not_reintroduce_float_noise():
    """Gaps 266/272 were both this symptom rendered into chat (7.249887640449439,
    5436.3099999999995). Decimal-via-str arithmetic, quantized to this
    codebase's existing 2dp currency precision."""
    result = compute("sum_by_currency", [
        {"amount": 0.1, "currency": "USD"},
        {"amount": 0.2, "currency": "USD"},
        {"amount": 5436.3099999999995, "currency": "USD"},
    ])

    assert result.by_currency == {"USD": 5436.61}
    assert result.formatted == ["USD 5,436.61"]


def test_compute_reads_amounts_as_rendered_in_a_results_table():
    result = compute("sum_by_currency", [
        {"amount": "1,200.50", "currency": "USD"},
        {"amount": "$99.50", "currency": "USD"},
    ])
    assert result.by_currency == {"USD": 1300.00}


def test_compute_errors_rather_than_silently_dropping_a_bad_amount():
    result = compute("sum_by_currency", [
        {"amount": 100.00, "currency": "USD"},
        {"amount": "not a number", "currency": "USD"},
    ])

    assert result.status == "error"
    assert "index 1" in result.message
    assert result.by_currency == {}


def test_compute_rejects_an_unknown_operation():
    result = compute("average_by_vendor", [{"amount": 1, "currency": "USD"}])
    assert result.status == "error"
    assert "sum_by_currency" in result.message


# ── compute: the reconciliation-mismatch shape ──────────────────────────────


def test_compute_flags_the_historical_false_equation_case():
    """Gap 269 (US tenant test, Q4 and Q10): the reply stated '5000.00 units x
    USD 0.08 = USD 420.00' -- false, since 5000 x 0.08 is 400.00. The summary
    prompt's 'EXCEPTION -- reconciliation/mismatch questions' paragraph asks the
    model not to do that. Here the equation simply cannot be produced: both
    figures come back separately, with the mismatch named."""
    result = compute("reconcile_line_items", [
        {
            "description": "Steel bolts",
            "quantity": 5000.00,
            "unit_price": 0.08,
            "amount": 420.00,
            "currency": "USD",
        }
    ])

    assert result.status == "ok"
    row = result.rows[0]
    assert row["computed_amount"] == 400.00
    assert row["stated_amount"] == 420.00
    assert row["matches"] is False
    assert row["difference"] == 20.00
    assert result.all_match is False
    assert result.mismatches == [row]
    assert "mismatch" in result.formatted[0]
    assert "= USD 420.00" not in result.formatted[0]  # the false equation is unrenderable


def test_compute_uses_the_plain_equation_when_a_line_actually_reconciles():
    result = compute("reconcile_line_items", [
        {
            "description": "Training & Onboarding",
            "quantity": 40,
            "unit_price": 732.57,
            "amount": 29302.80,
            "currency": "USD",
        }
    ])

    row = result.rows[0]
    assert row["matches"] is True
    assert row["difference"] == 0.0
    assert result.all_match is True
    assert result.mismatches == []
    assert result.formatted[0] == "Training & Onboarding: 40 x USD 732.57 = USD 29,302.80"


def test_compute_reconciles_a_mixed_batch_and_keeps_each_rows_own_currency():
    result = compute("reconcile_line_items", [
        {"description": "Onboarding pack", "quantity": 2, "unit_price": 50.00, "amount": 100.00, "currency": "INR"},
        {"description": "Steel bolts", "quantity": 5000, "unit_price": 0.08, "amount": 420.00, "currency": "USD"},
    ])

    assert result.all_match is False
    assert [row["currency"] for row in result.rows] == ["INR", "USD"]
    assert [row["matches"] for row in result.rows] == [True, False]
    assert len(result.mismatches) == 1


def test_compute_reconcile_errors_on_a_missing_field():
    result = compute("reconcile_line_items", [{"description": "Steel bolts", "quantity": 5000}])
    assert result.status == "error"
    assert "index 0" in result.message


# ── ask_clarifying_question ─────────────────────────────────────────────────


def test_ask_clarifying_question_returns_a_turn_ending_contract():
    """The contract the orchestrator's loop branches on: a status that says this
    turn ends in a question, the question itself, and a reason code from a closed
    vocabulary -- not prose the orchestrator has to interpret."""
    result = ask_clarifying_question(
        "Do you mean the invoice Titan Steel Distributors sent you, or one you sent them?",
        "AMBIGUOUS_DIRECTION",
    )

    assert result.status == "needs_clarification"
    assert result.ends_turn is True
    assert result.reason == "AMBIGUOUS_DIRECTION"
    assert result.reason in CLARIFICATION_REASONS
    assert result.reason_detail is None
    assert result.question.startswith("Do you mean")

    payload = result.to_dict()
    assert set(payload) == {"question", "reason", "reason_detail", "status", "ends_turn"}
    assert payload["status"] == "needs_clarification"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("ambiguous-direction", "AMBIGUOUS_DIRECTION"),
        ("ambiguous time range", "AMBIGUOUS_TIME_RANGE"),
        ("no_results", "NO_RESULTS"),
        ("  UNSUPPORTED_FIELD  ", "UNSUPPORTED_FIELD"),
    ],
)
def test_ask_clarifying_question_normalizes_known_reason_codes(raw, expected):
    assert ask_clarifying_question("Which one did you mean?", raw).reason == expected


def test_ask_clarifying_question_downgrades_an_unknown_reason_instead_of_failing():
    """A model inventing a plausible-but-unknown code should still get to ask its
    question -- crashing the turn over a label would be worse than the guess this
    tool exists to prevent."""
    result = ask_clarifying_question("Which vendor did you mean?", "vendor_name_collision")

    assert result.reason == "OTHER"
    assert result.reason_detail == "vendor_name_collision"
    assert result.status == "needs_clarification"


@pytest.mark.parametrize("empty", ["", "   ", None])
def test_ask_clarifying_question_rejects_an_empty_question(empty):
    with pytest.raises(ValueError):
        ask_clarifying_question(empty, "AMBIGUOUS_ENTITY")


def test_ask_clarifying_question_result_is_immutable():
    """Frozen on purpose: once the loop has been told this turn ends in a
    question, nothing downstream should be able to edit the question or quietly
    flip ends_turn."""
    result = ask_clarifying_question("Which one?", "AMBIGUOUS_ENTITY")
    with pytest.raises(Exception):
        result.ends_turn = False


# ── the flag boundary ───────────────────────────────────────────────────────


def test_no_tool_is_wired_into_the_live_chat_pipeline():
    """No tool is ever reached from the live pipeline directly.

    The orchestrator is the only caller of these tools, `run_query_agent()`
    reaches it through exactly one `ENABLE_AGENTIC_SAGE`-guarded branch (asserted
    in `test_agentic_sage.py::test_the_orchestrator_is_reachable_only_through_the_settings_flag`),
    and with the flag off `query_agent` does not import `query_tools` or
    `sage_orchestrator` at all. A tool called straight from the classify-and-fork
    path would bypass the flag entirely -- which is the mistake the original
    Feature 21's revert was about."""
    import ast
    import inspect

    from agents import query_agent

    tree = ast.parse(inspect.getsource(query_agent))

    imported = set()
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)

    assert not any("query_tools" in name for name in imported)
    for tool in ("identify_invoices", "get_full_record", "search_invoices", "aggregate",
                 "ask_clarifying_question", "compute"):
        assert tool not in called, f"{tool} appears to be wired into the live pipeline already"
