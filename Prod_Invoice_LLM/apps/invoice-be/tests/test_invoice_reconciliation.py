"""
Tests for FE Gaps 81 + 84: stuck-invoice reconciliation and durable failure
persistence (services/invoice_reconciliation.py plus the two queue handlers'
except blocks).

Both gaps produced the same visible symptom -- an invoice frozen on
PROCESSING/UPLOADED forever -- from different causes, so the tests are split
the same way:

Gap 84 (worker ran and failed, but the failure was never persisted)
1.  mark_invoice_failed writes FAILED + completed_at.
2.  ...and appends its alert instead of discarding alerts already on the row.
3.  The inbound handler's failure path persists FAILED to the DB, not just SSE.
4.  The outbound handler's failure path does too -- the worse case, since
    outbound never persists any intermediate status at all.
5.  A DB failure while recording the failure must not replace the original
    exception the handler is re-raising.

Gap 81 (worker never touched the message; nothing ages the invoice out)
6.  A fresh in-flight invoice is not considered stuck.
7.  One older than the threshold is.
8.  A terminal-status invoice is never a candidate, however old.
9.  Age is measured from last_enqueued_at when set, not created_at -- otherwise
    a just-re-enqueued invoice would be re-enqueued again every pass.
10. Reconciliation re-enqueues a stuck invoice with the right task name for its
    direction, and stamps attempts/last_enqueued_at.
11. ...and is therefore idempotent: an immediate second pass does nothing.
12. Once attempts are exhausted it stops retrying and marks the invoice FAILED.
13. An enqueue failure does not burn an attempt (the failure was ours).
14. force_requeue works regardless of age and attempt count, and revives a
    FAILED invoice to its own direction's in-flight status.
"""
from datetime import datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import services.invoice_reconciliation as recon
from models import Invoice

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TENANT_ID = UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def captured_queue(monkeypatch):
    """Replace the real Azure Queue send with a recorder.

    Patching _enqueue's collaborator rather than _enqueue itself keeps the
    task-name/kwargs construction under test -- that mapping is the part that
    would silently send an outbound invoice down the inbound handler.
    """
    sent: list[dict] = []

    class _FakeQueueClient:
        @staticmethod
        def from_connection_string(_conn, _queue):
            return _FakeQueueClient()

        def send_message(self, body):
            import json

            sent.append(json.loads(body))

    monkeypatch.setattr(recon, "QueueClient", _FakeQueueClient)
    monkeypatch.setattr(
        recon.get_settings(), "AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true"
    )
    return sent


def _seed_invoice(
    db_session: Session,
    status: str = "PROCESSING",
    direction: str = "INBOUND",
    created_minutes_ago: int = 0,
    last_enqueued_minutes_ago: int | None = None,
    attempts: int = 1,
    alerts: list | None = None,
) -> Invoice:
    now = datetime.utcnow()
    invoice = Invoice(
        tenant_id=TENANT_ID,
        batch_id=uuid4(),
        file_path=f"blob://{uuid4()}.pdf",
        status=status,
        flow_direction=direction,
        created_at=now - timedelta(minutes=created_minutes_ago),
        last_enqueued_at=(
            None if last_enqueued_minutes_ago is None else now - timedelta(minutes=last_enqueued_minutes_ago)
        ),
        processing_attempts=attempts,
        sa_alerts=alerts or [],
    )
    db_session.add(invoice)
    db_session.commit()
    db_session.refresh(invoice)
    return invoice


# ---------------------------------------------------------------------------
# Gap 84 -- durable failure
# ---------------------------------------------------------------------------

def test_mark_invoice_failed_persists_terminal_state(db_session):
    invoice = _seed_invoice(db_session)

    recon.mark_invoice_failed(db_session, invoice, reason="Doc Intelligence rejected the file")

    reloaded = db_session.get(Invoice, invoice.id)
    assert reloaded.status == "FAILED"
    assert reloaded.completed_at is not None
    assert reloaded.sa_alerts[-1]["type"] == "processing_failed"
    assert "Doc Intelligence" in reloaded.sa_alerts[-1]["message"]


