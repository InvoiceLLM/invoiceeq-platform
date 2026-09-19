"""BE Gap 678: no pooled Postgres connection is held open across network calls.

Postgres only (CONVENTIONS hard rule 2): the check is the real SQLAlchemy pool's
`checkedout()` count, sampled from inside fakes for the network steps -- embedding /
Chroma indexing, the webhook fan-out and the staff email. The first version of this
test inspected a MagicMock's `__exit__.called`, which was already True from an earlier
session in the same handler, so it passed whether or not indexing was inside the session.
"""
from unittest.mock import patch
from uuid import uuid4

from sqlmodel import Session, select

from dependencies import MOCK_TENANT_ID
from models import Invoice
from tests.pg_gap_fixtures import pg_engine, pg_only  # noqa: F401  (pytest fixture)


def _process(pg_engine, status="COMPLETED"):
    from queue_worker.handlers import handle_process_invoice

    file_path = f"tenants/{MOCK_TENANT_ID}/invoices/{uuid4()}.pdf"
    with Session(pg_engine) as s:
        s.add(Invoice(id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path=file_path, status="PROCESSING"))
        s.commit()

    seen = {}

    def sample(name):
        def _fake(*args, **kwargs):
            seen[name] = pg_engine.pool.checkedout()
        return _fake

    agent = {"status": status, "alerts": [], "extracted_data": {"vendor_name": "Kaveri Logistics", "invoice_number": "KL-9", "grand_total": 10.0}}
    with patch("queue_worker.handlers.engine", pg_engine), \
         patch("queue_worker.handlers._run_ocr", return_value="ocr"), \
         patch("queue_worker.handlers._publish_sse_events"), \
         patch("queue_worker.handlers.run_extraction_agent", return_value=agent), \
         patch("queue_worker.handlers.track_extraction_pipeline_turn"), \
         patch("chroma_client.index_invoice_document", side_effect=sample("index")), \
         patch("services.webhooks.dispatch_webhook_event", side_effect=sample("webhook")), \
         patch("services.staff_notify.notify_processing_complete", side_effect=sample("notify")):
        handle_process_invoice(str(uuid4()), file_path, str(MOCK_TENANT_ID))

    with Session(pg_engine) as s:
        row = s.exec(select(Invoice).where(Invoice.file_path == file_path)).one()
    return seen, row


@pg_only
def test_no_connection_is_checked_out_during_chroma_indexing(pg_engine):
    seen, row = _process(pg_engine)
    assert row.status == "COMPLETED"
    assert seen["index"] == 0


@pg_only
def test_webhook_and_email_run_after_the_persistence_session_is_closed(pg_engine):
    """Each helper gets its own short session, so at most that one connection is out --
    never the persistence session's connection as well. The status is already committed."""
    seen, row = _process(pg_engine, status="AUDIT_REQUIRED")
    assert row.status == "AUDIT_REQUIRED"
    assert seen["webhook"] <= 1
    assert seen["notify"] <= 1
