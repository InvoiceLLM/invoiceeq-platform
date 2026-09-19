"""BE Gap 679: the stuck-invoice sweep that the new scheduled job runs.

Founder ruling D10 (2026-09-17): sweep every 10 minutes, an invoice is stuck after
**20** minutes. The first version of these tests mocked the setting to 30, so they
could not notice the real default; these use the real `config.py` value and write real
rows, so they run on Postgres only (CONVENTIONS hard rule 2).
"""
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from sqlmodel import Session

from config import Settings, get_settings
from dependencies import MOCK_TENANT_ID
from models import Invoice
from services.invoice_reconciliation import find_stuck_invoices, reconcile_stuck_invoices
from tests.pg_gap_fixtures import pg_engine, pg_only  # noqa: F401  (pytest fixture)

NOW = datetime(2026, 9, 17, 12, 0, 0)


def test_stuck_threshold_default_is_20_minutes():
    assert Settings.model_fields["INVOICE_STUCK_AFTER_MINUTES"].default == 20


def test_bicep_declares_the_sweep_job_every_10_minutes():
    bicep = (Path(__file__).resolve().parents[3] / "infra" / "08-apps.bicep").read_text(encoding="utf-8")
    assert "param stuckInvoiceSweepCron string = '*/10 * * * *'" in bicep
    assert "'scripts/reconcile_stuck_invoices.py'" in bicep
    assert "cronExpression: stuckInvoiceSweepCron" in bicep


def _invoice(session, minutes_ago, attempts=0, status="PROCESSING"):
    inv = Invoice(id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path=f"tenants/t/invoices/{uuid4()}.pdf",
                  status=status, created_at=NOW - timedelta(minutes=minutes_ago), processing_attempts=attempts)
    session.add(inv)
    session.commit()
    return inv.id


@pg_only
def test_only_invoices_older_than_20_minutes_are_stuck(pg_engine):
    assert get_settings().INVOICE_STUCK_AFTER_MINUTES == 20
    with Session(pg_engine) as session:
        stuck = _invoice(session, minutes_ago=21)
        fresh = _invoice(session, minutes_ago=19)
        done = _invoice(session, minutes_ago=90, status="COMPLETED")
        found = {inv.id for inv in find_stuck_invoices(session, now=NOW)}
    assert stuck in found
    assert fresh not in found
    assert done not in found


@pg_only
def test_sweep_requeues_then_fails_after_max_attempts(pg_engine):
    with Session(pg_engine) as session:
        requeue_id = _invoice(session, minutes_ago=25, attempts=0)
        exhausted_id = _invoice(session, minutes_ago=25, attempts=get_settings().INVOICE_MAX_REPROCESS_ATTEMPTS)
        with patch("services.invoice_reconciliation._enqueue", return_value=True):
            result = reconcile_stuck_invoices(session, now=NOW)

    assert requeue_id in result["requeued"]
    assert exhausted_id in result["failed"]
    with Session(pg_engine) as session:
        requeued = session.get(Invoice, requeue_id)
        failed = session.get(Invoice, exhausted_id)
        assert requeued.processing_attempts == 1
        assert requeued.last_enqueued_at == NOW
        assert failed.status == "FAILED"
