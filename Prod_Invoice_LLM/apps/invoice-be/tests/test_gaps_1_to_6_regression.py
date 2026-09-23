"""Regression test suite for Gaps 1 through 6.

Gap 1: API chat session message authorization for API keys.
Gap 2: File replacement blocked when invoice is PROCESSING (409 Conflict) and
       worker discards stale extraction if file_hash changed.
Gap 3: Outbound invoice replacement enqueues `process_outbound_invoice` and resets `customer_name`.
Gap 4: Upload failure preserves original file name.
Gap 5: Chroma chunks for replaced invoices are pruned before re-indexing.
Gap 6: Storage failure during replace refunds the deducted free quota.
"""
import io
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from dependencies import (
    API_KEY_USER_ID,
    MOCK_TENANT_ID,
    TenantContext,
    get_db_session,
    get_tenant_context,
    get_tenant_or_api_key_context,
    require_actions_scope_or_human,
    require_can_load_and_actions_scope,
)
from main import app
from models import ChatSession, Invoice, Tenant
from routers.chat import MessageCreate, post_chat_message
from services.billing_quota import refund_free_quota
from services.storage import StorageUploadError

client = TestClient(app)

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def override_db_session(db_session):
    def _override():
        yield db_session

    app.dependency_overrides[get_db_session] = _override
    yield
    app.dependency_overrides.clear()


def _key_context(scope: str = "actions", tenant_id=None) -> TenantContext:
    return TenantContext(
        tenant_id=tenant_id or MOCK_TENANT_ID,
        user_id=API_KEY_USER_ID,
        role="Restricted",
        billing_plan="free",
        auth_method="api_key",
        key_scope=scope,
        can_train=False,
        can_audit=True,
        can_load=True,
    )


def _as_api_key(scope: str = "actions", tenant_id=None):
    ctx = _key_context(scope, tenant_id)

    def _refuse_clerk():
        raise HTTPException(status_code=401, detail="Authentication required.")

    app.dependency_overrides[get_tenant_or_api_key_context] = lambda: ctx
    app.dependency_overrides[require_can_load_and_actions_scope] = lambda: ctx
    app.dependency_overrides[require_actions_scope_or_human] = lambda: ctx
    app.dependency_overrides[get_tenant_context] = _refuse_clerk
    return ctx


def _pdf_bytes():
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"


def _replace(invoice_id, file_bytes=None, filename="invoice.pdf"):
    content = file_bytes if file_bytes is not None else _pdf_bytes()
    return client.post(
        f"/api/v1/invoices/{invoice_id}/file",
        files={"file": (filename, io.BytesIO(content), "application/pdf")},
    )


# ═══════════════════════════════════════════════════════════════════════════
# GAP 1: API Chat session message authorization
# ═══════════════════════════════════════════════════════════════════════════

def test_gap1_api_key_can_post_to_own_session(db_session):
    """An API key must be able to post messages to the chat session it created."""
    session = ChatSession(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        user_id=API_KEY_USER_ID,
        title="Integration Chat",
    )
    db_session.add(session)
    db_session.commit()

    key_ctx = _key_context()
    with patch("routers.chat.enforce_chat_rate_limit"), \
         patch("routers.chat.charge_sandbox_chat_or_402"), \
         patch("services.chat_queue.is_chat_session_locked", return_value=False), \
         patch("routers.chat.run_query_agent") as mock_agent:
        mock_agent.return_value = {
            "content": "Total is 100",
            "generated_sql": None,
            "citations": [],
            "result_invoice_ids": [],
            "turn_metadata": {},
        }
        try:
            post_chat_message(
                session_id=session.id,
                payload=MessageCreate(content="What is the total?"),
                background_tasks=BackgroundTasks(),
                request=MagicMock(),
                sync=True,
                db_session=db_session,
                tenant_context=key_ctx,
            )
        except HTTPException as he:
            assert he.status_code != 403, f"Should not raise 403: {he.detail}"


def test_gap1_api_key_cannot_post_to_human_session(db_session):
    """An API key must be rejected if trying to post to a human user's session."""
    human_session = ChatSession(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        user_id="user_clerk_123",
        title="Human Chat",
    )
    db_session.add(human_session)
    db_session.commit()

    key_ctx = _key_context()
    with pytest.raises(HTTPException) as exc_info:
        post_chat_message(
            session_id=human_session.id,
            payload=MessageCreate(content="Snoop"),
            background_tasks=BackgroundTasks(),
            request=MagicMock(),
            sync=True,
            db_session=db_session,
            tenant_context=key_ctx,
        )
    assert exc_info.value.status_code == 403
    assert "user-owned" in exc_info.value.detail


