"""Gap 502 (credit-note line arithmetic is sign-flipped) and Gap 503 (Layer 3
near-duplicate soft alert). Found 2026-09-09 by the founder on the VPI demo
tenant: BHF-CN-2010 raised `line_item_calculation_mismatch` (-36,250 vs
36,250) and NAT-2006 / NAT-2007 (same vendor, date, total, different number)
raised nothing.

The near-duplicate half runs on real Postgres (CONVENTIONS hard rule 2): the
predicate is a date-equality plus a numeric band, which is exactly the kind of
comparison SQLite gets wrong.
"""
from datetime import date, datetime
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from config import get_settings
from models import Invoice, Tenant
from queue_worker.handlers import find_near_duplicate
from utils.verification_tools import verify_line_items_math

# ------------------------------------------------------------------ Gap 502
_CREDIT_LINE = [{"description": "Hex Bolts M10x40, box 100", "quantity": 25, "unit_price": 1450.0, "amount": -36250.0}]


def test_credit_note_line_with_negative_amount_is_not_flagged():
    assert verify_line_items_math(_CREDIT_LINE, -36250.0, doc_type="CREDIT_NOTE") is None
    assert verify_line_items_math(_CREDIT_LINE, -36250.0, doc_type="DEBIT_NOTE") is None


def test_the_same_line_on_a_plain_invoice_is_still_flagged():
    """Unchanged behaviour for every other document type, including None."""
    for doc_type in (None, "INVOICE", "PROFORMA_INVOICE"):
        alert = verify_line_items_math(_CREDIT_LINE, -36250.0, doc_type=doc_type)
        assert alert is not None and alert["type"] == "line_item_calculation_mismatch"


def test_a_credit_note_with_genuinely_wrong_arithmetic_is_still_flagged():
    bad = [{"description": "x", "quantity": 25, "unit_price": 1450.0, "amount": -30000.0}]
    assert verify_line_items_math(bad, -30000.0, doc_type="CREDIT_NOTE")["type"] == "line_item_calculation_mismatch"


# ------------------------------------------------------------------ Gap 503
def _pg_or_skip():
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
    with Session(_pg_or_skip()) as session:
        yield session


def _tenant(pg, tag):
    t = Tenant(id=uuid4(), name=f"G503-{tag}", domain=f"g503-{tag}.invalid", billing_plan="free", free_invoices_remaining=50)
    pg.add(t)
    pg.commit()
    return t


def _invoice(pg, tenant, number, total=79956.80, vendor="National MRO Traders", when=date(2026, 8, 19), status="COMPLETED", flow="INBOUND"):
    row = Invoice(
        id=uuid4(), tenant_id=tenant.id, file_path=f"{tenant.id}/{number}.pdf", vendor_name=vendor,
        invoice_number=number, grand_total=total, currency="INR", invoice_date=when,
        created_at=datetime.utcnow(), status=status, flow_direction=flow,
    )
    pg.add(row)
    pg.commit()
    return row


def _cleanup(pg, tenant_ids):
    pg.rollback()
    for tid in tenant_ids:
        for row in pg.exec(select(Invoice).where(Invoice.tenant_id == tid)).all():
            pg.delete(row)
        t = pg.get(Tenant, tid)
        if t:
            pg.delete(t)
    pg.commit()


def _extracted(number, total=79956.80, vendor="national mro traders", when="2026-08-19"):
    return {"vendor_name": vendor, "invoice_number": number, "grand_total": total, "invoice_date": when}


def test_same_vendor_date_total_different_number_is_a_near_duplicate(pg):
    tag = uuid4().hex[:8]
    t = _tenant(pg, tag)
    try:
        first = _invoice(pg, t, "NAT-2006")
        second = _invoice(pg, t, "NAT-2007")  # the row being processed
        hit = find_near_duplicate(pg, second, _extracted("NAT-2007"))
        assert hit is not None and hit.id == first.id
    finally:
        _cleanup(pg, [t.id])


def test_same_number_is_left_to_layer_2(pg):
    tag = uuid4().hex[:8]
    t = _tenant(pg, tag)
    try:
        _invoice(pg, t, "NAT-2006")
        second = _invoice(pg, t, "NAT-2006")
        assert find_near_duplicate(pg, second, _extracted("NAT-2006")) is None
    finally:
        _cleanup(pg, [t.id])


def test_different_date_or_total_or_vendor_is_not_a_near_duplicate(pg):
    """OM -2000 (9 Jul) and OM -2001 (16 Aug) share a total and must NOT flag."""
    tag = uuid4().hex[:8]
    t = _tenant(pg, tag)
    try:
        _invoice(pg, t, "OM -2000", total=41654.0, vendor="Om Stationery Mart", when=date(2026, 7, 9))
        second = _invoice(pg, t, "OM -2001", total=41654.0, vendor="Om Stationery Mart", when=date(2026, 8, 16))
        assert find_near_duplicate(pg, second, _extracted("OM -2001", 41654.0, "Om Stationery Mart", "2026-08-16")) is None
        assert find_near_duplicate(pg, second, _extracted("OM -2001", 41654.0, "Om Stationery Mart", "2026-07-09")) is not None
        assert find_near_duplicate(pg, second, _extracted("OM -2001", 41655.0, "Om Stationery Mart", "2026-07-09")) is None
        assert find_near_duplicate(pg, second, _extracted("OM -2001", 41654.0, "Someone Else", "2026-07-09")) is None
    finally:
        _cleanup(pg, [t.id])


def test_other_tenants_duplicate_rows_and_outbound_are_ignored(pg):
    tag = uuid4().hex[:8]
    a, b = _tenant(pg, tag + "a"), _tenant(pg, tag + "b")
    try:
        _invoice(pg, b, "NAT-2006")                       # other tenant
        _invoice(pg, a, "NAT-2005", status="DUPLICATE")   # a duplicate pointer row
        _invoice(pg, a, "NAT-2004", flow="OUTBOUND")      # issued, not received
        second = _invoice(pg, a, "NAT-2007")
        assert find_near_duplicate(pg, second, _extracted("NAT-2007")) is None
    finally:
        _cleanup(pg, [a.id, b.id])


def test_missing_date_or_total_never_raises(pg):
    tag = uuid4().hex[:8]
    t = _tenant(pg, tag)
    try:
        row = _invoice(pg, t, "NAT-2007")
        assert find_near_duplicate(pg, row, {"vendor_name": "x", "invoice_number": "y"}) is None
        assert find_near_duplicate(pg, row, _extracted("NAT-2007", when="not a date")) is None
    finally:
        _cleanup(pg, [t.id])
