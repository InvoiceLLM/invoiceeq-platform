"""BE Gap 670: a printed date in any common format is stored; one that cannot be
read is reported, never guessed and never silently blanked.

Pure tests cover the parser and the alert. The handler and near-duplicate tests
write rows, so they run on Postgres only (`tests/pg_gap_fixtures.py`).
Founder ruling D1 (2026-09-17): an unreadable date sends the invoice to review.
"""
from datetime import date
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlmodel import Session, select

from dependencies import MOCK_TENANT_ID
from models import Invoice
from tests.pg_gap_fixtures import pg_engine, pg_only  # noqa: F401  (pytest fixture)
from utils.alert_registry import get_alert_type
from utils.correction_values import parse_date
from utils.extracted_dates import DATE_ALERT_TYPE, parse_extracted_date


# --- the parser ---------------------------------------------------------------

@pytest.mark.parametrize(
    "printed, expected",
    [
        ("2026-09-15", date(2026, 9, 15)),
        ("2026-09-15T00:00:00", date(2026, 9, 15)),
        ("15/09/2026", date(2026, 9, 15)),
        ("12/31/2025", date(2025, 12, 31)),
        ("15.09.2026", date(2026, 9, 15)),
        ("15-09-2026", date(2026, 9, 15)),
        ("Sep 15, 2026", date(2026, 9, 15)),
        ("15 Sep 2026", date(2026, 9, 15)),
        ("15-Sep-2026", date(2026, 9, 15)),
        ("15-September-2026", date(2026, 9, 15)),
        ("15th September 2026", date(2026, 9, 15)),
        ("September 1st, 2026", date(2026, 9, 1)),
        ("15 Sept 2026", date(2026, 9, 15)),
        ("2026/09/15", date(2026, 9, 15)),
        ("2026.9.5", date(2026, 9, 5)),
        ("07/07/2026", date(2026, 7, 7)),
        ("15/09/2026 10:30", date(2026, 9, 15)),
        ("Sep 15, 2026 10:30 AM", date(2026, 9, 15)),
    ],
)
def test_printed_formats_are_read(printed, expected):
    parsed, alert = parse_extracted_date(printed, "invoice_date")
    assert (parsed, alert) == (expected, None)


@pytest.mark.parametrize("printed", ["05/06/2026", "15/09/26", "sometime in September", "2026-13-45", "31/02/2026"])
def test_unreadable_or_ambiguous_dates_raise_an_alert_and_are_not_guessed(printed):
    parsed, alert = parse_extracted_date(printed, "due_date")
    assert parsed is None
    assert alert["type"] == DATE_ALERT_TYPE
    assert alert["field"] == "due_date"
    assert alert["severity"] == "warning"
    assert f"'{printed}'" in alert["message"]
    assert "use YYYY-MM-DD" not in alert["message"]


def test_ambiguous_date_names_the_ambiguity():
    _, alert = parse_extracted_date("05/06/2026", "invoice_date")
    assert "day/month or month/day" in alert["message"]
    assert alert["message"].startswith("The printed invoice date ")


def test_one_parser_for_documents_and_audit_corrections():
    # BE Gap 670 widened the shared parser instead of adding a second one.
    for printed in ("15th September 2026", "2026/09/15", "15/09/2026 10:30", "Sep 15, 2026"):
        assert parse_extracted_date(printed, "invoice_date")[0] == parse_date(printed)


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_an_absent_date_is_not_an_alert(empty):
    assert parse_extracted_date(empty, "invoice_date") == (None, None)


def test_alert_type_is_registered_as_a_factual_alert():
    spec = get_alert_type(DATE_ALERT_TYPE)
    assert spec is not None
    assert spec.default_field is None  # raised on four different date fields
    assert spec.flaggable_as_missed is False
    assert spec.not_correctable_reason


def test_audit_correction_parser_still_refuses_what_it_refused():
    # The correction screens share parse_date; widening must not start guessing.
    with pytest.raises(ValueError):
        parse_date("05/06/2026")
    with pytest.raises(ValueError):
        parse_date("15/09/26")


def test_generic_document_date_alert_lands_on_the_alert_list():
    from queue_worker.handlers import _parse_doc_date

    alerts = []
    assert _parse_doc_date("15/09/2026", "doc_date", alerts) == date(2026, 9, 15)
    assert alerts == []
    assert _parse_doc_date("05/06/2026", "valid_until", alerts) is None
    assert [a["field"] for a in alerts] == ["valid_until"]


# --- Postgres: the worker write sites -------------------------------------------

def _agent_result(**dates):
    data = {
        "vendor_name": "Kaveri Logistics",
        "invoice_number": f"KL-{uuid4().hex[:6]}",
        "subtotal": 100.0,
        "tax_amount": 18.0,
        "grand_total": 118.0,
        **dates,
    }
    return {"status": "COMPLETED", "alerts": [], "extracted_data": data}


