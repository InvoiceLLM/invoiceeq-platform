"""Feature 6.1 item C3 — zero rows is a diagnosis, never an answer.

The defect that started the whole review (Gap 413): "discount amount for apex
consulting group" became a line-item search for the word "discount", found zero
rows, and the sentinel was narrated back as a confident "no records found". The
Gap 305 fallbacks (direct invoice-number lookup, reflected category search) cover
two shapes. C3 adds the ladder for everything else, deterministically:

  identify → probe → vector → propose → ask back → telemetry

Hard rule 3 throughout: nothing on this ladder decides a figure. The only model
call is the RAG narration a `vector_answered` outcome hands off to, and that
narrates document text.

Hard rule 2: the execution-path tests run on real Postgres (`DATABASE_URL`), and
skip loudly rather than fall back to SQLite.
"""
import os
from datetime import date
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from agents import query_agent  # noqa: E402
from agents.query_agent import (  # noqa: E402
    NO_RECORDS_FOUND,
    _diagnose_zero_rows,
    _nearest_entity_names,
    _resend_text,
    _zero_rows_clarification,
    run_sql_generation_loop,
)

# ---------------------------------------------------------------------------
# Postgres — the only evidence this repo accepts for an execution path.
# ---------------------------------------------------------------------------

_DB_URL = os.environ.get("DATABASE_URL", "")
postgres_only = pytest.mark.skipif(
    not _DB_URL.startswith("postgresql"),
    reason="Hard rule 2: set DATABASE_URL to the dev Postgres (localhost:5433) and re-run.",
)

TENANT = UUID("aaaaaaaa-0000-4000-8000-00000000c301")
OTHER_TENANT = UUID("bbbbbbbb-0000-4000-8000-00000000c302")


@pytest.fixture(scope="module")
def pg_session():
    from sqlmodel import Session, create_engine

    engine = create_engine(_DB_URL)
    with Session(engine) as session:
        yield session


@pytest.fixture
def seeded(pg_session):
    """Two vendors for the tenant, one for another tenant, cleaned up after."""
    from models import Invoice

    # `file_path` is NOT NULL on Postgres even though the model defaults it to
    # None -- the SQLite suites never notice, which is exactly why hard rule 2
    # insists on this engine.
    rows = [
        Invoice(
            tenant_id=TENANT, invoice_number="APX-1001", vendor_name="Apex Consulting Group",
            grand_total=5400.0, currency="USD", invoice_date=date(2026, 6, 3), status="COMPLETED",
            file_path="tests/c3/apx-1001.pdf",
            items=[{"description": "Strategy workshop", "quantity": 1, "unit_price": 5400.0, "amount": 5400.0}],
        ),
        Invoice(
            tenant_id=TENANT, invoice_number="TSD-2002", vendor_name="Titan Steel Distributors",
            grand_total=12000.0, currency="USD", invoice_date=date(2026, 5, 20), status="COMPLETED",
            file_path="tests/c3/tsd-2002.pdf",
            items=[{"description": "Steel bolts", "quantity": 100, "unit_price": 120.0, "amount": 12000.0}],
        ),
        Invoice(
            tenant_id=OTHER_TENANT, invoice_number="OTH-9", vendor_name="Apex Consulting Group",
            grand_total=1.0, currency="USD", invoice_date=date(2026, 1, 1), status="COMPLETED",
            file_path="tests/c3/oth-9.pdf", items=[],
        ),
    ]
    for r in rows:
        pg_session.add(r)
    pg_session.commit()
    try:
        yield rows
    finally:
        for r in rows:
            pg_session.delete(r)
        pg_session.commit()


class _ScriptedLLM:
    """Replays one SQLGenerationSchema-shaped result per structured call."""

    def __init__(self, sql):
        self._sql = sql
        self.prompts = []

    def with_structured_output(self, schema):
        outer = self

        class _Runner:
            def invoke(self, prompt):
                outer.prompts.append(prompt)
                return MagicMock(sql=outer._sql, explanation_or_error=None)

        return _Runner()

    def invoke(self, prompt):  # never used on this path: the ladder makes no summary call
        raise AssertionError("C3 must not call the model on a zero-row diagnosis")


def _loop(sql, question, db, tenant=TENANT):
    return run_sql_generation_loop(
        llm=_ScriptedLLM(sql),
        system_prompt="prompt",
        wrapped_user_message=question,
        user_message=question,
        tenant_id=str(tenant),
        db_session=db,
    )


# ---------------------------------------------------------------------------
# Step 1 — the diagnosis is a deterministic split of the WHERE clause.
# ---------------------------------------------------------------------------


