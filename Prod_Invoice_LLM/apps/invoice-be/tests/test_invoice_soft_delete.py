"""Gap 460, reopened 2026-09-08: invoice delete is a HARD delete.

History kept in the filename on purpose. Gap 192 made delete a soft delete
(`deleted_at`) and this file asserted the row survived; Gap 460 then closed the
RAG leak and asserted the SQL route was safe, which it was not — model-generated
SQL has only a tenant guard, so soft-deleted invoices answered in chat. The
founder's rule is "delete means delete": every assertion below is on the
DATABASE (real Postgres, per CONVENTIONS hard rule 2), not on a 404, because a
404 alone is what the soft delete also produced.
"""
from datetime import date, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from config import get_settings
from dependencies import TenantContext, get_db_session, get_tenant_context
from main import app
from models import AuditLog, BankStatementLine, DocumentComparison, Invoice, Tenant, User
from services import invoice_deletion

INVOICES = "/api/v1/invoices"


def _pg_engine_or_skip():
    psycopg2 = pytest.importorskip("psycopg2")
    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        psycopg2.connect(url, connect_timeout=5).close()
    except psycopg2.OperationalError as exc:
        pytest.skip(f"local Postgres not reachable: {exc}")
    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="pg")
def pg_fixture():
    with Session(_pg_engine_or_skip()) as session:
        yield session


@pytest.fixture(autouse=True)
def _no_external_stores(monkeypatch):
    """Blob and Chroma are patched at the module the router calls into; the
    chat-cache invalidation gets a fake Redis so the keys it deletes are visible."""
    monkeypatch.setattr(invoice_deletion, "_delete_blob", lambda *a, **k: None)
    yield


def _tenant(session, tag):
    row = Tenant(
        id=uuid4(), name=f"G460-{tag}", domain=f"g460-{tag}.invalid",
        billing_plan="free", free_invoices_remaining=50,
    )
    session.add(row)
    session.commit()
    return row


def _user(session, tenant, tag):
    row = User(
        id=uuid4(), tenant_id=tenant.id, email=f"g460-{tag}@g460.invalid",
        role="Admin", clerk_user_id=f"user_g460_{tag}",
    )
    session.add(row)
    session.commit()
    return row


def _invoice(session, tenant, tag, batch_id=None, **extra):
    row = Invoice(
        id=uuid4(), tenant_id=tenant.id, batch_id=batch_id,
        file_path=f"{tenant.id}/inv-{tag}.pdf", vendor_name=f"Vendor {tag}",
        invoice_number=f"INV-{tag}", grand_total=100.0, currency="INR",
        invoice_date=date(2026, 9, 1), created_at=datetime.utcnow(),
        status="COMPLETED", flow_direction="INBOUND", **extra,
    )
    session.add(row)
    session.commit()
    return row


def _cleanup(session, tenant_ids):
    session.rollback()
    for tid in tenant_ids:
        for model in (AuditLog, DocumentComparison, BankStatementLine, Invoice, User):
            for row in session.exec(select(model).where(model.tenant_id == tid)).all():
                session.delete(row)
        tenant = session.get(Tenant, tid)
        if tenant:
            session.delete(tenant)
    session.commit()


class _Client:
    def __init__(self, session, tenant, db_user_id):
        self._session, self._tenant, self._db_user_id = session, tenant, db_user_id

    def __enter__(self):
        def _db():
            yield self._session

        def _ctx():
            return TenantContext(
                tenant_id=self._tenant.id, user_id="test-user",
                db_user_id=self._db_user_id, role="Admin", billing_plan="free",
            )

        app.dependency_overrides[get_db_session] = _db
        app.dependency_overrides[get_tenant_context] = _ctx
        return TestClient(app)

    def __exit__(self, *exc):
        app.dependency_overrides.clear()
        return False


class _FakeRedis:
    def __init__(self, keys):
        self.keys = set(keys)
        self.deleted = []

    def scan_iter(self, match, count=None):
        import fnmatch
        return [k for k in self.keys if fnmatch.fnmatch(k, match)]

    def delete(self, *keys):
        self.deleted.extend(keys)
        self.keys -= set(keys)
        return len(keys)


