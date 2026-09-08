"""Feature 30 tasks 30.6 and 30.18 — the async cards and their R9 thresholds.

Verification plan 30.18: "Each threshold card returns `skipped` with reason
below its threshold and `ok` with exact figures at or above it."
Verification plan 30.6: "Fixture party with two overdue invoices and a PO: card
names both and the month outflow."

Real Postgres, and necessarily: every card here reads a semantic view, and the
views are Postgres DDL. No model anywhere.
"""
import os
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from models import ChatAttachment, ChatMessage, ChatSession, Insight, Invoice, TenantInsightSetting  # noqa: E402
from services import attachment_insights as ai  # noqa: E402

VENDOR = "Shree Packaging Pvt Ltd"


@pytest.fixture(name="pg_session")
def pg_session_fixture():
    psycopg2 = pytest.importorskip("psycopg2")
    from config import get_settings

    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        psycopg2.connect(url, connect_timeout=5).close()
    except psycopg2.OperationalError as exc:  # pragma: no cover - env dependent
        pytest.skip(f"local Postgres not reachable: {exc}")

    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="flag_on")
def flag_on_fixture(monkeypatch):
    from config import get_settings

    monkeypatch.setattr(get_settings(), "ENABLE_ATTACHMENT_INSIGHTS", True, raising=False)
    yield


@pytest.fixture(name="world")
def world_fixture(pg_session):
    tenant_id = uuid4()
    chat = ChatSession(tenant_id=tenant_id, title="F30 async")
    pg_session.add(chat)
    pg_session.commit()
    pg_session.refresh(chat)

    ctx = {"tenant_id": tenant_id, "session": chat}

    def add_invoice(number, *, total=10000.0, po=None, due=None, invoice_date=None,
                    vendor=VENDOR, status="PROCESSING", paid=None, direction="INBOUND"):
        inv = Invoice(
            tenant_id=tenant_id, invoice_number=number, file_path=f"test/{number}.pdf",
            vendor_name=vendor, grand_total=total, currency="INR", po_number=po,
            invoice_date=invoice_date or date(2026, 3, 1), due_date=due,
            status=status, paid_at=paid, flow_direction=direction,
        )
        pg_session.add(inv)
        pg_session.commit()
        pg_session.refresh(inv)
        return inv

    def add_attachment(doc_type, **kw):
        att = ChatAttachment(
            tenant_id=tenant_id, session_id=chat.id, filename="doc.pdf", blob_path="",
            doc_type=doc_type, extraction_status="EXTRACTED", party_name=kw.pop("party", VENDOR),
            currency="INR", doc_number=kw.pop("doc_number", "DOC-1"),
            doc_date=kw.pop("doc_date", date(2026, 2, 20)),
            grand_total=kw.pop("grand_total", 100000.0),
            extracted_json=kw.pop("extracted_json", {}),
            **kw,
        )
        pg_session.add(att)
        pg_session.commit()
        pg_session.refresh(att)
        return att

    ctx["add_invoice"] = add_invoice
    ctx["add_attachment"] = add_attachment
    yield ctx

    for model in (Insight, TenantInsightSetting):
        for r in pg_session.exec(select(model).where(model.tenant_id == tenant_id)).all():
            pg_session.delete(r)
    for msg in pg_session.exec(select(ChatMessage).where(ChatMessage.session_id == chat.id)).all():
        pg_session.delete(msg)
    pg_session.commit()
    for model in (ChatAttachment, Invoice):
        for r in pg_session.exec(select(model).where(model.tenant_id == tenant_id)).all():
            pg_session.delete(r)
    pg_session.commit()
    pg_session.delete(chat)
    pg_session.commit()


def _card(row, pg_session, name, stage="async"):
    block = ai.build_insight_block(row, pg_session, row.tenant_id, stage=stage)
    return next(c for c in block["cards"] if c["card"] == name)


# --- every async card is silent at the sync stage ---------------------------


@pytest.mark.parametrize(
    "doc_type,card",
    [
        ("PURCHASE_ORDER", "open_po_value"),
        ("PURCHASE_ORDER", "cash_out_timing"),
        ("PURCHASE_ORDER", "over_invoicing_history"),
        ("PURCHASE_ORDER", "cash_impact"),
        ("QUOTATION", "quote_drift"),
        ("CONTRACT", "contract_deviations"),
        ("DELIVERY_NOTE", "partial_delivery_balance"),
        ("DELIVERY_NOTE", "repeat_short_delivery"),
    ],
)
def test_async_cards_skip_themselves_in_the_sync_bubble(pg_session, world, flag_on, doc_type, card):
    """The sync bubble must stay fast; the user is told a second answer follows."""
    att = world["add_attachment"](doc_type)
    result = _card(att, pg_session, card, stage="sync")
    assert result["status"] == "skipped"
    assert "a moment after" in result["reason"]


# --- 30.6 cash impact -------------------------------------------------------