def test_diagnose_separates_identifying_from_narrowing():
    sql = (
        f"SELECT invoice_number, grand_total, currency FROM invoice "
        f"WHERE tenant_id = '{TENANT}' AND LOWER(vendor_name) LIKE LOWER('%apex consulting group%') "
        f"AND LOWER(CAST(items AS TEXT)) LIKE LOWER('%discount%')"
    )
    dx = _diagnose_zero_rows(sql, "postgresql")
    assert dx["parsed"] is True
    assert dx["narrowing"] is True, "the items LIKE is the narrowing predicate"
    assert any("vendor_name" in p for p in dx["identifying"])
    assert not any("items" in p for p in dx["identifying"])
    assert dx["entities"] == [("vendor_name", "apex consulting group")]


def test_diagnose_treats_rule_4a_direction_group_as_identifying():
    """An OR group that touches only identifying columns identifies."""
    sql = (
        f"SELECT * FROM invoice WHERE tenant_id = '{TENANT}' AND "
        f"((flow_direction='INBOUND' AND LOWER(vendor_name) LIKE LOWER('%titan%')) "
        f"OR (flow_direction='OUTBOUND' AND LOWER(customer_name) LIKE LOWER('%titan%'))) "
        f"AND status = 'PAID'"
    )
    dx = _diagnose_zero_rows(sql, "postgresql")
    assert dx["narrowing"] is True  # status
    assert len(dx["identifying"]) == 2  # tenant + the direction group
    assert ("vendor_name", "titan") in dx["entities"]


def test_diagnose_flags_a_category_group_as_narrowing():
    """Rule 6b's four-column group includes tags/items, so it narrows."""
    sql = (
        f"SELECT * FROM invoice WHERE tenant_id = '{TENANT}' AND "
        f"(LOWER(CAST(tags AS TEXT)) LIKE '%freight%' OR LOWER(CAST(items AS TEXT)) LIKE '%freight%' "
        f"OR LOWER(vendor_name) LIKE '%freight%' OR LOWER(customer_name) LIKE '%freight%')"
    )
    dx = _diagnose_zero_rows(sql, "postgresql")
    assert dx["narrowing"] is True
    assert dx["entities"] == []


def test_diagnose_fails_closed_on_unparseable_sql():
    dx = _diagnose_zero_rows("SELECT this is not (((", "postgresql")
    assert dx == {"identifying": [], "identifying_entities": 0, "narrowing": False, "entities": [], "parsed": False}


def test_diagnose_counts_only_entity_predicates_as_identifying():
    """tenant_id alone identifies nothing: dropping the narrowing would return
    every invoice the tenant has, which is not a recovery, it is a different
    question. The probe must not run on this shape."""
    sql = (
        f"SELECT invoice_number FROM invoice WHERE tenant_id = '{TENANT}' "
        f"AND LOWER(CAST(items AS TEXT)) LIKE LOWER('%late delivery penalty%')"
    )
    dx = _diagnose_zero_rows(sql, "postgresql")
    assert dx["narrowing"] is True
    assert dx["identifying_entities"] == 0
    assert len(dx["identifying"]) == 1  # the carried tenant predicate


# ---------------------------------------------------------------------------
# Step 4 — nearest names propose, never correct.
# ---------------------------------------------------------------------------


def test_nearest_names_finds_a_typo_and_ignores_nonsense():
    names = ["Apex Consulting Group", "Titan Steel Distributors", "Blue Ridge Logistics"]
    assert _nearest_entity_names("apex consultng grp", names) == ["Apex Consulting Group"]
    assert _nearest_entity_names("titan steel distributers", names) == ["Titan Steel Distributors"]
    assert _nearest_entity_names("zzyzx ltd", names) == []
    assert _nearest_entity_names("", names) == []


def test_resend_text_replaces_the_typo_in_place():
    out = _resend_text("discount amount for apex consultng grp", "apex consultng grp", "Apex Consulting Group")
    assert out == "discount amount for Apex Consulting Group"


def test_resend_text_appends_when_the_literal_is_not_verbatim_in_the_question():
    out = _resend_text("what did Apex bill us", "apex consultng", "Apex Consulting Group")
    assert out == "what did Apex bill us (vendor: Apex Consulting Group)"


def test_clarification_is_a_proposal_with_resend_options():
    payload = _zero_rows_clarification(
        "discount amount for apex consultng grp",
        [("vendor_name", "apex consultng grp")],
        {"apex consultng grp": ["Apex Consulting Group"]},
    )
    assert "Did you mean Apex Consulting Group" in payload["message"]
    assert payload["options"] == [
        {"intent": "resend", "label": "Yes — Apex Consulting Group",
         "text": "discount amount for Apex Consulting Group"}
    ]