def test_delete_removes_the_row_its_history_and_every_back_reference(pg):
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        user = _user(pg, tenant, tag)
        inv = _invoice(pg, tenant, tag)
        dup = _invoice(pg, tenant, tag + "d", duplicate_of_invoice_id=inv.id)
        clone = _invoice(pg, tenant, tag + "c", source_invoice_id=inv.id)
        pg.add(AuditLog(
            tenant_id=tenant.id, invoice_id=inv.id, actor_user_id=user.id,
            actor_role="Admin", action="RESOLVE_INVOICE", details={"target_status": "PAID"},
            timestamp=datetime.utcnow(),
        ))
        pg.add(DocumentComparison(tenant_id=tenant.id, invoice_id=inv.id, kind="attachment_vs_invoice"))
        line = BankStatementLine(
            tenant_id=tenant.id, attachment_id=uuid4(), line_no=1, matched_invoice_id=inv.id,
            **_bank_line_required(),
        )
        pg.add(line)
        pg.commit()

        with _Client(pg, tenant, user.id) as client, \
                patch("chroma_client.delete_invoice_chunks") as chunks, \
                patch.object(invoice_deletion, "invalidate_tenant_chat_cache") as cache:
            res = client.delete(f"{INVOICES}/{inv.id}")
            assert res.status_code == 200, res.text
            chunks.assert_called_once_with(str(inv.id), str(tenant.id))
            cache.assert_called_once_with(tenant.id)

            assert client.get(f"{INVOICES}/{inv.id}").status_code == 404
            assert client.delete(f"{INVOICES}/{inv.id}").status_code == 404

        pg.expire_all()
        # The proof the SQL chat route cannot leak it: the row is not in the table.
        assert pg.execute(
            text("SELECT count(*) FROM invoice WHERE id = :id"), {"id": str(inv.id)}
        ).scalar() == 0
        assert pg.get(Invoice, dup.id).duplicate_of_invoice_id is None
        assert pg.get(Invoice, clone.id).source_invoice_id is None
        assert pg.get(BankStatementLine, line.id).matched_invoice_id is None
        assert pg.exec(select(DocumentComparison).where(DocumentComparison.invoice_id == inv.id)).all() == []

        logs = pg.exec(select(AuditLog).where(AuditLog.invoice_id == inv.id)).all()
        assert [l.action for l in logs] == ["DELETE_INVOICE"], "exactly one summary row remains"
        assert logs[0].details["hard_delete"] is True
        assert logs[0].details["invoice_number"] == f"INV-{tag}"
    finally:
        _cleanup(pg, [tenant.id])


def test_delete_purges_blob_and_survives_chroma_failure(pg, monkeypatch):
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        user = _user(pg, tenant, tag)
        inv = _invoice(pg, tenant, tag)
        blobs = []
        monkeypatch.setattr(invoice_deletion, "_delete_blob", lambda path, what: blobs.append(path))
        import chroma_client

        def boom():
            raise RuntimeError("chroma down")

        monkeypatch.setattr(chroma_client, "get_chroma_client", boom)

        with _Client(pg, tenant, user.id) as client, \
                patch.object(invoice_deletion, "invalidate_tenant_chat_cache"):
            assert client.delete(f"{INVOICES}/{inv.id}").status_code == 200

        assert blobs == [f"{tenant.id}/inv-{tag}.pdf"]
        pg.expire_all()
        assert pg.get(Invoice, inv.id) is None
    finally:
        _cleanup(pg, [tenant.id])


def test_delete_invalidates_only_this_tenants_cached_chat_answers(monkeypatch):
    tenant_id, other = uuid4(), uuid4()
    fake = _FakeRedis({
        f"chat_answer_cache:{tenant_id}:vendors", f"chat_answer_cache:{tenant_id}:total:rules=v2",
        f"chat_answer_cache:{other}:vendors", "tenant_stats:x",
    })
    import agents.query_agent as qa
    monkeypatch.setattr(qa, "_get_redis_client", lambda: fake)

    assert invoice_deletion.invalidate_tenant_chat_cache(tenant_id) == 2
    assert fake.keys == {f"chat_answer_cache:{other}:vendors", "tenant_stats:x"}


def test_batch_rollback_hard_deletes_every_invoice_in_the_batch(pg):
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        user = _user(pg, tenant, tag)
        batch_id = uuid4()
        ids = [_invoice(pg, tenant, tag + str(i), batch_id=batch_id).id for i in range(2)]
        keep = _invoice(pg, tenant, tag + "k", batch_id=uuid4())

        with _Client(pg, tenant, user.id) as client, \
                patch("chroma_client.delete_invoice_chunks") as chunks, \
                patch.object(invoice_deletion, "invalidate_tenant_chat_cache"):
            res = client.delete(f"{INVOICES}/batches/{batch_id}")
            assert res.status_code == 200, res.text
            assert res.json()["count"] == 2
            assert sorted(c.args for c in chunks.call_args_list) == sorted((str(i), str(tenant.id)) for i in ids)

        pg.expire_all()
        for i in ids:
            assert pg.get(Invoice, i) is None
        assert pg.get(Invoice, keep.id) is not None, "wrong batch was rolled back"
        actions = pg.exec(select(AuditLog).where(AuditLog.tenant_id == tenant.id)).all()
        assert sorted(a.details.get("batch_id") for a in actions) == [str(batch_id)] * 2
    finally:
        _cleanup(pg, [tenant.id])


def test_cross_tenant_delete_is_404_and_destroys_nothing(pg):
    tag = uuid4().hex[:10]
    a, b = _tenant(pg, tag + "a"), _tenant(pg, tag + "b")
    try:
        user_b = _user(pg, b, tag)
        inv = _invoice(pg, a, tag)
        with _Client(pg, b, user_b.id) as client, patch("chroma_client.delete_invoice_chunks") as chunks:
            assert client.delete(f"{INVOICES}/{inv.id}").status_code == 404
            chunks.assert_not_called()
        pg.expire_all()
        assert pg.get(Invoice, inv.id) is not None
    finally:
        _cleanup(pg, [a.id, b.id])


def _bank_line_required():
    """Minimal non-null columns of BankStatementLine beyond the ones the test sets."""
    from models import BankStatementLine as B
    required = {}
    for name, col in B.__table__.columns.items():
        if col.nullable or col.default is not None or col.server_default is not None or col.primary_key:
            continue
        if name in {"tenant_id", "attachment_id", "line_no", "matched_invoice_id"}:
            continue
        py = col.type.python_type
        required[name] = {str: "x", int: 1, float: 1.0}.get(py, date(2026, 9, 1) if py is date else datetime.utcnow())
    return required