def test_cash_impact_names_the_overdue_bills_and_the_monthly_spend(pg_session, world, flag_on):
    world["add_invoice"]("OD-1", total=40000.0, due=date(2026, 1, 10))
    world["add_invoice"]("OD-2", total=25000.0, due=date(2026, 2, 10))
    world["add_invoice"]("PAID-1", total=9000.0, due=date(2026, 1, 5),
                         status="PAID", paid=datetime(2026, 1, 4))
    att = world["add_attachment"]("PURCHASE_ORDER")

    card = _card(att, pg_session, "cash_impact")
    assert card["status"] == "ok"
    assert card["figures"]["overdue_total"] == 65000.0  # 40000 + 25000, not the paid one
    assert card["figures"]["overdue_count"] == 2.0
    assert card["figures"]["this_document_total"] == 100000.0
    assert card["evidence"]["monthly_spend"]
    assert card["findings"][0]["impact_amount"] == 65000.0


def test_cash_impact_refuses_to_add_two_currencies(pg_session, world, flag_on):
    inv = world["add_invoice"]("FX-1", total=1000.0, due=date(2026, 1, 10))
    inv.currency = "EUR"
    pg_session.add(inv)
    pg_session.commit()

    att = world["add_attachment"]("PURCHASE_ORDER")
    card = _card(att, pg_session, "cash_impact")
    assert card["status"] == "skipped"
    assert "not added together" in card["reason"]


# --- 30.18 open PO value / cash-out timing ----------------------------------


def test_open_po_value_reports_what_is_not_yet_invoiced(pg_session, world, flag_on):
    world["add_invoice"]("PO-INV-1", total=40000.0, po="PO-77")
    att = world["add_attachment"](
        "PURCHASE_ORDER", doc_number="PO-77",
        extracted_json={"po_number": "PO-77", "doc_number": "PO-77"},
    )
    card = _card(att, pg_session, "open_po_value")
    assert card["figures"] == {
        "ordered_value": 100000.0,
        "invoiced_against_order": 40000.0,
        "not_yet_invoiced": 60000.0,
    }
    assert card["findings"][0]["impact_amount"] == 60000.0


def test_open_po_value_flags_over_invoicing_against_the_order(pg_session, world, flag_on):
    world["add_invoice"]("PO-INV-2", total=123200.0, po="PO-78")
    att = world["add_attachment"](
        "PURCHASE_ORDER", doc_number="PO-78", extracted_json={"po_number": "PO-78"}
    )
    card = _card(att, pg_session, "open_po_value")
    assert card["figures"]["not_yet_invoiced"] == -23200.0
    assert "more has been invoiced" in card["findings"][0]["title"]


def test_cash_out_timing_uses_the_documents_own_terms(pg_session, world, flag_on):
    att = world["add_attachment"](
        "PURCHASE_ORDER", doc_date=date(2026, 2, 20),
        extracted_json={"payment_terms": "Net 30"},
    )
    card = _card(att, pg_session, "cash_out_timing")
    assert card["figures"] == {"expected_outflow": 100000.0, "payment_days": 30.0}
    assert card["findings"][0]["evidence"]["expected_date"] == "2026-03-22"


def test_cash_out_timing_skips_without_a_printed_window(pg_session, world, flag_on):
    att = world["add_attachment"]("PURCHASE_ORDER", extracted_json={})
    assert _card(att, pg_session, "cash_out_timing")["status"] == "skipped"


# --- 30.18 the three R9 thresholds ------------------------------------------


def test_over_invoicing_history_is_skipped_below_three_pairs(pg_session, world, flag_on):
    world["add_invoice"]("H-1", po="PO-A")
    world["add_invoice"]("H-2", po="PO-B")
    att = world["add_attachment"]("PURCHASE_ORDER")

    card = _card(att, pg_session, "over_invoicing_history")
    assert card["status"] == "skipped"
    assert "needs 3" in card["reason"]


def test_over_invoicing_history_runs_at_the_threshold(pg_session, world, flag_on):
    for i, po in enumerate(["PO-A", "PO-B", "PO-C"]):
        world["add_invoice"](f"H-{i}", po=po)
    # PO-A billed twice -- the pattern the card reports.
    world["add_invoice"]("H-EXTRA", po="PO-A")
    att = world["add_attachment"]("PURCHASE_ORDER")

    card = _card(att, pg_session, "over_invoicing_history")
    assert card["status"] == "ok"
    assert card["figures"]["orders_with_invoices"] == 3.0
    assert card["figures"]["threshold_used"] == 3.0
    assert "invoiced more than once" in card["findings"][0]["title"]


def test_a_tenant_override_moves_the_history_threshold(pg_session, world, flag_on):
    from services.insight_thresholds import set_threshold

    world["add_invoice"]("H-X", po="PO-Z")
    att = world["add_attachment"]("PURCHASE_ORDER")
    assert _card(att, pg_session, "over_invoicing_history")["status"] == "skipped"

    set_threshold("over_invoicing_pairs", world["tenant_id"], 1.0, pg_session)
    card = _card(att, pg_session, "over_invoicing_history")
    assert card["status"] == "ok"
    assert card["figures"]["threshold_used"] == 1.0


