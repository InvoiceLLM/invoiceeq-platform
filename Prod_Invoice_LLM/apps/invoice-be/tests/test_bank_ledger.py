"""Feature 30 task 30.0c — the bank ledger: extractor output -> `bank_statement_line`.

Verification plan 30.0c: "Fixture statement -> N ledger rows with exact
debit / credit / balance; `statement_date` set."

Real Postgres (hard rule 2): the rows are a real table with a real
`attachment_id` FK-shaped column, and the replace-on-re-extract behaviour is a
DELETE + INSERT in one transaction.

No OCR and no model: the fixture is the `extracted_json` an extraction would
produce, which is exactly the boundary this module owns.
"""
import os
from datetime import date
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from models import BankStatementLine, ChatAttachment, ChatSession, Invoice  # noqa: E402
from services import bank_ledger as bl  # noqa: E402

#: Six rows, the §8.9 30.5 fixture shape: four that will match, one unmatched
#: debit, one unmatched credit.
STATEMENT_JSON = {
    "doc_type": "STATEMENT_OF_ACCOUNT",
    "party_name": "HDFC Bank",
    "statement_date": "2026-03-31",
    "currency": "INR",
    "statement_lines": [
        {"line_date": "2026-03-04", "narration": "NEFT SHREE PACKAGING", "debit": 123200.0, "balance": 876800.0, "utr_ref": "UTR0001"},
        {"line_date": "2026-03-09", "narration": "RTGS BHARAT STEELS", "debit": 45000.0, "balance": 831800.0, "utr_ref": "UTR0002"},
        {"line_date": "2026-03-14", "narration": "UPI LUNA TRADERS", "debit": 8000.5, "balance": 823799.5, "utr_ref": "UTR0003"},
        {"line_date": "2026-03-19", "narration": "NEFT CR ACME CUSTOMER", "credit": 250000.0, "balance": 1073799.5, "utr_ref": "UTR0004"},
        {"line_date": "2026-03-22", "narration": "NEFT SHREE PACKAGING", "debit": 123200.0, "balance": 950599.5, "utr_ref": "UTR0005"},
        {"line_date": "2026-03-28", "narration": "BANK CHARGE - SMS ALERTS", "debit": 59.0, "balance": 950540.5, "utr_ref": None},
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


@pytest.fixture(name="statement")
def statement_fixture(pg_session):
    tenant_id = uuid4()
    chat = ChatSession(tenant_id=tenant_id, title="F30 ledger")
    pg_session.add(chat)
    pg_session.commit()
    pg_session.refresh(chat)

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

    yield {"tenant_id": tenant_id, "session": chat, "attachment": att}

    for row in pg_session.exec(
        select(BankStatementLine).where(BankStatementLine.tenant_id == tenant_id)
    ).all():
        pg_session.delete(row)
    for row in pg_session.exec(select(Invoice).where(Invoice.tenant_id == tenant_id)).all():
        pg_session.delete(row)
    pg_session.commit()
    pg_session.delete(att)
    pg_session.delete(chat)
    pg_session.commit()


# --- parsing ---------------------------------------------------------------


def test_parse_reads_every_row_in_printed_order():
    lines = bl.parse_statement_lines(STATEMENT_JSON)
    assert len(lines) == 6
    assert lines[0]["narration"] == "NEFT SHREE PACKAGING"
    assert lines[0]["debit"] == 123200.0
    assert lines[0]["credit"] is None  # an empty column is None, never 0
    assert lines[3]["credit"] == 250000.0
    assert lines[3]["debit"] is None
    assert lines[-1]["balance"] == 950540.5


def test_a_printed_zero_is_not_an_empty_column():
    lines = bl.parse_statement_lines(
        {"statement_lines": [{"narration": "REVERSAL", "debit": 0.0, "credit": None}]}
    )
    assert lines[0]["debit"] == 0.0
    assert lines[0]["credit"] is None


def test_it_falls_back_to_referenced_documents_for_an_older_extraction():
    """A statement read before `statement_lines` existed still has references."""
    lines = bl.parse_statement_lines(
        {
            "referenced_documents": [
                {"doc_number": "INV-1", "doc_date": "2026-03-04", "amount": 1000.0},
                {"doc_number": "CN-1", "doc_date": "2026-03-05", "amount": -250.0},
            ]
        }
    )
    assert [l["source"] for l in lines] == ["referenced_documents", "referenced_documents"]
    assert lines[0]["debit"] == 1000.0 and lines[0]["credit"] is None
    assert lines[1]["credit"] == 250.0 and lines[1]["debit"] is None


@pytest.mark.parametrize(
    "raw,expected",
    [("2026-03-31", date(2026, 3, 31)), ("31/03/2026", date(2026, 3, 31)), ("garbage", None), (None, None)],
)
def test_date_parsing_never_guesses(raw, expected):
    assert bl._to_date(raw) == expected


def test_statement_date_prefers_what_the_document_printed():
    assert bl.detect_statement_date(STATEMENT_JSON, []) == date(2026, 3, 31)


def test_statement_date_falls_back_to_the_latest_row_never_to_today():
    lines = bl.parse_statement_lines(STATEMENT_JSON)
    assert bl.detect_statement_date({"statement_lines": STATEMENT_JSON["statement_lines"]}, lines) == date(2026, 3, 28)
    assert bl.detect_statement_date({}, []) is None


def test_bank_charges_are_labelled_not_dropped():
    assert bl.is_bank_charge("BANK CHARGE - SMS ALERTS") is True
    assert bl.is_bank_charge("NEFT SHREE PACKAGING") is False


# --- landing ---------------------------------------------------------------


def test_landing_writes_the_rows_and_the_statement_date(pg_session, statement):
    created = bl.land_statement_lines(statement["attachment"], pg_session)
    assert len(created) == 6

    rows = bl.statement_lines_for(statement["attachment"].id, pg_session)
    assert [r.debit for r in rows] == [123200.0, 45000.0, 8000.5, None, 123200.0, 59.0]
    assert [r.credit for r in rows] == [None, None, None, 250000.0, None, None]
    assert bl.closing_balance(rows) == 950540.5
    assert all(r.match_status == "UNMATCHED" for r in rows)
    assert all(r.statement_date == date(2026, 3, 31) for r in rows)

    pg_session.refresh(statement["attachment"])
    assert statement["attachment"].statement_date == date(2026, 3, 31)


def test_re_landing_replaces_rather_than_doubling(pg_session, statement):
    bl.land_statement_lines(statement["attachment"], pg_session)
    bl.land_statement_lines(statement["attachment"], pg_session)
    assert len(bl.statement_lines_for(statement["attachment"].id, pg_session)) == 6


def test_a_confirmed_match_survives_a_re_extraction(pg_session, statement):
    inv = Invoice(
        tenant_id=statement["tenant_id"],
        invoice_number="INV-BL-1",
        file_path="test/bl-1.pdf",
        vendor_name="Shree Packaging Pvt Ltd",
        grand_total=123200.0,
    )
    pg_session.add(inv)
    pg_session.commit()
    pg_session.refresh(inv)

    rows = bl.land_statement_lines(statement["attachment"], pg_session)
    rows[0].matched_invoice_id = inv.id
    rows[0].match_status = "MATCHED"
    rows[0].match_confidence = "high"
    pg_session.add(rows[0])
    pg_session.commit()

    bl.land_statement_lines(statement["attachment"], pg_session)
    after = bl.statement_lines_for(statement["attachment"].id, pg_session)
    assert after[0].matched_invoice_id == inv.id
    assert after[0].match_status == "MATCHED"
    # ... and the rows nobody matched are still open questions.
    assert after[1].match_status == "UNMATCHED"


def test_an_unreadable_statement_lands_nothing_and_says_nothing(pg_session, statement):
    statement["attachment"].extracted_json = {"doc_type": "STATEMENT_OF_ACCOUNT"}
    pg_session.add(statement["attachment"])
    pg_session.commit()

    assert bl.land_statement_lines(statement["attachment"], pg_session) == []
    pg_session.refresh(statement["attachment"])
    assert statement["attachment"].statement_date is None


def test_the_reference_schema_can_actually_carry_a_statement():
    """BE Gap 493: the cards read fields the REFERENCE schema did not have.

    Asserted on the schema itself, because the defect was not in any card's
    arithmetic — it was that the data never arrived.
    """
    from agents.extraction_agent import ReferenceDocExtractionSchema

    fields = set(ReferenceDocExtractionSchema.model_fields)
    assert {"payment_terms", "delivery_terms", "notes", "referenced_documents",
            "statement_lines", "statement_date"} <= fields

    parsed = ReferenceDocExtractionSchema(**STATEMENT_JSON)
    assert parsed.statement_lines[0].debit == 123200.0
    assert parsed.statement_lines[0].credit is None
