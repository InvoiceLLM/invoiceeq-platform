"""Feature 29 task 29.5 — `services/full_records.py`, against REAL Postgres.

Hard rule 2: this file does not run on SQLite at all. It skips when
`DATABASE_URL` is not Postgres or the local container is not reachable, because
the two behaviours under test here are precisely the ones SQLite gets wrong:

  * `items` / `taxes` / `sa_alerts` / `payment_instructions` are **JSONB**
    columns in Postgres and plain JSON-in-TEXT in SQLite, and this module's whole
    contract is "the parsed structures reach the prompt";
  * the cross-tenant refusal is a `WHERE tenant_id = <uuid>` comparison against a
    real UUID column, and SQLite stores UUIDs dashless, which is the fidelity gap
    that has bitten this repo four times.

Every row is created under a throwaway tenant UUID and deleted in the fixture's
teardown, so the test leaves the shared dev database exactly as it found it.
"""
import os
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from models import Invoice  # noqa: E402
from services import full_records  # noqa: E402


@pytest.fixture(name="pg_session")
def pg_session_fixture():
    psycopg2 = pytest.importorskip("psycopg2")
    from config import get_settings

    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        psycopg2.connect(url, connect_timeout=5).close()
    except psycopg2.OperationalError as exc:  # pragma: no cover - env dependent
        pytest.skip(f"local Postgres not reachable: {exc}")

    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="tenant")
def tenant_fixture(pg_session):
    """A throwaway tenant id, with every invoice written under it removed after."""
    tenant_id = uuid4()
    yield tenant_id
    for inv in pg_session.exec(select(Invoice).where(Invoice.tenant_id == tenant_id)).all():
        pg_session.delete(inv)
    pg_session.commit()


def _seed(pg_session, tenant_id, **kwargs):
    defaults = dict(
        id=uuid4(),
        tenant_id=tenant_id,
        file_path="f29/full-records.pdf",
        flow_direction="INBOUND",
        status="COMPLETED",
        invoice_number=f"F29-{uuid4().hex[:8].upper()}",
        vendor_name="Rajesh Steel Traders",
        currency="INR",
        subtotal=1000.0,
        tax_amount=180.0,
        grand_total=1180.0,
        items=[{"description": "MS Angle 50x50", "quantity": 10, "unit_price": 100.0, "amount": 1000.0}],
        taxes=[
            {"tax_type": "CGST", "rate_percent": 9.0, "amount": 90.0},
            {"tax_type": "SGST", "rate_percent": 9.0, "amount": 90.0},
        ],
        sa_alerts=[{"type": "duplicate_suspected", "severity": "warning"}],
        payment_instructions=[{"bank_name": "HDFC", "account_number": "XXXX1234"}],
        notes="Delivery to gate 3 only.",
    )
    defaults.update(kwargs)
    inv = Invoice(**defaults)
    pg_session.add(inv)
    pg_session.commit()
    return inv


# ---------------------------------------------------------------------------
# The evidence the golden set was missing
# ---------------------------------------------------------------------------


def test_every_column_survives_the_round_trip_including_the_json_ones(pg_session, tenant):
    """Spec section 2.3: `items`, `taxes`, `sa_alerts`, `payment_instructions`,
    `notes` and `subtotal` were absent from the prompt on 29 of 36 golden turns.
    They are the reason this module exists, so they are asserted by name, as
    parsed structures rather than as a JSON string."""
    inv = _seed(pg_session, tenant)

    result = full_records.fetch_full_records([str(inv.id)], str(tenant), pg_session)

    assert len(result.records) == 1
    record = result.records[0].record
    assert record["invoice_number"] == inv.invoice_number
    assert record["subtotal"] == 1000.0
    assert record["notes"] == "Delivery to gate 3 only."
    # Parsed, not a string: a prompt that shows `"[{\\"tax_type\\"..."` is the
    # same failure as not showing it.
    assert isinstance(record["taxes"], list)
    assert {t["tax_type"] for t in record["taxes"]} == {"CGST", "SGST"}
    assert isinstance(record["items"], list) and record["items"][0]["amount"] == 1000.0
    assert isinstance(record["sa_alerts"], list) and record["sa_alerts"]
    assert isinstance(record["payment_instructions"], list)
    assert result.records[0].has_alerts is True

    block = full_records.full_record_block(result)
    assert "FULL INVOICE RECORD(S)" in block
    assert '"tax_type": "CGST"' in block
    assert "Delivery to gate 3 only." in block


