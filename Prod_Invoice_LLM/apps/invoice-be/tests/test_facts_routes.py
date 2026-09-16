"""Tests for GAP-04: Facts HTTP API Endpoint (routers/facts.py)."""
from datetime import date, datetime
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from routers.facts import router as facts_router
from dependencies import get_db_session, get_tenant_context, TenantContext
from models import Fact


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def build_test_client(db_session, tenant_id=None, role="Auditor", clearance="ops"):
    app = FastAPI()
    app.include_router(facts_router)
    app.include_router(facts_router, prefix="/api/v1")

    t_id = tenant_id or uuid4()

    def override_get_db():
        return db_session

    def override_tenant_context():
        return TenantContext(
            tenant_id=t_id,
            user_id="test_user",
            role=role,
            clearance=clearance,
            billing_plan="free",
            is_authenticated=True,
            can_edit=True,
            can_train=True,
        )

    app.dependency_overrides[get_db_session] = override_get_db
    app.dependency_overrides[get_tenant_context] = override_tenant_context
    client = TestClient(app)
    return client, t_id


def test_get_facts_for_subject_kind_and_id(test_db):
    client, tenant_id = build_test_client(test_db, clearance="ops")

    f1 = Fact(
        tenant_id=tenant_id,
        clearance="ops",
        kind="commitment",
        subject_kind="invoice",
        subject_id="INV-9901",
        as_of=date(2026, 9, 1),
        figures={"total_amount": 50000.0, "currency": "INR"},
    )
    f2 = Fact(
        tenant_id=tenant_id,
        clearance="ops",
        kind="payment",
        subject_kind="invoice",
        subject_id="INV-9901",
        as_of=date(2026, 9, 10),
        figures={"paid_amount": 50000.0, "currency": "INR"},
    )
    f3 = Fact(
        tenant_id=tenant_id,
        clearance="ops",
        kind="commitment",
        subject_kind="invoice",
        subject_id="INV-OTHER",
    )
    test_db.add_all([f1, f2, f3])
    test_db.commit()

    # Query with subject_kind and subject_id
    resp = client.get("/facts?subject_kind=invoice&subject_id=INV-9901")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["count"] == 2
    kinds = [f["kind"] for f in data["facts"]]
    assert "commitment" in kinds
    assert "payment" in kinds

    # Also test via /api/v1 prefix
    resp_v1 = client.get("/api/v1/facts?subject_kind=invoice&subject_id=INV-9901")
    assert resp_v1.status_code == 200
    assert resp_v1.json()["count"] == 2


def test_clearance_filtering_ops_vs_exec(test_db):
    tenant_id = uuid4()

    # Fact 1: ops clearance
    f_ops = Fact(
        tenant_id=tenant_id,
        clearance="ops",
        kind="delivery",
        subject_kind="invoice",
        subject_id="INV-SEC-1",
    )
    # Fact 2: exec clearance (cashflow / owner sensitive)
    f_exec = Fact(
        tenant_id=tenant_id,
        clearance="exec",
        kind="bank_balance",
        subject_kind="invoice",
        subject_id="INV-SEC-1",
        figures={"owner_override": True},
    )
    test_db.add_all([f_ops, f_exec])
    test_db.commit()

    # 1. Auditor (ops) only sees ops fact
    client_ops, _ = build_test_client(test_db, tenant_id=tenant_id, role="Auditor", clearance="ops")
    resp_ops = client_ops.get("/facts?subject_kind=invoice&subject_id=INV-SEC-1")
    assert resp_ops.status_code == 200
    data_ops = resp_ops.json()
    assert data_ops["count"] == 1
    assert data_ops["facts"][0]["kind"] == "delivery"

    # 2. Admin (exec) sees both ops and exec facts
    client_exec, _ = build_test_client(test_db, tenant_id=tenant_id, role="Admin", clearance="exec")
    resp_exec = client_exec.get("/facts?subject_kind=invoice&subject_id=INV-SEC-1")
    assert resp_exec.status_code == 200
    data_exec = resp_exec.json()
    assert data_exec["count"] == 2


def test_tenant_isolation(test_db):
    tenant_a = uuid4()
    tenant_b = uuid4()

    f_a = Fact(
        tenant_id=tenant_a,
        clearance="ops",
        kind="commitment",
        subject_kind="invoice",
        subject_id="INV-SHARED-NUM",
    )
    f_b = Fact(
        tenant_id=tenant_b,
        clearance="ops",
        kind="commitment",
        subject_kind="invoice",
        subject_id="INV-SHARED-NUM",
    )
    test_db.add_all([f_a, f_b])
    test_db.commit()

    client_a, _ = build_test_client(test_db, tenant_id=tenant_a)
    resp = client_a.get("/facts?subject_kind=invoice&subject_id=INV-SHARED-NUM")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["facts"][0]["tenant_id"] == str(tenant_a)


def test_get_fact_by_id_and_clearance_guard(test_db):
    tenant_id = uuid4()
    exec_fact = Fact(
        tenant_id=tenant_id,
        clearance="exec",
        kind="executive_variance",
        subject_kind="invoice",
        subject_id="INV-404",
    )
    test_db.add(exec_fact)
    test_db.commit()

    # Ops user gets 403 Forbidden
    client_ops, _ = build_test_client(test_db, tenant_id=tenant_id, clearance="ops")
    resp_ops = client_ops.get(f"/facts/{exec_fact.id}")
    assert resp_ops.status_code == 403

    # Exec user gets 200
    client_exec, _ = build_test_client(test_db, tenant_id=tenant_id, clearance="exec")
    resp_exec = client_exec.get(f"/facts/{exec_fact.id}")
    assert resp_exec.status_code == 200
    assert resp_exec.json()["id"] == str(exec_fact.id)

    # Unknown ID gets 404
    resp_404 = client_exec.get(f"/facts/{uuid4()}")
    assert resp_404.status_code == 404


def test_documents_summary(test_db):
    client, tenant_id = build_test_client(test_db, clearance="ops")

    doc_id = uuid4()
    f1 = Fact(
        tenant_id=tenant_id,
        clearance="ops",
        kind="commitment",
        subject_kind="invoice",
        subject_id="INV-DOC-1",
        source_id=doc_id,
        source_kind="chat_attachment",
    )
    f2 = Fact(
        tenant_id=tenant_id,
        clearance="ops",
        kind="delivery",
        subject_kind="invoice",
        subject_id="INV-DOC-1",
        source_id=doc_id,
        source_kind="chat_attachment",
    )
    test_db.add_all([f1, f2])
    test_db.commit()

    resp = client.get("/facts/documents/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert len(data["documents"]) == 1
    doc_entry = data["documents"][0]
    assert doc_entry["source_id"] == str(doc_id)
    assert doc_entry["facts_count"] == 2