def test_mark_invoice_failed_preserves_existing_alerts(db_session):
    """An invoice can fail *after* verification alerts were raised; those are the
    only diagnostic the auditor has, so they must not be overwritten."""
    invoice = _seed_invoice(db_session, alerts=[{"type": "tax_mismatch", "message": "earlier finding"}])

    recon.mark_invoice_failed(db_session, invoice, reason="boom")

    alerts = db_session.get(Invoice, invoice.id).sa_alerts
    assert [a["type"] for a in alerts] == ["tax_mismatch", "processing_failed"]


def test_inbound_handler_failure_persists_failed(db_session, monkeypatch):
    """The regression this gap is really about: the handler used to publish
    FAILED to SSE and re-raise, leaving the DB row on PROCESSING forever."""
    import queue_worker.handlers as handlers

    invoice = _seed_invoice(db_session)
    monkeypatch.setattr(handlers, "engine", engine)
    monkeypatch.setattr(handlers, "_publish_sse_events", lambda *a, **k: None)
    monkeypatch.setattr(
        handlers, "_run_ocr",
        lambda *a, **k: (_ for _ in ()).throw(Exception("InvalidContent: file is corrupted")),
    )

    with pytest.raises(Exception, match="InvalidContent"):
        handlers.handle_process_invoice(str(invoice.batch_id), invoice.file_path, str(TENANT_ID))

    db_session.expire_all()
    reloaded = db_session.get(Invoice, invoice.id)
    assert reloaded.status == "FAILED"
    assert "InvalidContent" in reloaded.sa_alerts[-1]["message"]


def test_outbound_handler_failure_persists_failed(db_session, monkeypatch):
    """Outbound is the worse case: with no intermediate DB status at all, a
    Gap-84 failure and a Gap-81 worker-down invoice were indistinguishable from
    the database alone (both sat at UPLOADED)."""
    import queue_worker.handlers as handlers
    import queue_worker.outbound_handlers as outbound_handlers

    invoice = _seed_invoice(db_session, status="UPLOADED", direction="OUTBOUND")
    monkeypatch.setattr(handlers, "engine", engine)
    monkeypatch.setattr(outbound_handlers, "_publish_sse_events", lambda *a, **k: None)
    monkeypatch.setattr(
        outbound_handlers, "_run_ocr",
        lambda *a, **k: (_ for _ in ()).throw(Exception("InvalidContent: file is corrupted")),
    )

    with pytest.raises(Exception, match="InvalidContent"):
        outbound_handlers.handle_process_outbound_invoice(
            str(invoice.batch_id), invoice.file_path, str(TENANT_ID)
        )

    db_session.expire_all()
    assert db_session.get(Invoice, invoice.id).status == "FAILED"


def test_persist_failure_error_does_not_mask_the_original_exception(monkeypatch):
    """Losing the real cause to a bookkeeping error would make this harder to
    debug than the bug it fixes."""
    import queue_worker.handlers as handlers

    def _explode(*_a, **_k):
        raise RuntimeError("database is down")

    monkeypatch.setattr(handlers, "Session", _explode)

    # Must return normally, swallowing its own failure.
    handlers._persist_processing_failure("blob://nope.pdf", Exception("original cause"))


# ---------------------------------------------------------------------------
# Gap 81 -- staleness detection
# ---------------------------------------------------------------------------

def test_fresh_in_flight_invoice_is_not_stuck(db_session):
    _seed_invoice(db_session, created_minutes_ago=1, last_enqueued_minutes_ago=1)
    assert find_ids(recon.find_stuck_invoices(db_session)) == []


def test_old_in_flight_invoice_is_stuck(db_session):
    invoice = _seed_invoice(db_session, created_minutes_ago=60, last_enqueued_minutes_ago=60)
    assert find_ids(recon.find_stuck_invoices(db_session)) == [invoice.id]


@pytest.mark.parametrize("status", ["COMPLETED", "AUDIT_REQUIRED", "VERIFIED", "FAILED", "PAID"])
def test_terminal_statuses_are_never_stuck(db_session, status):
    _seed_invoice(db_session, status=status, created_minutes_ago=10_000, last_enqueued_minutes_ago=10_000)
    assert recon.find_stuck_invoices(db_session) == []


