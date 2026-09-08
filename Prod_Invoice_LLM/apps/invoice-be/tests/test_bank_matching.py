"""Feature 30 task 30.5 — bank matching (ruling R5) and the two statement cards.

Verification plan 30.5: "6-line statement fixture: 4 matched within ±1 / ±5 d,
1 unmatched debit flagged 'possible duplicate payment' when the invoice is
already PAID, 1 unmatched credit; closing balance and 'as of' date rendered."

Real Postgres: the ledger rows, the invoices and the `v_overdue` view the
cash-cover card reads are all real. No model anywhere — matching is arithmetic.

Gap 492 is asserted: matching writes `bank_statement_line` and never `invoice`.
"""
import os
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from models import BankStatementLine, ChatAttachment, ChatMessage, ChatSession, Insight, Invoice  # noqa: E402
from services import attachment_insights as ai  # noqa: E402
from services import bank_ledger as bl  # noqa: E402
from services import bank_matching as bm  # noqa: E402

STATEMENT_DATE = date(2026, 3, 31)

STATEMENT_JSON = {
    "doc_type": "STATEMENT_OF_ACCOUNT",
    "party_name": "HDFC Bank",
    "statement_date": "2026-03-31",
    "currency": "INR",
    "statement_lines": [
        # 1. exact match to INV-A (100000, due 2026-03-05, Shree Packaging)
        {"line_date": "2026-03-04", "narration": "NEFT SHREE PACKAGING PVT LTD", "debit": 100000.0, "balance": 900000.0, "utr_ref": "U1"},
        # 2. within +/- 1 currency unit of INV-B (45000.00 vs 45000.75)
        {"line_date": "2026-03-09", "narration": "RTGS BHARAT STEELS", "debit": 45000.75, "balance": 854999.25, "utr_ref": "U2"},
        # 3. within +/- 5 days of INV-C's due date (due 03-14, paid 03-18)
        {"line_date": "2026-03-18", "narration": "UPI LUNA TRADERS", "debit": 8000.5, "balance": 846998.75, "utr_ref": "U3"},
        # 4. a customer receipt against the OUTBOUND invoice INV-D
        {"line_date": "2026-03-19", "narration": "NEFT CR ACME CUSTOMER", "credit": 250000.0, "balance": 1096998.75, "utr_ref": "U4"},
        # 5. matches INV-PAID, which our records already say is paid
        {"line_date": "2026-03-22", "narration": "NEFT SHREE PACKAGING PVT LTD", "debit": 61000.0, "balance": 1035998.75, "utr_ref": "U5"},
        # 6. nothing on file at all
        {"line_date": "2026-03-28", "narration": "NEFT UNKNOWN PARTY", "debit": 17777.0, "balance": 1018221.75, "utr_ref": "U6"},
    ],
}


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
    chat = ChatSession(tenant_id=tenant_id, title="F30 bank")
    pg_session.add(chat)
    pg_session.commit()
    pg_session.refresh(chat)

    def _inv(number, vendor, total, due, *, direction="INBOUND", status="PROCESSING", paid=None, customer=None):
        inv = Invoice(
            tenant_id=tenant_id,
            invoice_number=number,
            file_path=f"test/{number}.pdf",
            vendor_name=vendor,
            customer_name=customer,
            grand_total=total,
            currency="INR",
            invoice_date=due - timedelta(days=30),
            due_date=due,
            status=status,
            paid_at=paid,
            flow_direction=direction,
        )
        pg_session.add(inv)
        return inv

    invoices = [
        _inv("INV-A", "Shree Packaging Pvt Ltd", 100000.0, date(2026, 3, 5)),
        _inv("INV-B", "Bharat Steels", 45000.0, date(2026, 3, 10)),
        _inv("INV-C", "Luna Traders", 8000.5, date(2026, 3, 14)),
        _inv("INV-D", None, 250000.0, date(2026, 3, 20), direction="OUTBOUND", customer="Acme Customer"),
        _inv("INV-PAID", "Shree Packaging Pvt Ltd", 61000.0, date(2026, 3, 20),
             status="PAID", paid=datetime(2026, 3, 21)),
    ]
    pg_session.commit()
    for inv in invoices:
        pg_session.refresh(inv)

    att = ChatAttachment(
        tenant_id=tenant_id,
        session_id=chat.id,
        filename="statement.pdf",
        blob_path="",
        doc_type="STATEMENT_OF_ACCOUNT",
        extraction_status="EXTRACTED",
        party_name="HDFC Bank",
        currency="INR",
        extracted_json=STATEMENT_JSON,
    )
    pg_session.add(att)
    pg_session.commit()
    pg_session.refresh(att)
    bl.land_statement_lines(att, pg_session)
    pg_session.refresh(att)

    yield {"tenant_id": tenant_id, "session": chat, "attachment": att, "invoices": invoices}

    for model in (BankStatementLine, Insight):
        for r in pg_session.exec(select(model).where(model.tenant_id == tenant_id)).all():
            pg_session.delete(r)
    for msg in pg_session.exec(select(ChatMessage).where(ChatMessage.session_id == chat.id)).all():
        pg_session.delete(msg)
    pg_session.commit()
    for inv in pg_session.exec(select(Invoice).where(Invoice.tenant_id == tenant_id)).all():
        pg_session.delete(inv)
    pg_session.delete(att)
    pg_session.delete(chat)
    pg_session.commit()


