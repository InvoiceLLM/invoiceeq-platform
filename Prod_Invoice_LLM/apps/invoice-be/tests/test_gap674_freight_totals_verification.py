"""BE Gap 674: Freight term in totals verification, extraction schemas, and persistence.

Validates:
1. Alembic migration b2c3d4e5f674 is the linear head with down_revision a1b2c3d4e684.
2. Invoice and Document models define nullable freight_amount defaulting to None.
3. InvoiceExtractionSchema, OutboundInvoiceExtractionSchema, GenericDocumentSchema define freight_amount,
   while ReferenceDocExtractionSchema remains untouched.
4. _DIRECTION_PROFILES schema versions bumped to v2 (invoice_v2, outbound_invoice_v2, generic_doc_v2).
5. verify_totals_math reconciles freight in totals block and respects double-counting guardrail.
6. verify_node passes freight_amount to verify_totals_math.
7. Worker persistence handles freight_amount across inbound, outbound, and non-invoice documents.
8. correction_recheck and rule_impact include freight_amount.
"""
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import agents.extraction_agent as ea
from models import Document, Invoice, Tenant
from queue_worker import handlers, outbound_handlers
from services.rule_impact import _replay_invoice
from utils.correction_recheck import MONEY_FIELDS, _math_alerts
from utils.verification_tools import verify_totals_math


# ---------------------------------------------------------------------------
# Database fixture
# ---------------------------------------------------------------------------
@pytest.fixture(name="db_engine")
def db_engine_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


# ---------------------------------------------------------------------------
# 1. Alembic Migration Linearity & Structure Tests
# ---------------------------------------------------------------------------
def test_alembic_gap674_is_linear_head():
    """b2c3d4e5f674 must be the single linear head and descend from a1b2c3d4e684."""
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_heads()
    assert len(heads) == 1, f"Expected 1 linear head, got: {heads}"
    assert heads[0] == "b2c3d4e5f674", f"Expected head b2c3d4e5f674, got: {heads[0]}"

    rev = script.get_revision("b2c3d4e5f674")
    assert rev is not None
    assert rev.down_revision == "a1b2c3d4e684"

    ancestry = {r.revision for r in script.iterate_revisions(heads[0], "base")}
    assert "a1b2c3d4e684" in ancestry
    assert "e6f7a8b9c0d1" in ancestry


# ---------------------------------------------------------------------------
# 2. Model Definitions
# ---------------------------------------------------------------------------
def test_models_freight_amount_column():
    """Invoice and Document must have nullable freight_amount defaulting to None."""
    inv = Invoice(file_path="dummy.pdf", tenant_id=uuid4())
    assert hasattr(inv, "freight_amount")
    assert inv.freight_amount is None

    doc = Document(file_path="dummy.pdf", tenant_id=uuid4())
    assert hasattr(doc, "freight_amount")
    assert doc.freight_amount is None


# ---------------------------------------------------------------------------
# 3. Extraction Schemas & Profile Versions
# ---------------------------------------------------------------------------
def test_schemas_freight_amount():
    """Invoice, Outbound, and Generic schemas carry freight_amount; Reference does not."""
    assert "freight_amount" in ea.InvoiceExtractionSchema.model_fields
    assert "freight_amount" in ea.OutboundInvoiceExtractionSchema.model_fields
    assert "freight_amount" in ea.GenericDocumentSchema.model_fields
    assert "freight_amount" not in ea.ReferenceDocExtractionSchema.model_fields


def test_schema_versions_bumped():
    """Inbound, Outbound, Generic schema_versions bumped to v2; Reference stays v1."""
    assert ea._DIRECTION_PROFILES["INBOUND"].schema_version == "invoice_v2"
    assert ea._DIRECTION_PROFILES["OUTBOUND"].schema_version == "outbound_invoice_v2"
    assert ea._DIRECTION_PROFILES["GENERIC"].schema_version == "generic_doc_v2"
    assert ea._DIRECTION_PROFILES["REFERENCE"].schema_version == "reference_doc_v1"


# ---------------------------------------------------------------------------
# 4. verify_totals_math Arithmetic & Guardrails
# ---------------------------------------------------------------------------
def test_verify_totals_math_without_freight():
    """Standard reconciliation without freight continues to work."""
    assert verify_totals_math(100.0, 10.0, 110.0) is None
    mismatch = verify_totals_math(100.0, 10.0, 115.0)
    assert mismatch is not None
    assert mismatch["type"] == "tax_mismatch"


def test_verify_totals_math_with_freight_reconciles():
    """Freight in totals block outside subtotal reconciles cleanly (e.g. US-PI-01 fixture)."""
    # Without freight, 5700.0 + 0 != 6010.0 -> mismatch
    alert = verify_totals_math(5700.0, 0.0, 6010.0)
    assert alert is not None
    assert alert["type"] == "tax_mismatch"

    # With freight 310.0, 5700.0 + 0 + 310.0 == 6010.0 -> passes
    assert verify_totals_math(5700.0, 0.0, 6010.0, freight_amount=310.0) is None


