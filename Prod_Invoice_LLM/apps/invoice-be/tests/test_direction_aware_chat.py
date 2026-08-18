"""Tests for Feature 6.1 (Direction-Aware Chat). Mirrors test_rag.py's
conventions. Covers: Task 6.1.1 (schema description includes the 3 new
columns + combined-question pattern), Task 6.1.2 (_get_global_business_rules
unions INBOUND + OUTBOUND Global templates, with a regression check that
INBOUND-only tenants see identical behavior to before this feature), and
Task 6.1.3 (RAG indexing fires on VERIFIED, not on NEEDS_REVIEW)."""
import os
from unittest.mock import patch, MagicMock
from uuid import uuid4

import pytest
from sqlmodel import SQLModel, create_engine, Session
from sqlalchemy.pool import StaticPool

os.environ["MOCK_EMBEDDINGS"] = "true"

from dependencies import MOCK_TENANT_ID
from models import ExtractionTemplate, Invoice
from agents.query_agent import _get_global_business_rules

sqlite_url = "sqlite:///:memory:"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


# ── Task 6.1.2: Global rules union across both directions ───────────────────

def test_global_rules_inbound_only_unchanged_behavior(db_session):
    """Regression check: a tenant with only today's usual INBOUND Global
    template must see identical behavior to before this feature."""
    db_session.add(ExtractionTemplate(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, vendor_name=None, flow_direction="INBOUND",
        rules={"constraints": ["Parse dates as DD/MM/YYYY"]}, version=1,
    ))
    db_session.commit()

    rules = _get_global_business_rules(str(MOCK_TENANT_ID), db_session)
    assert rules == ["Parse dates as DD/MM/YYYY"]


def test_global_rules_unions_inbound_and_outbound(db_session):
    db_session.add(ExtractionTemplate(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, vendor_name=None, flow_direction="INBOUND",
        rules={"constraints": ["Parse dates as DD/MM/YYYY"]}, version=1,
    ))
    db_session.add(ExtractionTemplate(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, vendor_name=None, flow_direction="OUTBOUND",
        rules={"constraints": ["Read customer name from the Bill To block"]}, version=1,
    ))
    db_session.commit()

    rules = _get_global_business_rules(str(MOCK_TENANT_ID), db_session)
    assert set(rules) == {"Parse dates as DD/MM/YYYY", "Read customer name from the Bill To block"}


def test_global_rules_outbound_only(db_session):
    db_session.add(ExtractionTemplate(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, vendor_name=None, flow_direction="OUTBOUND",
        rules={"constraints": ["Outbound-only rule"]}, version=1,
    ))
    db_session.commit()

    rules = _get_global_business_rules(str(MOCK_TENANT_ID), db_session)
    assert rules == ["Outbound-only rule"]


def test_global_rules_no_duplicates_if_same_rule_text_in_both(db_session):
    db_session.add(ExtractionTemplate(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, vendor_name=None, flow_direction="INBOUND",
        rules={"constraints": ["Shared rule text"]}, version=1,
    ))
    db_session.add(ExtractionTemplate(
        id=uuid4(), tenant_id=MOCK_TENANT_ID, vendor_name=None, flow_direction="OUTBOUND",
        rules={"constraints": ["Shared rule text"]}, version=1,
    ))
    db_session.commit()

    rules = _get_global_business_rules(str(MOCK_TENANT_ID), db_session)
    assert rules == ["Shared rule text"]


def test_global_rules_empty_when_no_templates(db_session):
    assert _get_global_business_rules(str(MOCK_TENANT_ID), db_session) == []


# ── Task 6.1.1: schema-description prompt includes the new columns ──────────

def test_sql_route_prompt_includes_direction_aware_columns(db_session):
    from agents import query_agent

    invoice_id = uuid4()
    db_session.add(Invoice(
        id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/out.pdf", flow_direction="OUTBOUND",
        status="SENT", customer_name="Vertex Industries", grand_total=500.0,
    ))
    db_session.commit()

    captured_prompts = []

    class MockStructuredSQL:
        def invoke(self, prompt):
            captured_prompts.append(prompt)
            return MagicMock(sql=f"SELECT * FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}' AND flow_direction='OUTBOUND'")

    class MockLLM:
        def with_structured_output(self, schema):
            return MockStructuredSQL()

        def invoke(self, prompt):
            return MagicMock(content="Vertex Industries owes $500.00.")

    with patch("agents.query_agent.classify_query", return_value="SQL"), \
         patch("agents.query_agent.get_llm", return_value=MockLLM()), \
         patch("agents.query_agent.get_cached_answer", return_value=None), \
         patch("agents.query_agent.set_cached_answer"), \
         patch("agents.query_agent.get_chat_history", return_value=""):
        query_agent.run_query_agent(str(uuid4()), "What does Vertex Industries owe me?", str(MOCK_TENANT_ID), db_session)

    assert len(captured_prompts) == 1
    prompt_text = captured_prompts[0]
    assert "flow_direction" in prompt_text
    assert "customer_name" in prompt_text
    assert "customer_id" in prompt_text
    assert "total_owed_by_us" in prompt_text  # the combined-question example pattern
    assert "total_owed_to_us" in prompt_text


