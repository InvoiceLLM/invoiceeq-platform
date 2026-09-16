"""BE Gap 550: deleting an invoice keeps its audit trail (services/invoice_deletion.py), on in-memory SQLite.

`tests/test_invoice_soft_delete.py` covers the whole delete on Postgres; this file pins the trail rule
where the default test run can reach it.
"""
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from models import AuditLog, Invoice
from services.extraction_quality_rollup import field_correction_rollup
from services.invoice_deletion import delete_invoice_rows


def test_deleting_an_invoice_keeps_its_trail_rows_and_their_correction_history():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    tenant_id, actor_id, invoice_id = uuid4(), uuid4(), uuid4()

    with Session(engine) as session:
        session.add(Invoice(
            id=invoice_id, tenant_id=tenant_id, file_path="mock/invoice.pdf", invoice_number="INV-9",
            status="PAID", sa_alerts=[],
        ))
        session.add(AuditLog(
            tenant_id=tenant_id, invoice_id=invoice_id, actor_user_id=actor_id, actor_role="Admin",
            action="RESOLVE_INVOICE", details={"corrections": {"grand_total": {"old": 100.0, "new": 120.0}}},
            timestamp=datetime.utcnow() - timedelta(minutes=5),
        ))
        session.commit()

        delete_invoice_rows(session, session.get(Invoice, invoice_id), actor_user_id=actor_id, actor_role="Admin")
        session.commit()

        assert session.get(Invoice, invoice_id) is None
        logs = session.exec(
            select(AuditLog).where(AuditLog.invoice_id == invoice_id).order_by(AuditLog.timestamp)
        ).all()
        assert [log.action for log in logs] == ["RESOLVE_INVOICE", "DELETE_INVOICE"]
        assert logs[1].details["invoice_number"] == "INV-9"
        # The correction still counts in the extraction-quality rollup after the delete.
        assert [row["field"] for row in field_correction_rollup(session, tenant_id)] == ["grand_total"]