def test_verify_totals_math_guardrail_line_item_not_double_counted():
    """Guardrail: If freight was already included in subtotal, it must not cause false mismatch."""
    # Subtotal is 6010.0 (already includes freight), grand total is 6010.0
    # Even if freight_amount=310.0 is extracted, candidates without freight pass!
    assert verify_totals_math(6010.0, 0.0, 6010.0, freight_amount=310.0) is None


def test_verify_totals_math_genuine_mismatch_includes_freight_in_message():
    """Genuine arithmetic error reports mismatch with Freight in message."""
    alert = verify_totals_math(5700.0, 0.0, 6500.0, freight_amount=310.0)
    assert alert is not None
    assert alert["type"] == "tax_mismatch"
    assert "Freight (310.00)" in alert["message"]


def test_verify_totals_math_freight_with_discounts_and_round_off():
    """Verify freight combined with pre-discount, tax, and round-off."""
    # pre-discount: subtotal 1000 - discount 100 + tax 50 + freight 25 + round_off 0.50 = 975.50
    assert verify_totals_math(
        subtotal=1000.0,
        tax_amount=50.0,
        grand_total=975.50,
        discount_amount=100.0,
        round_off=0.50,
        freight_amount=25.0,
    ) is None


# ---------------------------------------------------------------------------
# 5. verify_node integration
# ---------------------------------------------------------------------------
def test_verify_node_passes_freight_amount():
    """verify_node extracts freight_amount from state and passes it to verify_totals_math."""
    state = {
        "extracted_data": {
            "vendor_name": "Test Vendor",
            "invoice_number": "INV-FR-1",
            "subtotal": 5700.0,
            "tax_amount": 0.0,
            "freight_amount": 310.0,
            "grand_total": 6010.0,
            "items": [
                {"description": "Item 1", "amount": 5700.0, "quantity": 1, "unit_price": 5700.0}
            ],
        },
        "ocr_text": "Subtotal: $5700.00 Freight: $310.00 Total: $6010.00",
        "doc_type": "INVOICE",
        "flow_direction": "INBOUND",
    }

    result = ea.verify_node(state)
    assert result["status"] == "COMPLETED"
    tax_alerts = [a for a in result["alerts"] if a.get("type") == "tax_mismatch"]
    assert len(tax_alerts) == 0


# ---------------------------------------------------------------------------
# 6. Worker Persistence
# ---------------------------------------------------------------------------
def test_inbound_invoice_persists_freight_amount(db_engine):
    """handle_process_invoice persists freight_amount onto Invoice."""
    tenant_id = uuid4()
    invoice_id = uuid4()
    batch_id = uuid4()
    file_path = f"tenants/{tenant_id}/inbound/{batch_id}/fr_test.pdf"

    with Session(db_engine) as session:
        session.add(
            Invoice(
                id=invoice_id,
                tenant_id=tenant_id,
                batch_id=batch_id,
                file_path=file_path,
                status="PROCESSING",
                flow_direction="INBOUND",
            )
        )
        session.commit()

    agent_result = {
        "status": "COMPLETED",
        "alerts": [],
        "extracted_data": {
            "vendor_name": "Freight Shipper Co",
            "invoice_number": "FR-100",
            "subtotal": 1000.0,
            "freight_amount": 50.0,
            "tax_amount": 0.0,
            "grand_total": 1050.0,
        },
        "doc_type": "INVOICE",
        "doc_type_evidence": "INVOICE",
        "doc_attributes": None,
        "doc_type_confidence": 0.99,
        "model_deployment": "gpt-5-mini",
        "prompt_version": "inbound_v2",
        "schema_version": "invoice_v2",
        "llm_duration_ms": 1000,
    }

    with patch.object(handlers, "engine", db_engine), \
         patch.object(handlers, "_run_ocr", return_value={"content": "INVOICE"}), \
         patch.object(handlers, "run_extraction_agent", return_value=agent_result), \
         patch.object(handlers, "_publish_sse_events"), \
         patch("chroma_client.index_invoice_document", return_value=0):
        handlers.handle_process_invoice(str(batch_id), file_path, str(tenant_id))

    with Session(db_engine) as session:
        inv = session.get(Invoice, invoice_id)
        assert inv is not None
        assert inv.freight_amount == 50.0