# ── Task 6.1.3 / Gap 243: RAG indexing fires on VERIFIED *and* NEEDS_REVIEW ──
#
# Originally this pair asserted "VERIFIED indexes, NEEDS_REVIEW does not",
# locking in the `status == "VERIFIED"` gate. BE Gap 243 established that gate
# was a bug: because routers/outbound_audit.py's resolve path never mutates
# `invoice.status`, a NEEDS_REVIEW outbound invoice stayed unindexed for the
# life of the row, so a customer-facing invoice a human had to review could
# never be found through RAG chat -- not even after it was resolved. The second
# test below is therefore inverted deliberately, not relaxed.

def test_verified_outbound_invoice_triggers_rag_indexing(db_session):
    from queue_worker import outbound_handlers

    invoice_id = uuid4()
    db_session.add(Invoice(id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/out.pdf", flow_direction="OUTBOUND", status="UPLOADED"))
    db_session.commit()

    with patch("queue_worker.outbound_handlers.engine", engine), \
         patch("queue_worker.outbound_handlers._run_ocr", return_value="ocr text"), \
         patch("queue_worker.outbound_handlers._publish_sse_events"), \
         patch("queue_worker.outbound_handlers.run_outbound_extraction_agent") as m_extract, \
         patch("chroma_client.index_invoice_document") as m_index:
        m_extract.return_value = {
            "status": "VERIFIED", "alerts": [],
            "extracted_data": {"customer_name": "Vertex Industries", "invoice_number": "OUT-1", "grand_total": 500.0},
        }
        outbound_handlers.handle_process_outbound_invoice("batch-1", "mock/out.pdf", str(MOCK_TENANT_ID))

    m_index.assert_called_once()
    call_kwargs = m_index.call_args.kwargs
    assert call_kwargs["vendor_name"] == "Vertex Industries"  # customer_name passed through the vendor_name param
    assert call_kwargs["invoice_id"] == str(invoice_id)


def test_needs_review_outbound_invoice_also_triggers_rag_indexing(db_session):
    """Gap 243: a NEEDS_REVIEW outbound invoice must be indexed at ingestion
    just like a VERIFIED one. Its text is exactly as searchable, and the
    verification outcome says nothing about whether the document's content
    should be findable."""
    from queue_worker import outbound_handlers

    invoice_id = uuid4()
    db_session.add(Invoice(id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/out.pdf", flow_direction="OUTBOUND", status="UPLOADED"))
    db_session.commit()

    with patch("queue_worker.outbound_handlers.engine", engine), \
         patch("queue_worker.outbound_handlers._run_ocr", return_value="ocr text"), \
         patch("queue_worker.outbound_handlers._publish_sse_events"), \
         patch("queue_worker.outbound_handlers.run_outbound_extraction_agent") as m_extract, \
         patch("chroma_client.index_invoice_document") as m_index:
        m_extract.return_value = {
            "status": "NEEDS_REVIEW",
            "alerts": [{"type": "missing_required_field", "field": "customer_name", "message": "..."}],
            "extracted_data": {"invoice_number": "OUT-2", "grand_total": 500.0},
        }
        outbound_handlers.handle_process_outbound_invoice("batch-2", "mock/out.pdf", str(MOCK_TENANT_ID))

    m_index.assert_called_once()
    assert m_index.call_args.kwargs["invoice_id"] == str(invoice_id)


def test_unextracted_outbound_invoice_is_not_rag_indexed(db_session):
    """The other side of Gap 243's contract: widening the gate must not mean
    indexing everything. A FAILED extraction has no usable content, so
    should_index_status() still keeps it out."""
    from queue_worker import outbound_handlers

    invoice_id = uuid4()
    db_session.add(Invoice(id=invoice_id, tenant_id=MOCK_TENANT_ID, file_path="mock/out.pdf", flow_direction="OUTBOUND", status="UPLOADED"))
    db_session.commit()

    with patch("queue_worker.outbound_handlers.engine", engine), \
         patch("queue_worker.outbound_handlers._run_ocr", return_value="ocr text"), \
         patch("queue_worker.outbound_handlers._publish_sse_events"), \
         patch("queue_worker.outbound_handlers.run_outbound_extraction_agent") as m_extract, \
         patch("chroma_client.index_invoice_document") as m_index:
        m_extract.return_value = {
            "status": "FAILED", "alerts": [], "extracted_data": {},
        }
        outbound_handlers.handle_process_outbound_invoice("batch-3", "mock/out.pdf", str(MOCK_TENANT_ID))

    m_index.assert_not_called()