def test_identity_uuids_never_reach_the_prompt(pg_session, tenant):
    """Gap 294 is not weakened by moving the block into a service."""
    inv = _seed(pg_session, tenant)

    result = full_records.fetch_full_records([str(inv.id)], str(tenant), pg_session)
    block = full_records.full_record_block(result)

    assert str(tenant) not in block
    assert str(inv.id) not in block
    assert "tenant_id" not in result.records[0].record
    assert "id" not in result.records[0].record


def test_another_tenants_invoice_is_not_returned(pg_session, tenant):
    """`get_full_record` refuses cross-tenant as `not_found`; asserted here
    because this module is now the caller that decides what a chat turn sees."""
    other_tenant = uuid4()
    theirs = _seed(pg_session, other_tenant, vendor_name="Someone Else Ltd")
    try:
        result = full_records.fetch_full_records([str(theirs.id)], str(tenant), pg_session)
        assert result.records == []
        assert full_records.full_record_block(result) == ""
    finally:
        pg_session.delete(pg_session.get(Invoice, theirs.id))
        pg_session.commit()


# ---------------------------------------------------------------------------
# The cap — spec section 11 decision 1 (founder-ruled: 25, and disclose)
# ---------------------------------------------------------------------------


def test_the_cap_is_twenty_five_and_comes_from_settings(monkeypatch):
    assert full_records.DEFAULT_MAX_INVOICES == 25
    from config import get_settings

    assert get_settings().CHAT_FULL_RECORD_MAX_INVOICES == 25


def test_over_the_cap_discloses_the_count_instead_of_going_silent(pg_session, tenant):
    """Gap 310's bound returned `""` past three invoices, so a 40-invoice turn
    answered from a 2-column projection **with no disclosure at all**. Decision 1
    replaced that: name the count, list the ids, ask the user to narrow."""
    ids = [str(uuid4()) for _ in range(4)]

    result = full_records.fetch_full_records(ids, str(tenant), pg_session, max_invoices=3)

    assert result.over_cap is True
    assert result.records == []
    assert result.unrendered_ids == ids
    block = full_records.full_record_block(result)
    assert block != ""
    assert "4 invoices" in block
    assert "narrower" in block
    assert ids[0] in block
    # And it must not pretend to carry detail it does not have.
    assert "tax_type" not in block


def test_under_the_cap_every_record_is_rendered(pg_session, tenant):
    invoices = [_seed(pg_session, tenant) for _ in range(3)]

    block = full_records.full_record_block(
        full_records.fetch_full_records(
            [str(i.id) for i in invoices], str(tenant), pg_session
        )
    )

    assert block.count("FULL INVOICE RECORD(S)") == 1
    assert block.count('"tax_type": "CGST"') == 3


# ---------------------------------------------------------------------------
# Document chunks — the second half of the 22.2% -> 52.8% result
# ---------------------------------------------------------------------------


def test_document_pages_are_attached_for_a_single_invoice(pg_session, tenant, monkeypatch):
    """Spec section 2.3: **zero document chunks were cited on every one of the 36
    turns**. Chunks are fetched by invoice id, not by relevance ranking, so a page
    that exists is a page the model sees."""
    inv = _seed(pg_session, tenant)
    monkeypatch.setattr(
        "agents.query_tools.get_all_invoice_chunks",
        lambda invoice_id, tenant_id: [
            {
                "id": "chunk-1",
                "document": "Payment terms: net 45 days from delivery.",
                "metadata": {"page": 2, "invoice_id": str(inv.id)},
            }
        ],
    )

    result = full_records.fetch_full_records([str(inv.id)], str(tenant), pg_session)

    assert result.chunks_included is True
    assert result.records[0].chunks[0]["chunk_id"] == "chunk-1"
    block = full_records.full_record_block(result)
    assert "DOCUMENT PAGES" in block
    assert "net 45 days" in block
    assert "page 2" in block