def _run_inbound(pg_engine, agent_result, **existing):
    file_path = f"tenants/{MOCK_TENANT_ID}/invoices/{uuid4().hex}.pdf"
    with Session(pg_engine) as session:
        session.add(Invoice(id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path=file_path, status="PROCESSING", **existing))
        session.commit()
    from queue_worker.handlers import handle_process_invoice

    with patch("queue_worker.handlers.engine", pg_engine), \
         patch("queue_worker.handlers._run_ocr", return_value="ocr"), \
         patch("queue_worker.handlers._publish_sse_events"), \
         patch("queue_worker.handlers.run_extraction_agent", return_value=agent_result), \
         patch("chroma_client.index_invoice_document"):
        handle_process_invoice(str(uuid4()), file_path, str(MOCK_TENANT_ID))
    with Session(pg_engine) as session:
        return session.exec(select(Invoice).where(Invoice.file_path == file_path)).one()


@pg_only
def test_inbound_non_iso_dates_are_stored(pg_engine):
    row = _run_inbound(pg_engine, _agent_result(invoice_date="15/09/2026", due_date="Oct 15, 2026"))
    assert row.invoice_date == date(2026, 9, 15)
    assert row.due_date == date(2026, 10, 15)
    assert row.status == "COMPLETED"
    assert not any(isinstance(a, dict) and a.get("type") == DATE_ALERT_TYPE for a in row.sa_alerts)


@pg_only
def test_inbound_unreadable_date_is_reported_and_sent_to_review(pg_engine):
    row = _run_inbound(pg_engine, _agent_result(invoice_date="05/06/2026", due_date="2026-07-05"))
    assert row.invoice_date is None
    assert row.due_date == date(2026, 7, 5)
    assert row.status == "AUDIT_REQUIRED"
    date_alerts = [a for a in row.sa_alerts if isinstance(a, dict) and a.get("type") == DATE_ALERT_TYPE]
    assert len(date_alerts) == 1
    assert date_alerts[0]["field"] == "invoice_date"
    assert "05/06/2026" in date_alerts[0]["message"]


@pg_only
def test_an_unread_date_never_overwrites_a_date_already_on_the_row(pg_engine):
    row = _run_inbound(
        pg_engine,
        _agent_result(invoice_date="05/06/2026", due_date=None),
        invoice_date=date(2026, 6, 5),
        due_date=date(2026, 7, 5),
    )
    assert row.invoice_date == date(2026, 6, 5)
    assert row.due_date == date(2026, 7, 5)
    assert row.status == "AUDIT_REQUIRED"


@pg_only
def test_outbound_unreadable_date_is_reported_and_sent_to_review(pg_engine):
    from queue_worker import outbound_handlers

    file_path = f"tenants/{MOCK_TENANT_ID}/outbound/{uuid4().hex}.pdf"
    with Session(pg_engine) as session:
        session.add(Invoice(id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path=file_path, flow_direction="OUTBOUND", status="UPLOADED"))
        session.commit()
    extracted = {"customer_name": "Vertex Industries", "invoice_number": f"OUT-{uuid4().hex[:6]}", "grand_total": 500.0,
                 "invoice_date": "15/09/2026", "due_date": "05/06/2026"}
    with patch("queue_worker.outbound_handlers.engine", pg_engine), \
         patch("queue_worker.outbound_handlers._run_ocr", return_value="ocr"), \
         patch("queue_worker.outbound_handlers._publish_sse_events"), \
         patch("queue_worker.outbound_handlers.run_outbound_extraction_agent",
               return_value={"status": "VERIFIED", "alerts": [], "extracted_data": extracted}), \
         patch("chroma_client.index_invoice_document"):
        outbound_handlers.handle_process_outbound_invoice(str(uuid4()), file_path, str(MOCK_TENANT_ID))
    with Session(pg_engine) as session:
        row = session.exec(select(Invoice).where(Invoice.file_path == file_path)).one()
    assert row.invoice_date == date(2026, 9, 15)
    assert row.due_date is None
    assert row.status == "NEEDS_REVIEW"
    assert [a["field"] for a in row.sa_alerts if isinstance(a, dict) and a.get("type") == DATE_ALERT_TYPE] == ["due_date"]


@pg_only
def test_near_duplicate_is_found_when_the_date_is_printed_non_iso(pg_engine):
    from queue_worker.handlers import find_near_duplicate

    with Session(pg_engine) as session:
        earlier = Invoice(id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path=f"a-{uuid4().hex}.pdf", status="COMPLETED",
                          flow_direction="INBOUND", vendor_name="Kaveri Logistics", invoice_number="KL-1",
                          invoice_date=date(2026, 9, 15), grand_total=118.0)
        current = Invoice(id=uuid4(), tenant_id=MOCK_TENANT_ID, file_path=f"b-{uuid4().hex}.pdf", status="PROCESSING",
                          flow_direction="INBOUND")
        session.add(earlier)
        session.add(current)
        session.commit()
        found = find_near_duplicate(session, current, {
            "vendor_name": "kaveri logistics", "invoice_number": "KL-2", "grand_total": 118.0, "invoice_date": "15/09/2026",
        })
        assert found is not None and found.id == earlier.id
