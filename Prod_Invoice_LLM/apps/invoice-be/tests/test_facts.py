"""Tests for Feature 33 Task 33.8 — Facts Ledger & Emitters."""
from datetime import date
from uuid import uuid4
import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from models import Fact, ChatAttachment
from services.facts import (
    FACT_EMITTERS,
    emit_facts,
    facts_for,
    delete_facts_for_source,
    emit_commitment,
    emit_delivery_event,
    emit_payment_event,
    emit_terms,
    emit_period_accounts,
    emit_budget,
)


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_fact_emitters_registered():
    expected = {
        "emit_commitment",
        "emit_delivery_event",
        "emit_payment_event",
        "emit_terms",
        "emit_period_accounts",
        "emit_budget",
    }
    assert set(FACT_EMITTERS.keys()) == expected


def test_emit_commitment():
    tenant_id = uuid4()
    att_id = uuid4()
    att = ChatAttachment(
        id=att_id,
        tenant_id=tenant_id,
        session_id=uuid4(),
        filename="po_1041.pdf",
        blob_path="/blobs/po.pdf",
        doc_type="PURCHASE_ORDER",
        doc_number="PO-1041",
        party_name="Rajesh Steel",
        doc_date=date(2026, 9, 1),
        grand_total=440000.0,
        currency="INR",
        clearance="ops",
    )
    data = {
        "doc_type": "PURCHASE_ORDER",
        "doc_number": "PO-1041",
        "party_name": "Rajesh Steel",
        "grand_total": 440000.0,
        "currency": "INR",
        "line_items": [
            {"description": "Steel Rods", "quantity": 100, "unit_price": 4400, "total_amount": 440000}
        ],
    }
    facts = emit_commitment(att, data)
    assert len(facts) == 1
    f = facts[0]
    assert f.kind == "commitment"
    assert f.subject_kind == "po"
    assert f.subject_id == "PO-1041"
    assert f.counterparty_id == "Rajesh Steel"
    assert f.figures["total_amount"] == 440000.0
    assert f.clearance == "ops"


def test_emit_delivery_event():
    tenant_id = uuid4()
    att = ChatAttachment(
        id=uuid4(),
        tenant_id=tenant_id,
        session_id=uuid4(),
        filename="challan_88.pdf",
        blob_path="/blobs/challan.pdf",
        doc_type="DELIVERY_CHALLAN",
        doc_number="DC-88",
        party_name="Rajesh Steel",
        clearance="ops",
    )
    data = {
        "doc_type": "DELIVERY_CHALLAN",
        "doc_number": "DC-88",
        "party_name": "Rajesh Steel",
        "delivery_lines": [
            {"description": "Steel Rods", "delivered_quantity": 80, "po_reference": "PO-1041"}
        ],
    }
    facts = emit_delivery_event(att, data)
    assert len(facts) == 1
    f = facts[0]
    assert f.kind == "delivery_event"
    assert f.subject_kind == "delivery_note"
    assert f.figures["total_delivered_qty"] == 80.0


def test_emit_payment_event_option_c():
    tenant_id = uuid4()
    att = ChatAttachment(
        id=uuid4(),
        tenant_id=tenant_id,
        session_id=uuid4(),
        filename="bank_stmt.pdf",
        blob_path="/blobs/stmt.pdf",
        doc_type="BANK_STATEMENT",
        clearance="exec",  # Executive statement
    )
    data = {
        "doc_type": "BANK_STATEMENT",
        "statement_lines": [
            {
                "line_date": "2026-08-06",
                "narration": "NEFT-BHA-2002-PAID",
                "debit": 25000.0,
                "utr_ref": "UTR998877",
                "matched_invoice_id": "inv_123",  # Matched to ops-accessible invoice
            },
            {
                "line_date": "2026-08-07",
                "narration": "SALARY-AUG",
                "debit": 1490000.0,
                "utr_ref": "UTR112233",
                "matched_invoice_id": None,  # Non-invoice salary line
            },
        ],
    }
    facts = emit_payment_event(att, data)
    assert len(facts) == 2
    # Option C rule: Invoice match flows down to ops
    assert facts[0].clearance == "ops"
    assert facts[0].subject_id == "inv_123"
    # Salary line stays exec
    assert facts[1].clearance == "exec"