def test_document_pages_are_skipped_and_disclosed_for_a_wide_turn(pg_session, tenant, monkeypatch):
    """The second, independent bound. A 25-invoice listing does not get 25
    documents' worth of page text -- but the turn is TOLD the document wording is
    not available, rather than being left to invent it."""
    invoices = [_seed(pg_session, tenant) for _ in range(3)]
    called = []
    monkeypatch.setattr(
        "agents.query_tools.get_all_invoice_chunks",
        lambda invoice_id, tenant_id: called.append(invoice_id) or [],
    )
    monkeypatch.setattr(full_records, "_chunk_invoice_limit", lambda: 2)

    result = full_records.fetch_full_records(
        [str(i.id) for i in invoices], str(tenant), pg_session
    )
    block = full_records.full_record_block(result)

    assert called == []  # no Chroma round-trip at all
    assert result.chunk_invoices_skipped == 3
    assert "document text is not attached" in block
    assert "DOCUMENT PAGES" not in block


def test_the_turn_wide_chunk_budget_is_enforced(pg_session, tenant, monkeypatch):
    inv = _seed(pg_session, tenant)
    monkeypatch.setattr(
        "agents.query_tools.get_all_invoice_chunks",
        lambda invoice_id, tenant_id: [
            {"id": f"c{n}", "document": "x" * 10_000, "metadata": {"page": n}}
            for n in range(1, 6)
        ],
    )
    monkeypatch.setattr(full_records, "MAX_TURN_CHUNK_CHARS", 25_000)

    result = full_records.fetch_full_records([str(inv.id)], str(tenant), pg_session)

    kept = result.records[0].chunks
    assert 0 < len(kept) <= 3
    assert sum(len(c["document"]) for c in kept) <= 30_000


# ---------------------------------------------------------------------------
# Fail-soft, and the empty cases
# ---------------------------------------------------------------------------


def test_no_ids_is_an_empty_block(pg_session, tenant):
    assert full_records.full_record_block_for([], str(tenant), pg_session) == ""
    assert full_records.full_record_block_for(None, str(tenant), pg_session) == ""


def test_a_failing_fetch_never_kills_the_turn(pg_session, tenant, monkeypatch):
    inv = _seed(pg_session, tenant)

    def _boom(*a, **kw):
        raise RuntimeError("chroma is down")

    monkeypatch.setattr("agents.query_tools.get_full_record", _boom)

    assert full_records.full_record_block_for([str(inv.id)], str(tenant), pg_session) == ""


def test_provenance_names_the_invoice_and_its_chunks(pg_session, tenant, monkeypatch):
    """Task 29.9 attaches provenance to every claim; this is the shape it reads."""
    inv = _seed(pg_session, tenant)
    monkeypatch.setattr(
        "agents.query_tools.get_all_invoice_chunks",
        lambda invoice_id, tenant_id: [
            {"id": "chunk-9", "document": "page text", "metadata": {"page": 1}}
        ],
    )

    result = full_records.fetch_full_records([str(inv.id)], str(tenant), pg_session)
    prov = result.provenance()

    assert prov == [
        {
            "invoice_id": str(inv.id),
            "invoice_number": inv.invoice_number,
            "source": "invoice_row",
            "chunk_ids": ["chunk-9"],
        }
    ]


# ---------------------------------------------------------------------------
# The wiring — asserted on the PROMPT, on real Postgres
# ---------------------------------------------------------------------------
#
# Gap 478 is why these exist here rather than being read off a golden run: the
# offline harness records `_ToolOutputRecorder.context()` and never sees a
# prompt-only block, so a golden artifact cannot answer "did the full record
# reach the model?" either way. These tests answer it directly, by capturing the
# prompt the route actually built.
#
# Every LLM seam is patched -- `get_llm` AND `build_llm`, which is Gap 471's
# lesson: with `AZURE_OPENAI_FAST_DEPLOYMENT_NAME` set, patching only `get_llm`
# leaves `_fast_llm()` free to build a real client and make a paid call from the
# unit suite.