def test_non_invoice_document_persists_freight_amount(db_engine):
    """_persist_non_invoice_document persists freight_amount onto Document."""
    tenant_id = uuid4()
    invoice_id = uuid4()
    batch_id = uuid4()
    file_path = f"tenants/{tenant_id}/inbound/{batch_id}/po_fr_test.pdf"

    with Session(db_engine) as session:
        session.add(
            Invoice(
                id=invoice_id,
                tenant_id=tenant_id,
                batch_id=batch_id,
                file_path=file_path,
                status="PROCESSING",
                flow_direction="INBOUND",
            )
        )
        session.commit()

    agent_result = {
        "status": "EXTRACTED",
        "alerts": [],
        "extracted_data": {
            "party_name": "Supplier PO",
            "doc_number": "PO-99",
            "subtotal": 2000.0,
            "freight_amount": 120.0,
            "tax_amount": 0.0,
            "grand_total": 2120.0,
        },
        "doc_type": "PURCHASE_ORDER",
        "doc_type_evidence": "PURCHASE ORDER",
        "doc_attributes": None,
        "doc_type_confidence": 0.98,
        "model_deployment": "gpt-5-mini",
        "prompt_version": "generic_v2",
        "schema_version": "generic_doc_v2",
        "llm_duration_ms": 1200,
    }

    with patch.object(handlers, "engine", db_engine), \
         patch.object(handlers, "_run_ocr", return_value={"content": "PURCHASE ORDER"}), \
         patch.object(handlers, "run_extraction_agent", return_value=agent_result), \
         patch.object(handlers, "_publish_sse_events"), \
         patch("chroma_client.index_document_chunks", return_value=0):
        handlers.handle_process_invoice(str(batch_id), file_path, str(tenant_id))

    with Session(db_engine) as session:
        assert session.get(Invoice, invoice_id) is None
        docs = session.exec(select(Document).where(Document.tenant_id == tenant_id)).all()
        assert len(docs) == 1
        assert docs[0].freight_amount == 120.0


def test_outbound_invoice_persists_freight_amount(db_engine):
    """handle_process_outbound_invoice persists freight_amount onto Outbound Invoice."""
    tenant_id = uuid4()
    invoice_id = uuid4()
    batch_id = uuid4()
    file_path = f"tenants/{tenant_id}/outbound/{batch_id}/ar_fr_test.pdf"

    with Session(db_engine) as session:
        session.add(
            Invoice(
                id=invoice_id,
                tenant_id=tenant_id,
                batch_id=batch_id,
                file_path=file_path,
                status="PROCESSING",
                flow_direction="OUTBOUND",
            )
        )
        session.commit()

    agent_result = {
        "status": "VERIFIED",
        "alerts": [],
        "extracted_data": {
            "customer_name": "Outbound Freight Customer",
            "invoice_number": "AR-FR-5",
            "subtotal": 3000.0,
            "freight_amount": 200.0,
            "tax_amount": 0.0,
            "grand_total": 3200.0,
        },
        "doc_type": None,
        "doc_type_evidence": None,
        "doc_attributes": None,
        "doc_type_confidence": None,
        "model_deployment": "gpt-5-mini",
        "prompt_version": "outbound_v2",
        "schema_version": "outbound_invoice_v2",
        "llm_duration_ms": 1100,
    }

    with patch.object(outbound_handlers, "engine", db_engine), \
         patch.object(outbound_handlers, "_run_ocr", return_value={"content": "INVOICE"}), \
         patch.object(outbound_handlers, "run_outbound_extraction_agent", return_value=agent_result), \
         patch.object(outbound_handlers, "_publish_sse_events"), \
         patch("chroma_client.index_invoice_document", return_value=0):
        outbound_handlers.handle_process_outbound_invoice(str(batch_id), file_path, str(tenant_id))

    with Session(db_engine) as session:
        inv = session.get(Invoice, invoice_id)
        assert inv is not None
        assert inv.freight_amount == 200.0


# ---------------------------------------------------------------------------
# 7. Correction Recheck & Rule Impact
# ---------------------------------------------------------------------------
def test_correction_recheck_includes_freight_amount():
    """MONEY_FIELDS includes freight_amount and _math_alerts reconciles freight."""
    assert "freight_amount" in MONEY_FIELDS

    values_with_freight = {
        "items": [],
        "subtotal": 5700.0,
        "tax_amount": 0.0,
        "grand_total": 6010.0,
        "discount_amount": None,
        "discount_percent": None,
        "freight_amount": 310.0,
    }
    alerts = _math_alerts(values_with_freight, tolerances={}, doc_type="INVOICE")
    tax_alerts = [a for a in alerts if a.get("type") == "tax_mismatch"]
    assert len(tax_alerts) == 0


def test_rule_impact_passes_freight_amount():
    """_replay_invoice correctly reconciles an invoice with freight_amount."""
    tenant_id = uuid4()
    inv_with_freight = Invoice(
        id=uuid4(),
        tenant_id=tenant_id,
        file_path="test.pdf",
        subtotal=5700.0,
        tax_amount=0.0,
        freight_amount=310.0,
        grand_total=6010.0,
        status="COMPLETED",
        source_document_json={"SubTotal": {"value": 5700.0}},
    )
    fired, not_computable = _replay_invoice(inv_with_freight, tolerances={}, threshold=None)
    assert "tax_mismatch" not in fired

    inv_without_freight = Invoice(
        id=uuid4(),
        tenant_id=tenant_id,
        file_path="test.pdf",
        subtotal=5700.0,
        tax_amount=0.0,
        freight_amount=None,
        grand_total=6010.0,
        status="COMPLETED",
        source_document_json={"SubTotal": {"value": 5700.0}},
    )
    fired_mismatch, _ = _replay_invoice(inv_without_freight, tolerances={}, threshold=None)
    assert "tax_mismatch" in fired_mismatch
