"""BE Gap 684 — extraction records carry model, prompt and schema provenance.

Tests proving:
1. `_DIRECTION_PROFILES` defines explicit `prompt_version` and `schema_version` for all profiles.
2. `ExtractionState` declares all four provenance fields.
3. `extract_node` records `model_deployment`, `prompt_version`, `schema_version`, and `llm_duration_ms`.
4. `run_extraction_agent` returns all four provenance fields on completion and on token-limit aborts.
5. `queue_worker/handlers.py` persists provenance onto `Invoice` rows.
6. `queue_worker/handlers.py` persists pass 2 provenance when a vendor template triggers a re-run.
7. `queue_worker/handlers.py::_persist_non_invoice_document` persists provenance onto `Document` rows.
8. `queue_worker/outbound_handlers.py` persists provenance onto outbound `Invoice` rows.
9. Migration `a1b2c3d4e684` is the linear Alembic head with down_revision `e6f7a8b9c0d1`.
10. `Invoice` and `Document` models define nullable provenance columns with None defaults.
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


# ---------------------------------------------------------------------------
# In-Memory DB fixture for worker tests
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


@pytest.fixture(name="db_session")
def db_session_fixture(db_engine):
    with Session(db_engine) as session:
        yield session


# ---------------------------------------------------------------------------
# Alembic Migration Linearity & Structure Tests
# ---------------------------------------------------------------------------
def test_alembic_gap684_is_linear_head():
    """Verify migration a1b2c3d4e684 exists, descends from e6f7a8b9c0d1, and is ancestor of current head."""
    script = ScriptDirectory.from_config(Config("alembic.ini"))
    heads = script.get_heads()
    assert len(heads) == 1, f"Expected 1 linear head, got: {heads}"

    rev = script.get_revision("a1b2c3d4e684")
    assert rev is not None
    assert rev.down_revision == "e6f7a8b9c0d1"

    ancestry = {r.revision for r in script.iterate_revisions(heads[0], "base")}
    assert "a1b2c3d4e684" in ancestry
    assert "e6f7a8b9c0d1" in ancestry


def test_models_provenance_columns_nullable_by_default():
    """Invoice and Document must have model_deployment, prompt_version, schema_version, llm_duration_ms defaulting to None."""
    inv = Invoice(file_path="dummy.pdf", tenant_id=uuid4())
    assert inv.model_deployment is None
    assert inv.prompt_version is None
    assert inv.schema_version is None
    assert inv.llm_duration_ms is None

    doc = Document(file_path="dummy.pdf", tenant_id=uuid4())
    assert doc.model_deployment is None
    assert doc.prompt_version is None
    assert doc.schema_version is None
    assert doc.llm_duration_ms is None


# ---------------------------------------------------------------------------
# Unit Tests: Profiles, ExtractionState, extract_node, run_extraction_agent
# ---------------------------------------------------------------------------
def test_direction_profiles_have_provenance_versions():
    """Every profile in _DIRECTION_PROFILES must define non-empty prompt_version and schema_version."""
    expected_profiles = {
        "INBOUND": ("inbound_v2", "invoice_v2"),
        "OUTBOUND": ("outbound_v2", "outbound_invoice_v2"),
        "REFERENCE": ("reference_v2", "reference_doc_v1"),
        "GENERIC": ("generic_v2", "generic_doc_v2"),
    }
    for key, (exp_prompt, exp_schema) in expected_profiles.items():
        assert key in ea._DIRECTION_PROFILES, f"Missing profile {key}"
        profile = ea._DIRECTION_PROFILES[key]
        assert profile.prompt_version == exp_prompt
        assert profile.schema_version == exp_schema


def test_extraction_state_declares_provenance_keys():
    """ExtractionState TypedDict must declare the 4 provenance fields."""
    annotations = ea.ExtractionState.__annotations__
    for field in ("model_deployment", "prompt_version", "schema_version", "llm_duration_ms"):
        assert field in annotations, f"{field} not annotated in ExtractionState"


def test_extract_node_records_provenance():
    """extract_node must return model_deployment, prompt_version, schema_version, and llm_duration_ms."""
    state = {
        "file_path": "tenants/test/inbound/test.pdf",
        "ocr_text": "INVOICE #101\nAcme Corp\nTotal: $100.00",
        "images": [],
        "extracted_data": None,
        "alerts": [],
        "status": "PROCESSING",
        "rules": None,
        "complexity": "STANDARD",
        "ocr_result": None,
        "retry_count": 0,
        "max_retries": 2,
        "feedback": [],
        "dynamic_qa_context": None,
        "flow_direction": "INBOUND",
        "tenant_id": "00000000-0000-0000-0000-000000000001",
        "doc_type": None,
        "doc_type_evidence": None,
        "doc_type_confidence": None,
        "doc_attributes": None,
        "model_deployment": None,
        "prompt_version": None,
        "schema_version": None,
        "llm_duration_ms": None,
    }

    mock_llm = MagicMock()
    mock_llm.model_name = "gpt-5-mini-test"
    mock_structured = MagicMock()
    mock_llm.with_structured_output.return_value = mock_structured

    dummy_result = MagicMock()
    dummy_result.dict.return_value = {
        "vendor_name": "Acme Corp",
        "grand_total": 100.0,
        "subtotal": 100.0,
        "tax_amount": 0.0,
    }
    mock_structured.invoke.return_value = dummy_result

    with patch("agents.extraction_agent.get_llm", return_value=mock_llm):
        result = ea.extract_node(state)

    assert result["model_deployment"] == "gpt-5-mini-test"
    assert result["prompt_version"] == "inbound_v2"
    assert result["schema_version"] == "invoice_v2"
    assert isinstance(result["llm_duration_ms"], int)
    assert result["llm_duration_ms"] >= 0


def test_run_extraction_agent_returns_provenance_keys():
    """run_extraction_agent return dict must carry the 4 provenance keys."""
    mock_final_state = {
        "status": "COMPLETED",
        "alerts": [],
        "extracted_data": {"vendor_name": "Acme Corp"},
        "doc_type": None,
        "doc_type_evidence": None,
        "doc_type_confidence": None,
        "doc_attributes": None,
        "model_deployment": "gpt-5-mini-test",
        "prompt_version": "inbound_v1",
        "schema_version": "invoice_v1",
        "llm_duration_ms": 1500,
    }

    mock_graph = MagicMock()
    mock_graph.invoke.return_value = mock_final_state

    with patch("agents.extraction_agent.resolve_extraction_graph", return_value=mock_graph), \
         patch("agents.extraction_agent.document_to_base64_images", return_value=[]):
        res = ea.run_extraction_agent(
            file_path="dummy.pdf",
            ocr_text="dummy text",
            tenant_id=str(uuid4()),
        )

    assert res["model_deployment"] == "gpt-5-mini-test"
    assert res["prompt_version"] == "inbound_v1"
    assert res["schema_version"] == "invoice_v1"
    assert res["llm_duration_ms"] == 1500


def test_run_extraction_agent_token_limit_exceeded_returns_provenance_keys():
    """When token guardrail triggers early return, provenance keys are present with None values."""
    with patch("agents.extraction_agent.check_token_guardrails", return_value=(False, 50000, 16384)):
        res = ea.run_extraction_agent(
            file_path="huge.pdf",
            ocr_text="huge text...",
            tenant_id=str(uuid4()),
        )

    assert res["status"] == "AUDIT_REQUIRED"
    assert res["model_deployment"] is None
    assert res["prompt_version"] is None
    assert res["schema_version"] is None
    assert res["llm_duration_ms"] is None


# ---------------------------------------------------------------------------
# Database & Worker Persistence Tests
# ---------------------------------------------------------------------------
def test_inbound_invoice_provenance_persistence(db_engine):
    """handle_process_invoice must persist provenance fields onto the Invoice row."""
    tenant_id = uuid4()
    invoice_id = uuid4()
    batch_id = uuid4()
    file_path = f"tenants/{tenant_id}/inbound/{batch_id}/inv_test.pdf"

    with Session(db_engine) as session:
        invoice = Invoice(
            id=invoice_id,
            tenant_id=tenant_id,
            batch_id=batch_id,
            file_path=file_path,
            status="PROCESSING",
            flow_direction="INBOUND",
        )
        session.add(invoice)
        session.commit()

    agent_result = {
        "status": "COMPLETED",
        "alerts": [],
        "extracted_data": {
            "vendor_name": "Provenance Vendor Inc",
            "invoice_number": "INV-100",
            "grand_total": 450.0,
            "subtotal": 450.0,
            "tax_amount": 0.0,
        },
        "doc_type": "INVOICE",
        "doc_type_evidence": "TAX INVOICE",
        "doc_attributes": None,
        "doc_type_confidence": 0.99,
        "model_deployment": "gpt-5-mini",
        "prompt_version": "inbound_v1",
        "schema_version": "invoice_v1",
        "llm_duration_ms": 2345,
    }

    with patch.object(handlers, "engine", db_engine), \
         patch.object(handlers, "_run_ocr", return_value={"content": "TAX INVOICE"}), \
         patch.object(handlers, "run_extraction_agent", return_value=agent_result), \
         patch.object(handlers, "_publish_sse_events"), \
         patch("chroma_client.index_invoice_document", return_value=0):
        handlers.handle_process_invoice(str(batch_id), file_path, str(tenant_id))

    with Session(db_engine) as session:
        saved_inv = session.get(Invoice, invoice_id)
        assert saved_inv is not None
        assert saved_inv.model_deployment == "gpt-5-mini"
        assert saved_inv.prompt_version == "inbound_v1"
        assert saved_inv.schema_version == "invoice_v1"
        assert saved_inv.llm_duration_ms == 2345


def test_two_pass_extraction_persists_pass2_provenance(db_engine):
    """When vendor-specific template triggers Stage 2 re-run, pass 2 provenance must be persisted."""
    tenant_id = uuid4()
    invoice_id = uuid4()
    batch_id = uuid4()
    file_path = f"tenants/{tenant_id}/inbound/{batch_id}/pass2_test.pdf"

    with Session(db_engine) as session:
        invoice = Invoice(
            id=invoice_id,
            tenant_id=tenant_id,
            batch_id=batch_id,
            file_path=file_path,
            status="PROCESSING",
            flow_direction="INBOUND",
        )
        session.add(invoice)
        session.commit()

    pass1_result = {
        "status": "AUDIT_REQUIRED",
        "alerts": [],
        "extracted_data": {
            "vendor_name": "Trained Vendor Co",
            "invoice_number": "P2-1",
            "grand_total": 999.0,
        },
        "doc_type": "INVOICE",
        "doc_type_evidence": "INVOICE",
        "doc_attributes": None,
        "doc_type_confidence": 0.95,
        "model_deployment": "gpt-5-mini-pass1",
        "prompt_version": "inbound_v1",
        "schema_version": "invoice_v1",
        "llm_duration_ms": 1100,
    }

    pass2_result = {
        "status": "COMPLETED",
        "alerts": [],
        "extracted_data": {
            "vendor_name": "Trained Vendor Co",
            "invoice_number": "P2-1",
            "grand_total": 999.0,
            "subtotal": 999.0,
        },
        "doc_type": "INVOICE",
        "doc_type_evidence": "INVOICE",
        "doc_attributes": None,
        "doc_type_confidence": 0.98,
        "model_deployment": "gpt-5-mini-pass2",
        "prompt_version": "inbound_v1",
        "schema_version": "invoice_v1",
        "llm_duration_ms": 1950,
    }

    with patch.object(handlers, "engine", db_engine), \
         patch.object(handlers, "_run_ocr", return_value={"content": "INVOICE"}), \
         patch.object(handlers, "_get_template_rules", return_value=[{"rule": "mock"}]), \
         patch.object(handlers, "run_extraction_agent", side_effect=[pass1_result, pass2_result]), \
         patch.object(handlers, "_publish_sse_events"), \
         patch("chroma_client.index_invoice_document", return_value=0):
        handlers.handle_process_invoice(str(batch_id), file_path, str(tenant_id))

    with Session(db_engine) as session:
        saved_inv = session.get(Invoice, invoice_id)
        assert saved_inv is not None
        # Must reflect pass 2 provenance, NOT pass 1
        assert saved_inv.model_deployment == "gpt-5-mini-pass2"
        assert saved_inv.prompt_version == "inbound_v1"
        assert saved_inv.schema_version == "invoice_v1"
        assert saved_inv.llm_duration_ms == 1950


def test_non_invoice_document_provenance_persistence(db_engine):
    """When a document routes to documents table, provenance must be stored on the Document row."""
    tenant_id = uuid4()
    invoice_id = uuid4()
    batch_id = uuid4()
    file_path = f"tenants/{tenant_id}/inbound/{batch_id}/dn_test.pdf"

    with Session(db_engine) as session:
        invoice = Invoice(
            id=invoice_id,
            tenant_id=tenant_id,
            batch_id=batch_id,
            file_path=file_path,
            status="PROCESSING",
            flow_direction="INBOUND",
        )
        session.add(invoice)
        session.commit()

    agent_result = {
        "status": "EXTRACTED",
        "alerts": [],
        "extracted_data": {
            "party_name": "Steel Supplies Ltd",
            "doc_number": "DN-500",
            "items": [{"description": "Steel Rod", "quantity": 10.0}],
        },
        "doc_type": "DELIVERY_NOTE",
        "doc_type_evidence": "DELIVERY CHALLAN",
        "doc_attributes": None,
        "doc_type_confidence": 0.99,
        "model_deployment": "gpt-5.6-luna",
        "prompt_version": "generic_v1",
        "schema_version": "generic_doc_v1",
        "llm_duration_ms": 3100,
    }

    with patch.object(handlers, "engine", db_engine), \
         patch.object(handlers, "_run_ocr", return_value={"content": "DELIVERY CHALLAN"}), \
         patch.object(handlers, "run_extraction_agent", return_value=agent_result), \
         patch.object(handlers, "_publish_sse_events"), \
         patch("chroma_client.index_document_chunks", return_value=0):
        handlers.handle_process_invoice(str(batch_id), file_path, str(tenant_id))

    with Session(db_engine) as session:
        # Invoice placeholder should be deleted
        assert session.get(Invoice, invoice_id) is None

        # Document row should exist with provenance populated
        docs = session.exec(select(Document).where(Document.tenant_id == tenant_id)).all()
        assert len(docs) == 1
        doc = docs[0]
        assert doc.doc_type == "DELIVERY_NOTE"
        assert doc.model_deployment == "gpt-5.6-luna"
        assert doc.prompt_version == "generic_v1"
        assert doc.schema_version == "generic_doc_v1"
        assert doc.llm_duration_ms == 3100


def test_outbound_invoice_provenance_persistence(db_engine):
    """handle_process_outbound_invoice must persist provenance fields onto the Outbound Invoice row."""
    tenant_id = uuid4()
    invoice_id = uuid4()
    batch_id = uuid4()
    file_path = f"tenants/{tenant_id}/outbound/{batch_id}/ar_test.pdf"

    with Session(db_engine) as session:
        invoice = Invoice(
            id=invoice_id,
            tenant_id=tenant_id,
            batch_id=batch_id,
            file_path=file_path,
            status="PROCESSING",
            flow_direction="OUTBOUND",
        )
        session.add(invoice)
        session.commit()

    agent_result = {
        "status": "VERIFIED",
        "alerts": [],
        "extracted_data": {
            "customer_name": "Outbound Customer Corp",
            "invoice_number": "AR-900",
            "grand_total": 1250.0,
            "subtotal": 1250.0,
            "tax_amount": 0.0,
        },
        "doc_type": None,
        "doc_type_evidence": None,
        "doc_attributes": None,
        "doc_type_confidence": None,
        "model_deployment": "gpt-5-mini",
        "prompt_version": "outbound_v1",
        "schema_version": "outbound_invoice_v1",
        "llm_duration_ms": 1780,
    }

    with patch.object(outbound_handlers, "engine", db_engine), \
         patch.object(outbound_handlers, "_run_ocr", return_value={"content": "INVOICE"}), \
         patch.object(outbound_handlers, "run_outbound_extraction_agent", return_value=agent_result), \
         patch.object(outbound_handlers, "_publish_sse_events"), \
         patch("chroma_client.index_invoice_document", return_value=0):
        outbound_handlers.handle_process_outbound_invoice(str(batch_id), file_path, str(tenant_id))

    with Session(db_engine) as session:
        saved_inv = session.get(Invoice, invoice_id)
        assert saved_inv is not None
        assert saved_inv.model_deployment == "gpt-5-mini"
        assert saved_inv.prompt_version == "outbound_v1"
        assert saved_inv.schema_version == "outbound_invoice_v1"
        assert saved_inv.llm_duration_ms == 1780