def _match(world, pg_session):
    lines = bl.statement_lines_for(world["attachment"].id, pg_session)
    return bm.match_statement_lines(
        lines, world["invoices"], tenant_id=world["tenant_id"], db_session=pg_session
    ), lines


# --- R5's three rules ------------------------------------------------------


def test_the_six_line_fixture_matches_exactly_as_specified(pg_session, world):
    result, _ = _match(world, pg_session)

    matched = {e["invoice_number"] for e in result["matched"]}
    assert matched == {"INV-A", "INV-B", "INV-C", "INV-D"}
    assert len(result["possible_duplicates"]) == 1
    assert result["possible_duplicates"][0]["invoice_number"] == "INV-PAID"
    assert "already marked paid" in result["possible_duplicates"][0]["reason"]
    assert [e["amount"] for e in result["unmatched_debits"]] == [17777.0]
    assert result["unmatched_credits"] == []


def test_the_tolerances_are_the_r5_numbers_and_are_reported(pg_session, world):
    result, _ = _match(world, pg_session)
    assert result["tolerances"] == {"amount": 1.0, "days": 5, "vendor_must_match": True}


def test_a_tenant_override_widens_the_amount_tolerance(pg_session, world):
    """R5's "per-tenant override", end to end."""
    from services.insight_thresholds import set_threshold

    # 17777.0 vs a new 17700.0 invoice is outside +/- 1 ...
    inv = Invoice(
        tenant_id=world["tenant_id"], invoice_number="INV-WIDE", file_path="test/wide.pdf",
        vendor_name="Unknown Party", grand_total=17700.0, currency="INR",
        invoice_date=date(2026, 2, 26), due_date=date(2026, 3, 28), flow_direction="INBOUND",
    )
    pg_session.add(inv)
    pg_session.commit()
    pg_session.refresh(inv)
    invoices = world["invoices"] + [inv]
    lines = bl.statement_lines_for(world["attachment"].id, pg_session)

    tight = bm.match_statement_lines(lines, invoices, tenant_id=world["tenant_id"], db_session=pg_session)
    assert "INV-WIDE" not in {e.get("invoice_number") for e in tight["matched"]}

    # ... and inside a tenant override of 100.
    set_threshold("bank_amount_tolerance", world["tenant_id"], 100.0, pg_session)
    wide = bm.match_statement_lines(lines, invoices, tenant_id=world["tenant_id"], db_session=pg_session)
    assert "INV-WIDE" in {e.get("invoice_number") for e in wide["matched"]}
    assert wide["tolerances"]["amount"] == 100.0

    from models import TenantInsightSetting

    for r in pg_session.exec(
        select(TenantInsightSetting).where(TenantInsightSetting.tenant_id == world["tenant_id"])
    ).all():
        pg_session.delete(r)
    pg_session.commit()


