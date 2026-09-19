"""BE Gap 698 -- a turn rescued by a fallback must still get its full record.

The defect: `_harvest_invoice_ids_via_companion_query()` recovers invoice ids by
re-running the generated SQL's predicates, which is useless on exactly the turns
a deterministic fallback rescued -- the query being re-run is the one that
matched nothing. No ids meant no Gap 310 full-record block, so the model saw only
the fallback's five fixed columns and could not answer about any other field.

Measured on `eu_currency_confusion_trap`: asked which currency an invoice was
payable in, the model was handed a table with no `currency` column and answered
"the currency is unspecified", while the row said EUR.
"""

import os
from uuid import UUID, uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from models import Invoice
from agents.query_agent import (
    _invoice_ids_from_result_table,
    lookup_invoice_by_number_fallback,
)

TENANT = "33333333-3333-3333-3333-333333333333"
OTHER_TENANT = "44444444-4444-4444-4444-444444444444"

# Same engine selection and the same Gap 525/570 guard as
# `tests/test_chat_sql_quality.py` -- this fixture also drops every table.
postgres_test_url = os.getenv("TEST_DATABASE_URL")
if postgres_test_url:
    from urllib.parse import urlparse as _urlparse

    _parsed = _urlparse(postgres_test_url)
    assert _parsed.hostname in ("localhost", "127.0.0.1"), (
        "Gap 525/570 security guard: TEST_DATABASE_URL must point to localhost or 127.0.0.1."
    )
    assert "test" in (_parsed.path or "").lower(), (
        "Gap 525/570 security guard: TEST_DATABASE_URL must name a throwaway database."
    )
    engine = create_engine(postgres_test_url)
else:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture()
def seeded_invoice(db_session):
    """One EUR invoice -- the field the fallback's fixed SELECT omits."""
    invoice = Invoice(
        id=uuid4(),
        tenant_id=UUID(TENANT),  # a UUID column; a str raises in the bind processor
        file_path="mock/rit.pdf",
        invoice_number="GAP698-0001",
        vendor_name="Rhein Industrietechnik GmbH",
        grand_total=9428.00,
        currency="EUR",
        status="COMPLETED",
        flow_direction="INBOUND",
    )
    db_session.add(invoice)
    db_session.commit()
    return str(invoice.id)


def test_ids_are_read_from_the_table_the_fallback_produced(db_session, seeded_invoice):
    """The whole point: the fallback's own output yields the id, so the
    full-record block can be built for a turn whose SQL matched nothing."""
    table = lookup_invoice_by_number_fallback("GAP698-0001", TENANT, db_session)
    assert table, "fallback did not find the seeded invoice"
    # The fallback's fixed column list is what caused the defect. Assert it
    # really does omit the field the question was about, so this test fails
    # loudly if someone "fixes" the gap by widening that SELECT instead.
    assert "currency" not in table.lower()

    assert _invoice_ids_from_result_table(table, TENANT, db_session) == [seeded_invoice]


def test_a_name_mismatch_no_longer_costs_the_full_record(db_session, seeded_invoice):
    """The live shape: the user typed the vendor without its legal suffix, the
    generated SQL matched nothing, and the invoice-number fallback rescued it.
    Case-insensitive, like the fallback itself."""
    table = lookup_invoice_by_number_fallback("gap698-0001", TENANT, db_session)
    assert _invoice_ids_from_result_table(table, TENANT, db_session) == [seeded_invoice]


def test_another_tenant_never_resolves(db_session, seeded_invoice):
    """Tenant isolation holds on the new lookup, not only on the fallback."""
    table = lookup_invoice_by_number_fallback("GAP698-0001", TENANT, db_session)
    assert _invoice_ids_from_result_table(table, OTHER_TENANT, db_session) == []


@pytest.mark.parametrize(
    "table",
    [
        "",
        None,
        "No records found matching the query criteria.",
        "\n\nvendor_name | grand_total\n--- | ---\nAcme | 10.00",  # no invoice_number column
        "\n\ninvoice_number\n---",  # header only, no rows
        "not a table at all",
    ],
)
def test_unreadable_input_returns_empty_and_never_raises(db_session, table):
    """Best-effort, the same contract as the companion harvest it sits beside."""
    assert _invoice_ids_from_result_table(table, TENANT, db_session) == []


def test_an_unknown_invoice_number_resolves_to_nothing(db_session):
    table = "\n\ninvoice_number | vendor_name\n--- | ---\nNOPE-9999 | Ghost Ltd"
    assert _invoice_ids_from_result_table(table, TENANT, db_session) == []