class _PromptCapturingLLM:
    """Records every prompt, answers with something the gate will accept."""

    def __init__(self, sql: str, summary: str = "One invoice matched."):
        self._sql = sql
        self._summary = summary
        self.sql_prompts = []
        self.summary_prompts = []

    def with_structured_output(self, schema):
        outer = self

        class _Structured:
            def invoke(self, prompt):
                outer.sql_prompts.append(prompt)
                from unittest.mock import MagicMock

                return MagicMock(sql=outer._sql, explanation_or_error=None)

        return _Structured()

    def invoke(self, prompt, **kwargs):
        from unittest.mock import MagicMock

        self.summary_prompts.append(prompt)
        return MagicMock(content=self._summary)


def _run_sql_route(pg_session, tenant, message, sql):
    from contextlib import ExitStack
    from unittest.mock import MagicMock, patch
    from uuid import uuid4

    from agents import query_agent as qa

    llm = _PromptCapturingLLM(sql)
    turn = MagicMock()
    with ExitStack() as stack:
        for target in (
            patch.object(qa, "get_llm", return_value=llm),
            patch.object(qa, "build_llm", return_value=llm),
            patch.object(qa, "classify_query", return_value="SQL"),
            patch.object(qa, "query_invoice_chunks", return_value=[]),
            patch.object(qa, "get_cached_answer", return_value=None),
            patch.object(qa, "set_cached_answer"),
            patch.object(qa, "_get_tenant_stats_summary", return_value=""),
            patch.object(qa, "chat_rules_version", return_value="none"),
            patch.object(qa, "get_chat_history", return_value=""),
            patch.object(qa, "update_session_focus"),
        ):
            stack.enter_context(target)
        result = qa._run_query_agent(
            session_id=str(uuid4()),
            user_message=message,
            tenant_id=str(tenant),
            db_session=pg_session,
            turn=turn,
        )
    return result, llm


def test_the_full_record_block_reaches_the_summary_prompt_on_the_sql_route(pg_session, tenant):
    """Task 29.5's whole claim, asserted where it can be seen: the identified
    invoice's every column is in the prompt the summary model is given."""
    inv = _seed(pg_session, tenant)
    sql = (
        "SELECT id, invoice_number, grand_total FROM invoice "
        f"WHERE tenant_id = '{tenant}' AND invoice_number = '{inv.invoice_number}'"
    )

    result, llm = _run_sql_route(pg_session, tenant, "what tax is on that invoice", sql)

    assert llm.summary_prompts, "the summary call never happened"
    prompt = llm.summary_prompts[0]
    assert "FULL INVOICE RECORD(S)" in prompt
    assert '"tax_type": "CGST"' in prompt
    assert "Delivery to gate 3 only." in prompt
    # Gap 294 still holds on this path.
    assert str(tenant) not in prompt
    # 29.9: the provenance the FE will render once Gap 474 is decided.
    assert result.get("provenance")
    assert result["provenance"][0]["invoice_number"] == inv.invoice_number


def test_the_line_check_reaches_the_same_prompt(pg_session, tenant):
    """Task 29.6 on the same turn: the arithmetic is done in Python off the
    record's own `items`, with no line columns in the SELECT at all."""
    inv = _seed(
        pg_session,
        tenant,
        currency="USD",
        subtotal=420.0,
        grand_total=420.0,
        items=[{"description": "Bolts", "quantity": 5000, "unit_price": 0.08, "amount": 420.0}],
    )
    sql = (
        "SELECT id, invoice_number FROM invoice "
        f"WHERE tenant_id = '{tenant}' AND invoice_number = '{inv.invoice_number}'"
    )

    _, llm = _run_sql_route(pg_session, tenant, "does the bolts line add up", sql)

    prompt = llm.summary_prompts[0]
    assert "COMPUTED FIGURES" in prompt
    assert "computes to USD 400.00" in prompt
    assert "USD 20.00 over-stated" in prompt
    assert "do not reconcile" in prompt.split("- line arithmetic")[0]