def test_clarification_with_no_candidates_asks_back_without_options():
    payload = _zero_rows_clarification("invoices from zzyzx ltd", [("vendor_name", "zzyzx ltd")], {})
    assert "options" not in payload
    assert "zzyzx ltd" in payload["message"]
    assert "invoice number" in payload["message"]


# ---------------------------------------------------------------------------
# The ladder end to end, on Postgres.
# ---------------------------------------------------------------------------


@postgres_only
def test_gap_305_still_recovers_a_vendor_like_and_is_labelled(pg_session, seeded):
    """The Gap 413 shape with a vendor LIKE: Gap 305's reflected category search
    already recovers it (the vendor phrase matches on `vendor_name`), and C3 must
    not run on top of it. What C3 adds here is only the label."""
    sql = (
        f"SELECT invoice_number, grand_total, currency FROM invoice "
        f"WHERE tenant_id = '{TENANT}' AND LOWER(vendor_name) LIKE LOWER('%apex consulting group%') "
        f"AND LOWER(CAST(items AS TEXT)) LIKE LOWER('%discount%')"
    )
    with patch("agents.query_agent.query_invoice_chunks") as vec:
        out = _loop(sql, "discount amount for apex consulting group", pg_session)

    assert out.zero_result is False
    assert out.zero_result_fallback_recovered is True
    assert out.zero_result_diagnosis == "gap305_fallback"
    assert "APX-1001" in out.db_result
    assert out.clarification is None
    vec.assert_not_called()


@postgres_only
def test_narrowing_dropped_hands_the_identified_rows_to_the_answer(pg_session, seeded):
    """A rule-11 shape Gap 305 cannot recover: the invoice is identified by an
    equality (no LIKE literal for the category search to reflect) and the
    narrowing is a line-item keyword that matches nothing. C3's probe re-runs the
    identifier alone and hands the row to the full-record path."""
    sql = (
        f"SELECT invoice_number, grand_total, currency FROM invoice "
        f"WHERE tenant_id = '{TENANT}' AND invoice_number = 'APX-1001' "
        f"AND LOWER(CAST(items AS TEXT)) LIKE LOWER('%discount%')"
    )
    with patch("agents.query_agent.query_invoice_chunks") as vec:
        out = _loop(sql, "what was the discount on the apex invoice", pg_session)

    assert out.zero_result_diagnosis == "narrowing_dropped"
    assert out.zero_result is False
    assert out.zero_result_fallback_recovered is True
    assert "APX-1001" in out.db_result
    assert "OTH-9" not in out.db_result, "the probe leaked another tenant's row"
    assert out.clarification is None
    vec.assert_not_called(), "identified rows must win before the vector probe"


@postgres_only
def test_probe_never_widens_across_tenants(pg_session, seeded):
    """Same vendor exists for another tenant; the probe must stay inside its own."""
    sql = (
        f"SELECT invoice_number FROM invoice WHERE tenant_id = '{OTHER_TENANT}' "
        f"AND invoice_number = 'OTH-9' "
        f"AND LOWER(CAST(items AS TEXT)) LIKE LOWER('%discount%')"
    )
    with patch("agents.query_agent.query_invoice_chunks", return_value=[]):
        out = _loop(sql, "what was the discount on that invoice", pg_session, tenant=OTHER_TENANT)
    assert out.zero_result_diagnosis == "narrowing_dropped"
    assert "OTH-9" in out.db_result
    assert "APX-1001" not in out.db_result


@postgres_only
def test_typo_vendor_becomes_a_proposal_not_an_answer(pg_session, seeded):
    sql = (
        f"SELECT SUM(grand_total), currency FROM invoice WHERE tenant_id = '{TENANT}' "
        f"AND LOWER(vendor_name) LIKE LOWER('%apex consultng grp%') GROUP BY currency"
    )
    with patch("agents.query_agent.query_invoice_chunks", return_value=[]):
        out = _loop(sql, "discount amount for apex consultng grp", pg_session)

    assert out.zero_result is True
    assert out.zero_result_diagnosis == "clarified_with_candidates"
    assert out.clarification["options"][0]["text"] == "discount amount for Apex Consulting Group"
    assert out.clarification["options"][0]["intent"] == "resend"
    assert "Did you mean Apex Consulting Group" in out.clarification["message"]
    assert out.vector_chunks is None