def test_emit_period_accounts_and_budget():
    tenant_id = uuid4()
    att = ChatAttachment(
        id=uuid4(),
        tenant_id=tenant_id,
        session_id=uuid4(),
        filename="fpa.pdf",
        blob_path="/blobs/fpa.pdf",
        doc_type="PERIOD_ACCOUNTS",
        clearance="exec",
    )
    data = {
        "period_accounts": [
            {"account_name": "Revenue", "revenue": 5000000, "expense": 0, "net_amount": 5000000},
            {"account_name": "COGS", "revenue": 0, "expense": 3000000, "net_amount": -3000000},
        ],
        "budgets": [
            {"account_name": "Marketing", "budget_amount": 200000, "period": "Q3"},
        ],
    }
    pnl_facts = emit_period_accounts(att, data)
    assert len(pnl_facts) == 2
    assert pnl_facts[0].kind == "period_accounts"

    budget_facts = emit_budget(att, data)
    assert len(budget_facts) == 1
    assert budget_facts[0].kind == "budget"
    assert budget_facts[0].figures["budget_amount"] == 200000.0


def test_emit_facts_and_facts_for_clearance(session: Session):
    tenant_id = uuid4()
    att = ChatAttachment(
        id=uuid4(),
        tenant_id=tenant_id,
        session_id=uuid4(),
        filename="po.pdf",
        blob_path="/blobs/po.pdf",
        doc_type="PO",
        doc_number="PO-999",
        party_name="Vendor X",
        clearance="ops",
    )
    data = {
        "doc_type": "PO",
        "doc_number": "PO-999",
        "party_name": "Vendor X",
        "grand_total": 10000.0,
        "line_items": [{"description": "Item A", "total_amount": 10000.0}],
    }
    facts = emit_facts(att, data, db_session=session)
    assert len(facts) == 1

    # Query with ops clearance
    ops_results = facts_for("po", "PO-999", clearance="ops", db_session=session, tenant_id=tenant_id)
    assert len(ops_results) == 1

    # Query with exec clearance
    exec_results = facts_for("po", "PO-999", clearance="exec", db_session=session, tenant_id=tenant_id)
    assert len(exec_results) == 1


def test_hard_delete_facts(session: Session):
    tenant_id = uuid4()
    att_id = uuid4()
    att = ChatAttachment(
        id=att_id,
        tenant_id=tenant_id,
        session_id=uuid4(),
        filename="test.pdf",
        blob_path="/blobs/test.pdf",
        doc_type="PO",
        doc_number="PO-DEL",
        party_name="Vendor Y",
    )
    data = {
        "doc_type": "PO",
        "doc_number": "PO-DEL",
        "grand_total": 500.0,
        "line_items": [{"description": "Box", "total_amount": 500.0}],
    }
    emit_facts(att, data, db_session=session)
    stored = facts_for("po", "PO-DEL", clearance="exec", db_session=session, tenant_id=tenant_id)
    assert len(stored) == 1

    # Explicit hard delete
    deleted_count = delete_facts_for_source(att_id, session)
    assert deleted_count == 1
    session.flush()

    after_delete = facts_for("po", "PO-DEL", clearance="exec", db_session=session, tenant_id=tenant_id)
    assert len(after_delete) == 0


def test_extract_attachment_emits_facts(session: Session, monkeypatch):
    from services.attachment_extraction import extract_attachment
    from config import get_settings

    monkeypatch.setattr(get_settings(), "ENABLE_ATTACHMENT_FACTS", True, raising=False)
    monkeypatch.setattr(get_settings(), "ENABLE_ATTACHMENT_INSIGHTS", False, raising=False)

    # Mock OCR and extraction agent
    monkeypatch.setattr(
        "queue_worker.handlers._run_ocr",
        lambda *args, **kwargs: {"content": "dummy text"},
    )
    monkeypatch.setattr(
        "agents.extraction_agent.run_extraction_agent",
        lambda *args, **kwargs: {
            "doc_type": "PURCHASE_ORDER",
            "extracted_data": {
                "doc_type": "PURCHASE_ORDER",
                "doc_number": "PO-AUTO-1",
                "party_name": "Supplier ABC",
                "grand_total": 50000.0,
                "currency": "INR",
                "line_items": [{"description": "Item 1", "total_amount": 50000.0}],
            },
        },
    )
    # Mock indexer & matcher to be noops
    monkeypatch.setattr("services.attachment_extraction.index_attachment", lambda *a, **kw: None)
    monkeypatch.setattr("services.attachment_extraction.match_attachment", lambda *a, **kw: None)

    tenant_id = uuid4()
    att = ChatAttachment(
        id=uuid4(),
        tenant_id=tenant_id,
        session_id=uuid4(),
        filename="po_auto.pdf",
        blob_path="/blobs/po_auto.pdf",
    )
    db_att = extract_attachment(att, session)
    assert db_att.extraction_status == "EXTRACTED"

    # Verify fact row was emitted into DB
    facts = facts_for("po", "PO-AUTO-1", clearance="ops", db_session=session, tenant_id=tenant_id)
    assert len(facts) == 1
    assert facts[0].counterparty_id == "Supplier ABC"
    assert facts[0].figures["total_amount"] == 50000.0