def test_quote_drift_is_skipped_below_two_invoices(pg_session, world, flag_on):
    world["add_invoice"]("Q-1", total=120000.0, invoice_date=date(2026, 3, 5))
    att = world["add_attachment"]("QUOTATION", doc_date=date(2026, 2, 1))

    card = _card(att, pg_session, "quote_drift")
    assert card["status"] == "skipped"
    assert "needs 2" in card["reason"]


def test_quote_drift_reports_the_exact_drift_at_the_threshold(pg_session, world, flag_on):
    world["add_invoice"]("Q-1", total=110000.0, invoice_date=date(2026, 3, 5))
    world["add_invoice"]("Q-2", total=130000.0, invoice_date=date(2026, 3, 20))
    att = world["add_attachment"]("QUOTATION", doc_date=date(2026, 2, 1), grand_total=100000.0)

    card = _card(att, pg_session, "quote_drift")
    assert card["status"] == "ok"
    assert card["figures"]["quoted_total"] == 100000.0
    assert card["figures"]["average_invoice_since_quote"] == 120000.0
    assert card["figures"]["drift_amount"] == 20000.0
    assert card["figures"]["drift_percent"] == 20.0
    assert card["figures"]["invoices_since_quote"] == 2.0


def test_repeat_short_delivery_is_skipped_below_three_challans(pg_session, world, flag_on):
    world["add_attachment"]("DELIVERY_NOTE", doc_number="DC-1")
    att = world["add_attachment"]("DELIVERY_NOTE", doc_number="DC-2")

    card = _card(att, pg_session, "repeat_short_delivery")
    assert card["status"] == "skipped"
    assert "needs 3" in card["reason"]


def test_repeat_short_delivery_counts_the_short_lines_at_the_threshold(pg_session, world, flag_on):
    short_finding = {
        "card": "delivery_vs_order",
        "evidence": {"direction": "short_delivery", "description": "Corrugated boxes"},
    }
    for i in (1, 2):
        att = world["add_attachment"]("DELIVERY_NOTE", doc_number=f"DC-{i}")
        att.insights = {"findings": [short_finding]}
        pg_session.add(att)
    pg_session.commit()
    att = world["add_attachment"]("DELIVERY_NOTE", doc_number="DC-3")

    card = _card(att, pg_session, "repeat_short_delivery")
    assert card["status"] == "ok"
    assert card["figures"]["delivery_notes_on_file"] == 3.0
    assert card["figures"]["short_delivered_lines"] == 2.0
    assert card["figures"]["threshold_used"] == 3.0


def test_contract_deviations_needs_two_invoices_and_reports_the_window(pg_session, world, flag_on):
    att = world["add_attachment"](
        "CONTRACT", extracted_json={"payment_terms": "Net 30"}
    )
    world["add_invoice"]("C-1", invoice_date=date(2026, 3, 1), due=date(2026, 3, 31))
    assert _card(att, pg_session, "contract_deviations")["status"] == "skipped"

    world["add_invoice"]("C-2", invoice_date=date(2026, 3, 1), due=date(2026, 4, 15))
    card = _card(att, pg_session, "contract_deviations")
    assert card["status"] == "ok"
    assert card["figures"]["contract_payment_days"] == 30.0
    assert card["figures"]["invoices_checked"] == 2.0
    assert card["figures"]["invoices_off_contract"] == 1.0
    assert card["findings"][0]["evidence"]["deviations"][0]["invoice_number"] == "C-2"


def test_partial_delivery_balance_needs_the_order_number(pg_session, world, flag_on):
    att = world["add_attachment"]("DELIVERY_NOTE", extracted_json={"items": [{"quantity": 10}]})
    assert _card(att, pg_session, "partial_delivery_balance")["status"] == "skipped"

    att2 = world["add_attachment"](
        "DELIVERY_NOTE",
        extracted_json={"po_number": "PO-99", "items": [{"description": "Boxes", "quantity": 10}]},
    )
    world["add_invoice"]("D-1", total=5000.0, po="PO-99")
    card = _card(att2, pg_session, "partial_delivery_balance")
    assert card["status"] == "ok"
    assert card["figures"]["invoiced_against_order"] == 5000.0


# --- every skipped card is reported to the user (30.12) ---------------------


def test_the_gaps_card_lists_every_skipped_async_card(pg_session, world, flag_on):
    att = world["add_attachment"]("PURCHASE_ORDER")
    block = ai.build_insight_block(att, pg_session, world["tenant_id"], stage="async")
    gaps = next(c for c in block["cards"] if c["card"] == "confidence_gaps")
    reported = {c["card"] for c in gaps["evidence"]["checks_not_run"]}
    assert {"over_invoicing_history", "cash_out_timing"} <= reported
    assert all(c["reason"] for c in gaps["evidence"]["checks_not_run"])
