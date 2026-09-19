"""Feature 34 (ATLAS) task 34.5 — the claim → witness rule.

Spec: `docs/feature_34_atlas.md` §3.3 · decisions D19, D39, D40.

Everything here runs against real `invoice` and `documents` rows on the dev
Postgres (hard rule 2), because the two things the task turns on are both
database-derived and neither is stored:

* **the vendor baseline is computed at check time** (D39) -- so the test writes
  that vendor's history and asserts the range comes back off those rows;
* **the line shows its own working** (D40) -- "over 4x their usual ... across 14
  invoices" -- which is the substitute for a baseline the user could edit, and is
  therefore the thing that has to be right.

And the rule itself is asserted as a rule: hold the witness and ATLAS checks
silently, do not hold it and the ask has to be earned by a material amount.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlmodel import select

from models import Document, Invoice, Tenant
from services.atlas_capabilities import AtlasCapability
from services.atlas_contract import validate_recommendation
from services.atlas_doubt import (
    CLAIM_WITNESS,
    ClaimKind,
    Verdict,
    Witness,
    claims_for_invoice,
    doubt_recommendations,
    doubts_for_invoice,
    vendor_baseline,
    witnesses_held,
)
from tests.atlas_pg import open_session, postgres_only, unique_tag

VENDOR = "Kumar Supplies"


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
    tenant = Tenant(name=f"atlas-doubt-{tag}", domain=f"atlas-doubt-{tag}.test")
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


def _invoice(session, written, tenant, total, **fields):
    inv = Invoice(
        tenant_id=tenant.id,
        file_path=f"tests/{uuid4().hex}.pdf",
        vendor_name=fields.get("vendor_name", VENDOR),
        invoice_number=fields.get("number", uuid4().hex[:6]),
        grand_total=total,
        currency=fields.get("currency", "INR"),
        status=fields.get("status", "AUDIT_REQUIRED"),
        flow_direction="INBOUND",
        invoice_date=fields.get("invoice_date", date(2026, 8, 12)),
        items=fields.get("items", []),
    )
    session.add(inv)
    session.commit()
    session.refresh(inv)
    written.append(inv)
    return inv


def _document(session, written, tenant, doc_type):
    doc = Document(
        tenant_id=tenant.id,
        file_path=f"tests/{uuid4().hex}.pdf",
        doc_type=doc_type,
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    written.append(doc)
    return doc


def _history(session, written, tenant, amounts):
    return [_invoice(session, written, tenant, amount) for amount in amounts]


# ═════════════════════════════════════════════════════════════════════════════
# The mapping (§3.3, D19) — fixed, not learned
# ═════════════════════════════════════════════════════════════════════════════

def test_every_claim_has_exactly_one_witness():
    assert set(CLAIM_WITNESS) == set(ClaimKind)
    assert CLAIM_WITNESS[ClaimKind.RATE] is Witness.QUOTATION_OR_CONTRACT
    assert CLAIM_WITNESS[ClaimKind.QUANTITY] is Witness.PURCHASE_ORDER
    assert CLAIM_WITNESS[ClaimKind.DELIVERY] is Witness.DELIVERY_NOTE
    assert CLAIM_WITNESS[ClaimKind.PAYMENT] is Witness.BANK_STATEMENT
    assert CLAIM_WITNESS[ClaimKind.BALANCE] is Witness.VENDOR_STATEMENT


@postgres_only
def test_claims_come_off_extracted_fields_and_nowhere_else(pg):
    """D39: a claim is derived, never stored, and never invented for a field that
    was not extracted."""
    session, tenant, written = pg
    bare = _invoice(session, written, tenant, None, status="PROCESSING")
    assert claims_for_invoice(bare) == []

    full = _invoice(session, written, tenant, 5000.0, items=[{"total": 5000}])
    kinds = {claim.kind for claim in claims_for_invoice(full)}
    assert ClaimKind.RATE in kinds and ClaimKind.QUANTITY in kinds


# ═════════════════════════════════════════════════════════════════════════════
# The baseline (D39) — computed now, from that vendor's own invoices
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_the_baseline_is_computed_from_the_vendors_own_history(pg):
    session, tenant, written = pg
    _history(session, written, tenant, [40000.0, 55000.0, 60000.0, 48000.0])
    subject = _invoice(session, written, tenant, 250000.0)

    baseline = vendor_baseline(
        session, tenant.id, VENDOR, exclude_invoice_id=subject.id, currency="INR"
    )
    assert baseline.invoice_count == 4
    assert baseline.low == Decimal("40000")
    assert baseline.high == Decimal("60000")
    assert baseline.is_established


@postgres_only
def test_the_invoice_being_checked_is_excluded_from_its_own_baseline(pg):
    """Comparing a number against a range it is inside makes every invoice normal."""
    session, tenant, written = pg
    _history(session, written, tenant, [1000.0, 1000.0, 1000.0])
    subject = _invoice(session, written, tenant, 90000.0)
    baseline = vendor_baseline(
        session, tenant.id, VENDOR, exclude_invoice_id=subject.id, currency="INR"
    )
    assert baseline.high == Decimal("1000")


@postgres_only
def test_a_vendor_billing_in_two_currencies_has_two_baselines(pg):
    """§7.4 / D32 — one blended range would be a wrong number with a range around it."""
    session, tenant, written = pg
    _history(session, written, tenant, [1000.0, 1200.0, 1100.0])
    for amount in (10.0, 12.0, 11.0):
        _invoice(session, written, tenant, amount, currency="USD")
    inr = vendor_baseline(session, tenant.id, VENDOR, currency="INR")
    usd = vendor_baseline(session, tenant.id, VENDOR, currency="USD")
    assert inr.invoice_count == 3 and inr.high == Decimal("1200")
    assert usd.invoice_count == 3 and usd.high == Decimal("12")


# ═════════════════════════════════════════════════════════════════════════════
# The decision rule (§3.3) — three steps, in order
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_an_amount_inside_the_vendors_range_raises_no_doubt_at_all(pg):
    """₹4,500 matching twelve months of history: never ask (§3.3 step 3)."""
    session, tenant, written = pg
    _history(session, written, tenant, [4000.0, 4500.0, 5000.0, 4800.0])
    subject = _invoice(session, written, tenant, 4500.0)
    doubts = doubts_for_invoice(session, tenant.id, subject, held=set())
    assert doubts == []


@postgres_only
def test_an_unusual_amount_asks_and_shows_its_working(pg):
    """D40 — the line states the comparison that produced it, not just a verdict."""
    session, tenant, written = pg
    _history(session, written, tenant, [40000.0, 60000.0, 50000.0, 45000.0])
    subject = _invoice(session, written, tenant, 240000.0, number="1041")

    doubts = doubts_for_invoice(session, tenant.id, subject, held=set())
    assert len(doubts) == 1
    doubt = doubts[0]
    assert doubt.verdict is Verdict.ASK
    assert doubt.witness is Witness.QUOTATION_OR_CONTRACT
    assert "4x their usual" in doubt.working
    assert "40,000.00" in doubt.working and "60,000.00" in doubt.working
    assert "across 4 invoices" in doubt.working

    lines = doubt_recommendations(subject, doubts)
    assert len(lines) == 1
    line = lines[0]
    validate_recommendation(line)
    assert line.capability is AtlasCapability.AUDIT
    assert line.action.kind == "attach_witness_document"
    assert line.action.params["witness"] == "quotation_or_contract"
    # The ask carries its reason, or the user cannot judge it (§3.3).
    assert doubt.working in line.why.text
    # And the working is provenance, not decoration: each amount in it is a
    # COMPUTED figure naming what was computed (D40, Slice A's mechanism).
    assert {f.rendered for f in line.why.figures} >= {"2,40,000.00", "40,000.00", "60,000.00"}
    assert all(f.computation for f in line.why.figures)


@postgres_only
def test_holding_the_witness_means_checking_silently_and_saying_nothing(pg):
    """§3.3 step 2 — "this is what stops it nagging"."""
    session, tenant, written = pg
    _history(session, written, tenant, [40000.0, 60000.0, 50000.0])
    subject = _invoice(session, written, tenant, 240000.0)
    _document(session, written, tenant, "CONTRACT")

    held = witnesses_held(session, tenant.id)
    assert Witness.QUOTATION_OR_CONTRACT in held

    doubts = doubts_for_invoice(session, tenant.id, subject, held=held)
    assert [d.verdict for d in doubts] == [Verdict.CHECK_SILENTLY]
    assert doubt_recommendations(subject, doubts) == []


@postgres_only
def test_a_first_invoice_from_a_new_vendor_says_so_rather_than_inventing_a_range(pg):
    """Cold start (§7.1): "there is no history yet" is the honest line."""
    session, tenant, written = pg
    subject = _invoice(session, written, tenant, 90000.0, vendor_name="Brand New Ltd")
    doubts = doubts_for_invoice(session, tenant.id, subject, held=set())
    assert len(doubts) == 1
    assert doubts[0].verdict is Verdict.ASK
    assert "no history" in doubts[0].working
    assert doubts[0].multiple is None
    line = doubt_recommendations(subject, doubts)[0]
    validate_recommendation(line)
    assert line.certainty.value == "uncertain" and line.why.doubt


@postgres_only
def test_nothing_in_this_task_writes_a_row(pg):
    """D39's headline: no new tables, and no new rows in the old ones.

    Asserted rather than asserted-in-a-docstring: the whole task is "derive at
    check time", and a check that quietly persisted its baseline would pass every
    other test in this file.
    """
    session, tenant, written = pg
    _history(session, written, tenant, [40000.0, 60000.0, 50000.0])
    subject = _invoice(session, written, tenant, 240000.0)
    before = len(session.exec(select(Invoice)).all())

    doubts = doubts_for_invoice(session, tenant.id, subject, held=set())
    doubt_recommendations(subject, doubts)

    after = len(session.exec(select(Invoice)).all())
    assert before == after