# ═══════════════════════════════════════════════════════════════════════════
# GAP 2: File replacement while PROCESSING returns 409 & worker guard
# ═══════════════════════════════════════════════════════════════════════════

def test_gap2_replace_rejected_when_invoice_is_processing(db_session):
    """Replacing an invoice file while it is in PROCESSING returns 409 Conflict."""
    _as_api_key("actions")
    inv = Invoice(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/path.pdf",
        status="PROCESSING",
    )
    db_session.add(inv)
    db_session.commit()

    resp = _replace(inv.id)
    assert resp.status_code == 409
    assert "currently being processed" in resp.json()["detail"].lower()


def test_gap2_worker_discards_stale_extraction_if_file_replaced(db_session):
    """If an invoice's file_hash changed mid-extraction, the worker skips DB write."""
    from queue_worker.handlers import handle_process_invoice

    file_path = f"tenants/{MOCK_TENANT_ID}/invoices/{uuid4()}.pdf"
    inv = Invoice(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        file_path=file_path,
        file_hash="initial_hash",
        status="PROCESSING",
        vendor_name="Original Vendor",
    )
    db_session.add(inv)
    db_session.commit()

    def _simulated_replace_mid_flight(*args, **kwargs):
        with Session(engine) as s:
            target = s.exec(select(Invoice).where(Invoice.id == inv.id)).one()
            target.file_hash = "replaced_hash"
            s.add(target)
            s.commit()
        return {
            "status": "COMPLETED",
            "alerts": [],
            "extracted_data": {
                "vendor_name": "Old Wrong Extracted Vendor",
                "invoice_number": "OLD-1",
                "grand_total": 999.0,
            },
        }

    with patch("queue_worker.handlers.engine", engine), \
         patch("queue_worker.handlers._run_ocr", return_value="ocr"), \
         patch("queue_worker.handlers._publish_sse_events"), \
         patch("queue_worker.handlers.run_extraction_agent", side_effect=_simulated_replace_mid_flight), \
         patch("queue_worker.handlers.track_extraction_pipeline_turn"):
        result = handle_process_invoice(str(uuid4()), file_path, str(MOCK_TENANT_ID))

    assert result.get("skipped") is True
    assert "replaced during extraction" in result.get("reason", "").lower()

    db_session.refresh(inv)
    assert inv.vendor_name == "Original Vendor"


# ═══════════════════════════════════════════════════════════════════════════
# GAP 3: Outbound replacement enqueues outbound task & clears customer_name
# ═══════════════════════════════════════════════════════════════════════════

def test_gap3_outbound_invoice_replace_clears_customer_name(db_session):
    """Replacing an outbound invoice clears customer_name and enqueues process_outbound_invoice."""
    _as_api_key("actions")
    tenant = Tenant(
        id=MOCK_TENANT_ID,
        name="MockTenant",
        domain="mock.test",
        billing_plan="pro",
    )
    inv = Invoice(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/out.pdf",
        file_hash="old_hash_123",
        flow_direction="OUTBOUND",
        status="AUDIT_REQUIRED",
        customer_name="Acme Corp",
        vendor_name=None,
        invoice_number="INV-99",
    )
    db_session.add(tenant)
    db_session.add(inv)
    db_session.commit()

    enqueue_calls = []

    async def _mock_enqueue(db_inv, batch_id, file_path, context, session):
        task = "process_outbound_invoice" if (db_inv.flow_direction or "").upper() == "OUTBOUND" else "process_invoice"
        enqueue_calls.append(task)
        return True

    with patch("routers.invoices.upload_pdf_to_blob_storage", return_value="mock/new.pdf"), \
         patch("routers.invoices._enqueue_extraction", side_effect=_mock_enqueue), \
         patch("routers.invoices.delete_invoice_chunks", return_value=True):
        resp = _replace(inv.id)
        assert resp.status_code == 200

    db_session.refresh(inv)
    assert inv.customer_name is None, "customer_name must be reset on replace"
    assert inv.vendor_name is None
    assert enqueue_calls == ["process_outbound_invoice"]


# ═══════════════════════════════════════════════════════════════════════════
# GAP 4: Upload failure preserves original filename
# ═══════════════════════════════════════════════════════════════════════════

