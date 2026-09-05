"""Gap 192: invoice soft delete preserves AuditLog and hides the row from lists."""
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from dependencies import MOCK_TENANT_ID, get_db_session
from main import app
from models import AuditLog, Invoice, User

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
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
    def get_db_session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = get_db_session_override
    yield
    app.dependency_overrides.clear()


def test_soft_delete_preserves_audit_logs_and_hides_from_list(db_session):
    invoice_id = uuid4()
    actor_id = uuid4()
    db_session.add(
        User(
            id=actor_id,
            tenant_id=MOCK_TENANT_ID,
            clerk_user_id="actor-for-audit",
            email="actor@example.com",
            role="Admin",
        )
    )
    db_session.add(
        Invoice(
            id=invoice_id,
            tenant_id=MOCK_TENANT_ID,
            file_path="mock/soft-delete.pdf",
            status="COMPLETED",
            vendor_name="Soft Delete Vendor",
            grand_total=99.0,
        )
    )
    prior = AuditLog(
        tenant_id=MOCK_TENANT_ID,
        invoice_id=invoice_id,
        actor_user_id=actor_id,
        actor_role="Admin",
        action="RESOLVE_INVOICE",
        details={"target_status": "PAID"},
        timestamp=datetime.utcnow(),
    )
    db_session.add(prior)
    db_session.commit()

    client = TestClient(app)
    response = client.delete(f"/api/v1/invoices/{invoice_id}")
    assert response.status_code == 200
    assert response.json()["success"] is True

    db_session.expire_all()
    invoice = db_session.get(Invoice, invoice_id)
    assert invoice is not None
    assert invoice.deleted_at is not None

    logs = db_session.exec(
        select(AuditLog).where(AuditLog.invoice_id == invoice_id)
    ).all()
    actions = {log.action for log in logs}
    assert "RESOLVE_INVOICE" in actions
    assert "DELETE_INVOICE" in actions
    assert len(logs) == 2

    list_resp = client.get("/api/v1/invoices")
    assert list_resp.status_code == 200
    assert all(row["id"] != str(invoice_id) for row in list_resp.json())

    get_resp = client.get(f"/api/v1/invoices/{invoice_id}")
    assert get_resp.status_code == 404

    again = client.delete(f"/api/v1/invoices/{invoice_id}")
    assert again.status_code == 404


def _seed_invoice(db_session, invoice_id, batch_id=None):
    db_session.add(
        Invoice(
            id=invoice_id,
            tenant_id=MOCK_TENANT_ID,
            file_path=f"mock/{invoice_id}.pdf",
            status="COMPLETED",
            vendor_name="Chunk Vendor",
            grand_total=10.0,
            batch_id=batch_id,
        )
    )


def test_soft_delete_drops_chroma_chunks(db_session, monkeypatch):
    """Gap 460: single delete calls delete_invoice_chunks after the commit."""
    import routers.invoices as invoices_router

    invoice_id = uuid4()
    _seed_invoice(db_session, invoice_id)
    db_session.commit()

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        invoices_router, "delete_invoice_chunks",
        lambda inv, tenant: calls.append((inv, tenant)),
    )

    response = TestClient(app).delete(f"/api/v1/invoices/{invoice_id}")
    assert response.status_code == 200
    assert calls == [(str(invoice_id), str(MOCK_TENANT_ID))]

    db_session.expire_all()
    assert db_session.get(Invoice, invoice_id).deleted_at is not None


def test_soft_delete_survives_chroma_failure(db_session, monkeypatch):
    """Gap 460: an unreachable Chroma is swallowed inside delete_invoice_chunks;
    the row stays soft-deleted and the caller still gets 200."""
    import chroma_client

    invoice_id = uuid4()
    _seed_invoice(db_session, invoice_id)
    db_session.commit()

    def boom():
        raise RuntimeError("chroma down")

    monkeypatch.setattr(chroma_client, "get_chroma_client", boom)

    response = TestClient(app).delete(f"/api/v1/invoices/{invoice_id}")
    assert response.status_code == 200

    db_session.expire_all()
    assert db_session.get(Invoice, invoice_id).deleted_at is not None


def test_batch_rollback_drops_chroma_chunks_for_every_invoice(db_session, monkeypatch):
    """Gap 460: batch rollback calls delete_invoice_chunks once per invoice."""
    import routers.invoices as invoices_router

    batch_id = uuid4()
    ids = [uuid4(), uuid4()]
    for inv_id in ids:
        _seed_invoice(db_session, inv_id, batch_id=batch_id)
    db_session.commit()

    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        invoices_router, "delete_invoice_chunks",
        lambda inv, tenant: calls.append((inv, tenant)),
    )

    response = TestClient(app).delete(f"/api/v1/invoices/batches/{batch_id}")
    assert response.status_code == 200
    assert response.json()["count"] == 2
    assert sorted(calls) == sorted((str(i), str(MOCK_TENANT_ID)) for i in ids)