def test_the_vendor_clause_is_load_bearing(pg_session, world):
    """Same amount, same week, wrong supplier -> no match."""
    lines = bl.statement_lines_for(world["attachment"].id, pg_session)
    impostor = Invoice(
        tenant_id=world["tenant_id"], invoice_number="INV-IMPOSTOR", file_path="test/imp.pdf",
        vendor_name="Totally Different Traders", grand_total=17777.0, currency="INR",
        invoice_date=date(2026, 2, 26), due_date=date(2026, 3, 28), flow_direction="INBOUND",
    )
    pg_session.add(impostor)
    pg_session.commit()
    pg_session.refresh(impostor)

    result = bm.match_statement_lines(
        lines, world["invoices"] + [impostor], tenant_id=world["tenant_id"], db_session=pg_session
    )
    assert "INV-IMPOSTOR" not in {e.get("invoice_number") for e in result["matched"]}
    assert [e["amount"] for e in result["unmatched_debits"]] == [17777.0]


def test_a_debit_never_matches_an_outbound_invoice(pg_session, world):
    """A payment out cannot settle a bill we sent."""
    result, _ = _match(world, pg_session)
    credit_matches = [e for e in result["matched"] if e["side"] == "credit"]
    assert [e["invoice_number"] for e in credit_matches] == ["INV-D"]
    assert all(e["invoice_number"] != "INV-D" for e in result["matched"] if e["side"] == "debit")


def test_two_rows_matching_one_bill_are_flagged_as_a_double_payment(pg_session, world):
    lines = bl.statement_lines_for(world["attachment"].id, pg_session)
    # A second debit identical to line 1.
    extra = BankStatementLine(
        tenant_id=world["tenant_id"], attachment_id=world["attachment"].id,
        statement_date=STATEMENT_DATE, line_date=date(2026, 3, 6),
        narration="NEFT SHREE PACKAGING PVT LTD", debit=100000.0, balance=800000.0, utr_ref="U7",
    )
    pg_session.add(extra)
    pg_session.commit()
    pg_session.refresh(extra)

    result = bm.match_statement_lines(
        list(lines) + [extra], world["invoices"], tenant_id=world["tenant_id"], db_session=pg_session
    )
    duplicates = [e for e in result["possible_duplicates"] if e.get("duplicate_of_line_id")]
    assert len(duplicates) == 1
    assert duplicates[0]["amount"] == 100000.0


def test_ambiguity_is_reported_rather_than_guessed(pg_session, world):
    lines = bl.statement_lines_for(world["attachment"].id, pg_session)
    twin = Invoice(
        tenant_id=world["tenant_id"], invoice_number="INV-A2", file_path="test/a2.pdf",
        vendor_name="Shree Packaging Pvt Ltd", grand_total=100000.0, currency="INR",
        invoice_date=date(2026, 2, 3), due_date=date(2026, 3, 5), flow_direction="INBOUND",
    )
    pg_session.add(twin)
    pg_session.commit()
    pg_session.refresh(twin)

    result = bm.match_statement_lines(
        lines, world["invoices"] + [twin], tenant_id=world["tenant_id"], db_session=pg_session
    )
    ambiguous = result["ambiguous"]
    assert len(ambiguous) == 1
    assert {c["invoice_number"] for c in ambiguous[0]["candidates"]} == {"INV-A", "INV-A2"}


# --- persistence and Gap 492 ----------------------------------------------


def test_apply_matches_writes_the_ledger_and_nothing_else(pg_session, world):
    statuses_before = {i.invoice_number: i.status for i in world["invoices"]}
    result, lines = _match(world, pg_session)
    changed = bm.apply_matches(result, lines, pg_session)
    # 4 matched + 1 possible duplicate. The unmatched rows are deliberately NOT
    # rewritten: they are already UNMATCHED, and touching them would make every
    # sweep look like a change.
    assert changed == 5

    after = bl.statement_lines_for(world["attachment"].id, pg_session)
    by_ref = {r.utr_ref: r for r in after}
    assert by_ref["U1"].match_status == "MATCHED"
    assert by_ref["U1"].matched_invoice_id is not None
    assert by_ref["U5"].match_status == "POSSIBLE_DUPLICATE"
    assert by_ref["U6"].match_status == "UNMATCHED"

    for inv in world["invoices"]:
        pg_session.refresh(inv)
        assert inv.status == statuses_before[inv.invoice_number]


