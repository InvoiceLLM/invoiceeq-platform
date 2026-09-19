"""Feature 34 (ATLAS) task 34.4 — vendor statement reconciliation.

Spec: `docs/feature_34_atlas.md` §3.2 · decision D18.

The four buckets, each printed from the server's own rows, and each asserted
here against real `invoice` rows on the dev Postgres (hard rule 2). The
comparison itself is deterministic code, and the tests that matter most are the
ones that prove it stays that way: the same invoice number printed two different
ways still matches, two amounts that differ by ₹2,000 never quietly agree, and a
statement in another currency is refused rather than converted.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from models import Invoice, Tenant
from services.atlas_capabilities import AtlasCapability
from services.atlas_contract import CurrencyBlendError, validate_recommendation
from services.atlas_recon import (
    LedgerLine,
    StatementLine,
    ledger_lines_for_vendor,
    normalise_invoice_number,
    recon_recommendations,
    reconcile,
)
from tests.atlas_pg import open_session, postgres_only, unique_tag

VENDOR = "Shree Packaging Pvt Ltd"


@pytest.fixture(scope="module")
def pg_session():
    session = open_session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def pg(pg_session):
    tag = unique_tag()
    tenant = Tenant(name=f"atlas-recon-{tag}", domain=f"atlas-recon-{tag}.test")
    pg_session.add(tenant)
    pg_session.commit()
    pg_session.refresh(tenant)
    written: list = []
    try:
        yield pg_session, tenant, written
    finally:
        pg_session.rollback()
        for row in written:
            pg_session.delete(row)
        pg_session.commit()
        pg_session.delete(tenant)
        pg_session.commit()


def _invoice(session, written, tenant, number, total, **fields):
    inv = Invoice(
        tenant_id=tenant.id,
        file_path=f"tests/{uuid4().hex}.pdf",
        vendor_name=fields.get("vendor_name", VENDOR),
        invoice_number=number,
        grand_total=total,
        currency=fields.get("currency", "INR"),
        status=fields.get("status", "AUDIT_REQUIRED"),
        flow_direction="INBOUND",
        invoice_date=fields.get("invoice_date", date(2026, 8, 12)),
    )
    session.add(inv)
    session.commit()
    session.refresh(inv)
    written.append(inv)
    return inv


def _statement(number, amount, **fields):
    return StatementLine(
        invoice_number=number,
        amount=Decimal(str(amount)),
        currency=fields.get("currency", "INR"),
        line_date=fields.get("line_date"),
        raw_text=fields.get("raw_text"),
    )


# ═════════════════════════════════════════════════════════════════════════════
# Matching
# ═════════════════════════════════════════════════════════════════════════════

def test_invoice_numbers_match_across_printing_conventions():
    """One side pads and prefixes, the other does not. Same invoice."""
    assert normalise_invoice_number("INV #001041 ") == normalise_invoice_number("inv-1041")
    assert normalise_invoice_number("") == ""
    assert normalise_invoice_number(None) == ""


def test_an_unnumbered_statement_row_is_never_guessed_at():
    """An empty key matching anything would join every unnumbered row to every other."""
    result = reconcile(
        [_statement(None, 5000)],
        [LedgerLine(uuid4(), "1041", Decimal("5000"), "INR")],
        vendor_name=VENDOR,
        currency="INR",
    )
    assert result.unmatchable and not result.matched
    assert result.we_show_they_do_not  # ours is still unaccounted for, honestly


def test_a_statement_in_another_currency_is_refused_not_converted():
    """§7.4 / D32 — there is no rate in this system, so there is no answer."""
    with pytest.raises(CurrencyBlendError):
        reconcile(
            [_statement("1041", 5000, currency="USD")],
            [LedgerLine(uuid4(), "1041", Decimal("5000"), "INR")],
            vendor_name=VENDOR,
            currency="INR",
        )


def test_digits_only_matching_refuses_to_guess_when_it_is_ambiguous():
    """Two candidates for the same digits is a guess, and a guess that reports
    agreement is worse than a finding that says "I could not match this"."""
    ours_a = LedgerLine(uuid4(), "INV-1041", Decimal("5000"), "INR")
    ours_b = LedgerLine(uuid4(), "CN-1041", Decimal("5000"), "INR")
    result = reconcile(
        [_statement("1041", 5000)],
        [ours_a, ours_b],
        vendor_name=VENDOR,
        currency="INR",
    )
    assert not result.matched
    assert [s.invoice_number for s in result.they_show_we_do_not] == ["1041"]
    assert len(result.we_show_they_do_not) == 2


def test_digits_only_matching_pairs_an_unambiguous_prefix_difference():
    """Their template prefixes and pads; our extraction did not. One invoice."""
    ours = LedgerLine(uuid4(), "1041", Decimal("5000"), "INR")
    result = reconcile(
        [_statement("INV-01041", 5000)], [ours], vendor_name=VENDOR, currency="INR"
    )
    assert [p.ledger.invoice_number for p in result.matched] == ["1041"]


# ═════════════════════════════════════════════════════════════════════════════
# The four buckets, off real rows
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_the_four_buckets_are_printed_from_the_servers_own_rows(pg):
    session, tenant, written = pg
    _invoice(session, written, tenant, "1041", 50000.0)   # matches
    _invoice(session, written, tenant, "1042", 50000.0)   # amount differs
    ours_only = _invoice(session, written, tenant, "1043", 12000.0)  # they omit it

    ledger = ledger_lines_for_vendor(session, tenant.id, VENDOR)
    assert {row.invoice_number for row in ledger} == {"1041", "1042", "1043"}

    result = reconcile(
        [
            _statement("INV-01041", 50000, raw_text="INV-01041  50,000.00"),
            _statement("1042", 48000),
            _statement("9999", 7500),  # theirs only
        ],
        ledger,
        vendor_name=VENDOR,
        currency="INR",
    )

    assert [p.ledger.invoice_number for p in result.matched] == ["1041"]
    assert [d.ledger.invoice_number for d in result.amount_differs] == ["1042"]
    assert [s.invoice_number for s in result.they_show_we_do_not] == ["9999"]
    assert [row.invoice_id for row in result.we_show_they_do_not] == [ours_only.id]
    assert not result.agrees


@postgres_only
def test_a_clean_statement_produces_no_lines_at_all(pg):
    """Agreement is not work (§5.2: volume is how a product trains users to ignore it)."""
    session, tenant, written = pg
    _invoice(session, written, tenant, "2001", 1000.0)
    _invoice(session, written, tenant, "2002", 2000.0)
    result = reconcile(
        [_statement("2001", 1000), _statement("2002", 2000)],
        ledger_lines_for_vendor(session, tenant.id, VENDOR),
        vendor_name=VENDOR,
        currency="INR",
    )
    assert result.agrees
    assert recon_recommendations(result, document_id="stmt-1") == []


@postgres_only
def test_a_short_payment_names_its_likely_reason(pg):
    """§3.2: name the likely reason, do not just flag a gap."""
    session, tenant, written = pg
    _invoice(session, written, tenant, "3001", 50000.0)
    result = reconcile(
        [_statement("3001", 49000)],
        ledger_lines_for_vendor(session, tenant.id, VENDOR),
        vendor_name=VENDOR,
        currency="INR",
    )
    line = recon_recommendations(result, document_id="stmt-2")[0]
    assert line.capability is AtlasCapability.AUDIT
    assert "two percent" in line.why.text
    # The gap itself is a figure with its working, never a bare assertion.
    assert any(f.computation == "their amount less ours" for f in line.why.figures)
    assert "1,000.00" in line.why.text


@postgres_only
def test_every_recon_line_passes_the_contract_and_asks_for_nothing_it_cannot_show(pg):
    session, tenant, written = pg
    _invoice(session, written, tenant, "4001", 50000.0)
    _invoice(session, written, tenant, "4002", 25000.0)
    result = reconcile(
        [_statement("4001", 47500), _statement("8888", 9000)],
        ledger_lines_for_vendor(session, tenant.id, VENDOR),
        vendor_name=VENDOR,
        currency="INR",
    )
    lines = recon_recommendations(result, document_id="stmt-3")
    assert lines
    for line in lines:
        validate_recommendation(line)
        assert line.verify.document_id == "stmt-3"
        assert line.certainty.value == "uncertain" and line.why.doubt


@postgres_only
def test_asking_the_vendor_for_a_missing_invoice_leaves_the_company(pg):
    """§5.3 / D29 — a drafted message to a vendor is never batchable, ever."""
    session, tenant, written = pg
    _invoice(session, written, tenant, "5001", 1000.0)
    result = reconcile(
        [_statement("5001", 1000), _statement("7777", 4000)],
        ledger_lines_for_vendor(session, tenant.id, VENDOR),
        vendor_name=VENDOR,
        currency="INR",
    )
    line = next(
        line for line in recon_recommendations(result, document_id="stmt-4")
        if line.skill == "vendor_statement_they_show_we_do_not"
    )
    assert line.reversibility.value == "leaves_company"
    assert line.batchable is False