def test_age_is_measured_from_last_enqueued_at_not_created_at(db_session):
    """Without this, a just-re-enqueued invoice would look permanently overdue
    and be re-enqueued on every single sweep."""
    _seed_invoice(db_session, created_minutes_ago=600, last_enqueued_minutes_ago=1)
    assert recon.find_stuck_invoices(db_session) == []


# ---------------------------------------------------------------------------
# Gap 81 -- reconciliation behaviour
# ---------------------------------------------------------------------------

def find_ids(invoices) -> list[UUID]:
    return [i.id for i in invoices]


def test_reconcile_requeues_with_the_right_task_per_direction(db_session, captured_queue):
    inbound = _seed_invoice(db_session, created_minutes_ago=60, last_enqueued_minutes_ago=60)
    outbound = _seed_invoice(
        db_session, status="UPLOADED", direction="OUTBOUND",
        created_minutes_ago=60, last_enqueued_minutes_ago=60,
    )

    result = recon.reconcile_stuck_invoices(db_session)

    assert set(result["requeued"]) == {inbound.id, outbound.id}
    assert result["failed"] == []
    tasks = sorted(m["task"] for m in captured_queue)
    assert tasks == ["process_invoice", "process_outbound_invoice"]
    assert db_session.get(Invoice, inbound.id).processing_attempts == 2
    assert db_session.get(Invoice, inbound.id).last_enqueued_at is not None


def test_reconcile_is_idempotent_on_an_immediate_second_pass(db_session, captured_queue):
    _seed_invoice(db_session, created_minutes_ago=60, last_enqueued_minutes_ago=60)

    first = recon.reconcile_stuck_invoices(db_session)
    second = recon.reconcile_stuck_invoices(db_session)

    assert len(first["requeued"]) == 1
    assert second == {"requeued": [], "failed": []}
    assert len(captured_queue) == 1


def test_reconcile_gives_up_and_fails_after_max_attempts(db_session, captured_queue):
    """A file the worker genuinely cannot process must not be requeued forever."""
    from config import get_settings

    invoice = _seed_invoice(
        db_session, created_minutes_ago=60, last_enqueued_minutes_ago=60,
        attempts=get_settings().INVOICE_MAX_REPROCESS_ATTEMPTS,
    )

    result = recon.reconcile_stuck_invoices(db_session)

    assert result["failed"] == [invoice.id]
    assert captured_queue == []
    reloaded = db_session.get(Invoice, invoice.id)
    assert reloaded.status == "FAILED"
    assert reloaded.sa_alerts[-1]["type"] == "processing_timeout"


def test_enqueue_failure_does_not_burn_an_attempt(db_session, monkeypatch):
    """The failure was ours (queue unreachable), not the invoice's -- the next
    sweep should get a full retry, not a shortened one."""
    invoice = _seed_invoice(db_session, created_minutes_ago=60, last_enqueued_minutes_ago=60)
    monkeypatch.setattr(recon, "_enqueue", lambda _inv: False)

    result = recon.reconcile_stuck_invoices(db_session)

    assert result == {"requeued": [], "failed": []}
    reloaded = db_session.get(Invoice, invoice.id)
    assert reloaded.processing_attempts == 1
    assert reloaded.status == "PROCESSING"


def test_force_requeue_ignores_age_and_attempts_and_revives_a_failed_invoice(db_session, captured_queue):
    """Operator recovery path for an already-stuck record -- e.g. the 2026-07-29
    outbound invoice whose queue message was genuinely gone."""
    invoice = _seed_invoice(
        db_session, status="FAILED", direction="OUTBOUND",
        created_minutes_ago=0, last_enqueued_minutes_ago=0, attempts=99,
    )

    assert recon.force_requeue(db_session, invoice.id) is True

    reloaded = db_session.get(Invoice, invoice.id)
    assert reloaded.status == "UPLOADED"          # outbound's own in-flight status
    assert reloaded.processing_attempts == 0      # normal sweep looks after it again
    assert captured_queue[0]["task"] == "process_outbound_invoice"


def test_force_requeue_on_a_missing_invoice_returns_false(db_session, captured_queue):
    assert recon.force_requeue(db_session, uuid4()) is False