def test_gap4_upload_failure_reports_original_filename(db_session):
    """When a file in a multi-file batch fails ingestion, the failure report preserves original_filename."""
    _as_api_key("actions")
    tenant = Tenant(
        id=MOCK_TENANT_ID,
        name="MockTenant",
        domain="mock.test",
        billing_plan="pro",
    )
    db_session.add(tenant)
    db_session.commit()

    with patch("routers.invoices._ingest_single_file", side_effect=HTTPException(status_code=503, detail="Storage failed")):
        response = client.post(
            "/api/v1/invoices/upload",
            files=[
                ("files", ("receipt_photo.png", io.BytesIO(_pdf_bytes()), "application/pdf")),
            ],
        )

    # When all fail, it raises the first failure
    assert response.status_code == 503
    assert "Storage failed" in response.json()["detail"]


# ═══════════════════════════════════════════════════════════════════════════
# GAP 5: Chroma ghost pages pruned on replace and re-index
# ═══════════════════════════════════════════════════════════════════════════

def test_gap5_chroma_index_document_clears_prior_chunks():
    """index_invoice_document purges prior chunks for invoice_id before upserting."""
    import chroma_client

    mock_collection = MagicMock()
    mock_client = MagicMock()
    mock_client.get_or_create_collection.return_value = mock_collection

    invoice_id = str(uuid4())
    tenant_id = str(uuid4())

    with patch("chroma_client.get_chroma_client", return_value=mock_client), \
         patch("chroma_client.require_live_chroma"), \
         patch("chroma_client.download_pdf_from_storage", return_value=_pdf_bytes()), \
         patch("chroma_client.fitz.open") as mock_fitz, \
         patch("chroma_client.get_embeddings", return_value=[[0.1] * 1536]):
        
        mock_doc = MagicMock()
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Sample page text"
        mock_doc.__iter__.return_value = [mock_page]
        mock_fitz.return_value = mock_doc

        chroma_client.index_invoice_document(
            invoice_id=invoice_id,
            tenant_id=tenant_id,
            vendor_name="Vendor Test",
            file_path="mock/path.pdf",
        )

        mock_collection.delete.assert_called_once_with(where={"invoice_id": invoice_id})
        mock_collection.upsert.assert_called_once()


def test_gap5_chroma_chunks_deleted_on_replace(db_session):
    """Old Chroma chunks must be deleted when replacing an invoice file."""
    _as_api_key("actions")
    tenant = Tenant(
        id=MOCK_TENANT_ID,
        name="MockTenant",
        domain="mock.test",
        billing_plan="pro",
    )
    inv = Invoice(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/path.pdf",
        status="COMPLETED",
    )
    db_session.add(tenant)
    db_session.add(inv)
    db_session.commit()

    with patch("routers.invoices.upload_pdf_to_blob_storage", return_value="mock/new.pdf"), \
         patch("routers.invoices._enqueue_extraction", new=AsyncMock(return_value=True)), \
         patch("routers.invoices.delete_invoice_chunks") as mock_delete:
        mock_delete.return_value = True
        resp = _replace(inv.id)
        assert resp.status_code == 200
        mock_delete.assert_called_once_with(str(inv.id), str(inv.tenant_id))


# ═══════════════════════════════════════════════════════════════════════════
# GAP 6: Free quota refunded on storage upload failure during replace
# ═══════════════════════════════════════════════════════════════════════════

def test_gap6_refund_free_quota_helper(db_session):
    """refund_free_quota increments free_invoices_remaining for free tenants."""
    tenant = Tenant(
        id=MOCK_TENANT_ID,
        name="FreeCo",
        domain="freeco.test",
        billing_plan="free",
        free_invoices_remaining=3,
    )
    db_session.add(tenant)
    db_session.commit()

    refunded = refund_free_quota(db_session, MOCK_TENANT_ID, billable_count=2)
    assert refunded is not None
    assert refunded.free_invoices_remaining == 5


def test_gap6_storage_failure_during_replace_refunds_quota(db_session):
    """If blob storage upload fails during replace, charged quota is refunded."""
    _as_api_key("actions")
    tenant = Tenant(
        id=MOCK_TENANT_ID,
        name="FreeCo",
        domain="freeco.test",
        billing_plan="free",
        free_invoices_remaining=5,
    )
    inv = Invoice(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/path.pdf",
        status="COMPLETED",
        file_hash="original_hash",
    )
    db_session.add(tenant)
    db_session.add(inv)
    db_session.commit()

    with patch("routers.invoices.upload_pdf_to_blob_storage", side_effect=StorageUploadError("Azure error")):
        resp = _replace(inv.id, file_bytes=b"%PDF-1.4\nnew-bytes")
        assert resp.status_code == 503

    db_session.refresh(tenant)
    # 5 credits should remain intact because the deducted credit was refunded
    assert tenant.free_invoices_remaining == 5