@postgres_only
def test_textual_question_with_chunks_is_vector_answered(pg_session, seeded):
    """Mis-routed to SQL; the documents can answer it. No figure is produced here."""
    sql = (
        f"SELECT invoice_number FROM invoice WHERE tenant_id = '{TENANT}' "
        f"AND LOWER(CAST(items AS TEXT)) LIKE LOWER('%late delivery penalty%')"
    )
    chunks = [{"document": "Late delivery incurs a 2% penalty per week.",
               "metadata": {"invoice_id": str(uuid4()), "vendor_name": "Titan Steel Distributors", "page": 2},
               "distance": 0.31}]
    with patch("agents.query_agent.query_invoice_chunks", return_value=chunks):
        out = _loop(sql, "what does the contract say about late delivery penalties", pg_session)

    assert out.zero_result_diagnosis == "vector_answered"
    assert out.vector_chunks == chunks
    assert out.clarification is None
    assert out.db_result == NO_RECORDS_FOUND, "the loop itself must not invent rows"


@postgres_only
def test_unknown_vendor_and_no_documents_asks_back(pg_session, seeded):
    sql = (
        f"SELECT invoice_number FROM invoice WHERE tenant_id = '{TENANT}' "
        f"AND LOWER(vendor_name) LIKE LOWER('%zzyzx ltd%')"
    )
    with patch("agents.query_agent.query_invoice_chunks", return_value=[]):
        out = _loop(sql, "invoices from Zzyzx Ltd", pg_session)

    assert out.zero_result_diagnosis == "no_candidates"
    assert "options" not in out.clarification
    assert "zzyzx ltd" in out.clarification["message"]


@postgres_only
def test_a_query_with_rows_never_enters_the_ladder(pg_session, seeded):
    sql = (
        f"SELECT invoice_number, grand_total, currency FROM invoice "
        f"WHERE tenant_id = '{TENANT}' AND LOWER(vendor_name) LIKE LOWER('%titan%')"
    )
    with patch("agents.query_agent.query_invoice_chunks") as vec:
        out = _loop(sql, "what did titan bill us", pg_session)
    assert out.zero_result_diagnosis == ""
    assert out.clarification is None
    assert "TSD-2002" in out.db_result
    vec.assert_not_called()


# ---------------------------------------------------------------------------
# The turn: a proposal reaches the wire, and nothing is cached or summarised.
# ---------------------------------------------------------------------------


@postgres_only
def test_a_proposal_turn_carries_the_clarification_and_skips_summary_and_cache(pg_session, seeded):
    from models import ChatSession

    session_id = uuid4()
    pg_session.add(ChatSession(id=session_id, tenant_id=TENANT, title="C3"))
    pg_session.commit()
    try:
        sql = (
            f"SELECT SUM(grand_total), currency FROM invoice WHERE tenant_id = '{TENANT}' "
            f"AND LOWER(vendor_name) LIKE LOWER('%apex consultng grp%') GROUP BY currency"
        )
        llm = _ScriptedLLM(sql)
        with patch("agents.query_agent.classify_query", return_value="SQL"), \
             patch("agents.query_agent._generation_llm", return_value=llm), \
             patch("agents.query_agent._fast_llm", return_value=llm), \
             patch("agents.query_agent.get_llm", return_value=llm), \
             patch("agents.query_agent.get_chat_history", return_value=""), \
             patch("agents.query_agent._get_tenant_stats_summary", return_value=""), \
             patch("agents.query_agent.query_invoice_chunks", return_value=[]), \
             patch("agents.query_agent.get_cached_answer", return_value=None), \
             patch("agents.query_agent.set_cached_answer") as cache_write:
            out = query_agent.run_query_agent(
                str(session_id), "discount amount for apex consultng grp", str(TENANT), pg_session
            )
    finally:
        pg_session.rollback()
        cs = pg_session.get(ChatSession, session_id)
        if cs is not None:
            pg_session.delete(cs)
            pg_session.commit()

    assert out["needs_confirmation"] is True
    assert out["attachment_clarification"]["options"][0]["intent"] == "resend"
    assert "Did you mean Apex Consulting Group" in out["content"]
    assert NO_RECORDS_FOUND not in out["content"], "the sentinel must never reach the user"
    cache_write.assert_not_called(), "a proposal about this user's typo must not be cached"


def test_the_rag_branch_is_reachable_after_the_sql_branch():
    """C3 re-dispatches a vector_answered outcome into the RAG branch. That only
    works if RAG is a plain `if` after the SQL branch, and CHAT stays the catch-all
    for anything that is neither."""
    import inspect

    src = inspect.getsource(query_agent._run_query_agent)
    assert 'if route == "RAG":' in src
    assert 'elif route == "RAG":' not in src
    assert 'elif route != "SQL":  # CHAT' in src
    assert "chunks = forced_chunks if forced_chunks is not None else query_invoice_chunks(" in src