def test_an_ambiguous_row_is_never_given_an_invoice_id(pg_session, world):
    lines = bl.statement_lines_for(world["attachment"].id, pg_session)
    twin = Invoice(
        tenant_id=world["tenant_id"], invoice_number="INV-A3", file_path="test/a3.pdf",
        vendor_name="Shree Packaging Pvt Ltd", grand_total=100000.0, currency="INR",
        invoice_date=date(2026, 2, 3), due_date=date(2026, 3, 5), flow_direction="INBOUND",
    )
    pg_session.add(twin)
    pg_session.commit()
    result = bm.match_statement_lines(
        lines, world["invoices"] + [twin], tenant_id=world["tenant_id"], db_session=pg_session
    )
    bm.apply_matches(result, lines, pg_session)
    row = next(r for r in bl.statement_lines_for(world["attachment"].id, pg_session) if r.utr_ref == "U1")
    assert row.match_status == "AMBIGUOUS"
    assert row.matched_invoice_id is None


# --- the cards -------------------------------------------------------------


def test_the_sync_bubble_reports_the_match_and_the_as_of_date(pg_session, world, flag_on):
    block = ai.build_insight_block(world["attachment"], pg_session, world["tenant_id"], stage="sync")
    cards = {c["card"]: c for c in block["cards"]}

    assert cards["bank_reconcile"]["status"] == "ok"
    assert cards["bank_reconcile"]["figures"]["matched_count"] == 4.0
    assert cards["bank_reconcile"]["figures"]["closing_balance"] == 1018221.75
    assert cards["bank_reconcile"]["evidence"]["statement_date"] == "2026-03-31"
    assert "as of 2026-03-31" in cards["bank_reconcile"]["title"]

    keys = {f["finding_key"].split(":")[1] for f in block["findings"] if f["card"] == "bank_reconcile"}
    assert "duplicate" in keys and "unmatched_debit" in keys

    # The cash-cover card is async and says so rather than running early.
    assert cards["cash_cover"]["status"] == "skipped"
    assert any(c["card"] == "cash_cover" for c in block["checks_not_run"])


def test_the_async_stage_adds_the_cash_cover_figures(pg_session, world, flag_on):
    block = ai.build_insight_block(world["attachment"], pg_session, world["tenant_id"], stage="async")
    cards = {c["card"]: c for c in block["cards"]}

    assert cards["cash_cover"]["status"] == "ok"
    evidence = cards["cash_cover"]["evidence"]
    assert evidence["as_of"] == "2026-03-31"
    assert evidence["closing_balance"] == 1018221.75
    # Everything is dated from the statement, so a bill due in April is inside
    # the 30-day bucket and one due in June is not.
    assert evidence["due_within_60_days"] >= evidence["due_within_30_days"] >= evidence["due_within_7_days"]


def test_cash_cover_refuses_to_guess_an_as_of_date(pg_session, world, flag_on):
    world["attachment"].statement_date = None
    pg_session.add(world["attachment"])
    pg_session.commit()

    block = ai.build_insight_block(world["attachment"], pg_session, world["tenant_id"], stage="async")
    card = next(c for c in block["cards"] if c["card"] == "cash_cover")
    assert card["status"] == "skipped"
    assert "misleading" in card["reason"]


def test_cash_cover_arithmetic_is_anchored_on_the_statement_date():
    """Unit-level, so the bucket boundaries are pinned without a ledger."""
    figures = bm.cash_cover(
        balance=1000.0,
        overdue_rows=[{"grand_total": 500.0}],
        upcoming_rows=[
            {"grand_total": 100.0, "due_date": date(2026, 4, 3)},   # +3 days
            {"grand_total": 200.0, "due_date": date(2026, 4, 20)},  # +20 days
            {"grand_total": 400.0, "due_date": date(2026, 5, 20)},  # +50 days
            {"grand_total": 800.0, "due_date": date(2026, 8, 1)},   # outside 60
        ],
        statement_date=date(2026, 3, 31),
    )
    assert figures["due_within_7_days"] == 100.0
    assert figures["due_within_30_days"] == 300.0
    assert figures["due_within_60_days"] == 700.0
    assert figures["overdue_total"] == 500.0
    # 300 due + 500 overdue - 1000 balance = -200 -> no shortfall
    assert figures["shortfall_within_30_days"] == -200.0


def test_cash_cover_shortfall_is_none_when_there_is_no_balance():
    figures = bm.cash_cover(None, [], [], date(2026, 3, 31))
    assert figures["closing_balance"] is None
    assert figures["shortfall_within_30_days"] is None
