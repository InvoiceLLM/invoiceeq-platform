"""Feature 26 E-4 / task R9 — Tier 3 vector discovery. V-12 to V-15.

WHAT TIER 3 IS FOR. Part 1's Tier 2 requires BOTH a party name AND a date, and
gives up entirely if either is missing -- so a scanned delivery note with a
smudged date finds nothing at all, not a poor match, nothing. That is the
concrete mechanism behind the founder's underlying complaint and the case this
tier exists to serve.

WHAT MAKES IT SAFE, and it is emphatically not the ranking. A vector search is
non-deterministic, so its output is never an answer here: it is a list of
PROPOSALS that goes through the same confirmation gate as every other tier (D4).
The human decides, and the arithmetic that follows is the identical
`compare_reference_to_invoices()` on the identical `Decimal` math. Tier 3 changes
only WHICH invoices get compared -- never what the comparison concludes.

The tests below are therefore weighted towards the guardrails rather than the
retrieval: that Tier 3 cannot fire when a real match exists, cannot reach
`confirmed_invoice_ids`, cannot cross a tenant boundary, and cannot present
itself with a Tier-1 voice.
"""
from datetime import date
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import services.document_comparison as dc
from models import Invoice
from services.document_comparison import (
    TIER3_CANDIDATE_LIMIT,
    build_confirmation_payload,
    find_candidate_invoices,
)

engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)

TENANT = uuid4()
OTHER_TENANT = uuid4()


@pytest.fixture(name="db")
def db_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


def _invoice(db, *, tenant_id=None, number="INV-1", vendor="Acme Supplies Ltd",
             when=date(2026, 3, 1), deleted_at=None):
    row = Invoice(
        tenant_id=tenant_id or TENANT,
        file_path=f"{number}.pdf",
        vendor_name=vendor,
        invoice_number=number,
        invoice_date=when,
        currency="INR",
        subtotal=1000.0,
        tax_amount=180.0,
        grand_total=1180.0,
        status="COMPLETED",
        deleted_at=deleted_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _chunks(*invoice_ids):
    """The shape `query_invoice_chunks()` returns: one chunk per page, so several
    chunks routinely belong to one invoice. Tier 3 must collapse them."""
    return [{"document": "text", "metadata": {"invoice_id": str(i)}} for i in invoice_ids]


# --- V-12: fires only when Tiers 1 and 2 are both empty ----------------------


def test_v12_tier3_does_not_fire_when_tier1_finds_a_po_match(db):
    """An exact PO-number join is an identifier both documents were MEANT to
    share. Diluting it with similarity guesses would hand the user a list in
    which the right answer is no longer obviously right -- the same reasoning
    that makes Tier 2 a fallback rather than a supplement."""
    _invoice(db, number="INV-1")
    inv = _invoice(db, number="INV-2")
    inv.po_number = "PO-2024/0043"
    db.add(inv)
    db.commit()

    with patch.object(dc, "_tier3_candidates") as tier3:
        result = find_candidate_invoices(
            tenant_id=TENANT,
            po_number="PO-2024/0043",
            party_name="Acme Supplies Ltd",
            doc_date=date(2026, 3, 1),
            db_session=db,
        )

    assert result["tier"] == 1
    tier3.assert_not_called()


def test_v12_tier3_does_not_fire_when_tier2_finds_a_name_and_date_match(db):
    _invoice(db, vendor="Acme Supplies Ltd", when=date(2026, 3, 1))

    with patch.object(dc, "_tier3_candidates") as tier3:
        result = find_candidate_invoices(
            tenant_id=TENANT,
            po_number=None,
            party_name="Acme",
            doc_date=date(2026, 3, 5),
            db_session=db,
        )

    assert result["tier"] == 2
    tier3.assert_not_called()


def test_v12_tier3_fires_only_when_both_earlier_tiers_are_empty(db):
    """The motivating case: a document whose date did not survive the scan, so
    Tier 2's window has nothing to centre on."""
    target = _invoice(db, number="INV-9", vendor="Northwind Trading")

    with patch("chroma_client.query_invoice_chunks", return_value=_chunks(target.id)):
        result = find_candidate_invoices(
            tenant_id=TENANT,
            po_number="PO-NOT-PRESENT",
            party_name="Northwind Trading",
            doc_date=None,
            db_session=db,
        )

    assert result["tier"] == 3
    assert [i.id for i in result["invoices"]] == [target.id]


# --- V-13: proposals only, never a confirmed match ---------------------------


def test_v13_tier3_returns_proposals_that_still_go_through_the_confirmation_gate(db):
    """E-4's hardest guardrail. Part 1 keeps `candidate_invoice_ids` and
    `confirmed_invoice_ids` as separate columns precisely so a similarity guess
    can never become a confirmed match by accident, and that separation must not
    be collapsed. Asserted on the payload the user actually sees."""
    target = _invoice(db, number="INV-7", vendor="Northwind Trading")

    with patch("chroma_client.query_invoice_chunks", return_value=_chunks(target.id)):
        result = find_candidate_invoices(
            tenant_id=TENANT, po_number=None, party_name="Northwind Trading",
            doc_date=None, db_session=db,
        )

    payload = build_confirmation_payload(
        attachment_id=str(uuid4()),
        invoices=result["invoices"],
        tier=result["tier"],
        doc_type="PURCHASE_ORDER",
        doc_number="PO-1",
    )
    # It is a CONFIRMATION request, not an answer: no comparison, no figures.
    assert payload["kind"] == "attachment_match_confirmation"
    assert payload["tier"] == 3
    assert "attachment_comparison" not in payload
    assert payload["candidates"]


# --- V-15: the tier is visible, and Tier 3 does not sound like Tier 1 --------


def test_v15_a_tier3_proposal_is_labelled_as_similarity_not_as_a_match(db):
    """The tier is the user's only signal of how much the system actually knows.
    The three strengths are different claims -- an exact shared identifier, a
    name-and-date heuristic, and "nearest in a vector search" -- and presenting
    the third in the second's language is how a guess gets confirmed by someone
    skim-reading."""
    target = _invoice(db, number="INV-3")

    tier1 = build_confirmation_payload(
        attachment_id="a", invoices=[target], tier=1,
        doc_type="PURCHASE_ORDER", doc_number="PO-1",
    )
    tier3 = build_confirmation_payload(
        attachment_id="a", invoices=[target], tier=3,
        doc_type="PURCHASE_ORDER", doc_number="PO-1",
    )

    assert "PO-number" in tier1["message"]
    assert "similarity" in tier3["message"].lower()
    assert "confirm" in tier3["message"].lower()
    # The two must not read the same -- that is the whole point of the label.
    assert tier1["message"] != tier3["message"]


# --- the guardrails that are not in the V-numbers but must hold --------------


def test_tier3_is_capped_tighter_than_tier2(db):
    """10, not 20 (E-4). A date-window list degrades gracefully -- the 20th entry
    is still the same vendor in the same quarter. A similarity list does not, and
    a long one invites scrolling until something looks plausible."""
    assert TIER3_CANDIDATE_LIMIT == 10
    assert TIER3_CANDIDATE_LIMIT < dc.CANDIDATE_LIMIT

    rows = [_invoice(db, number=f"INV-{n}", vendor="Northwind Trading") for n in range(15)]
    with patch("chroma_client.query_invoice_chunks",
               return_value=_chunks(*[r.id for r in rows])):
        result = find_candidate_invoices(
            tenant_id=TENANT, po_number=None, party_name="Northwind Trading",
            doc_date=None, db_session=db,
        )
    assert len(result["invoices"]) <= TIER3_CANDIDATE_LIMIT


def test_tier3_collapses_several_chunks_of_one_invoice_into_one_candidate(db):
    """Chunking is one per PAGE, so a five-page invoice contributes five chunks.
    Offering the same invoice five times would be a list the user cannot read."""
    target = _invoice(db, number="INV-5", vendor="Northwind Trading")

    with patch("chroma_client.query_invoice_chunks",
               return_value=_chunks(target.id, target.id, target.id)):
        result = find_candidate_invoices(
            tenant_id=TENANT, po_number=None, party_name="Northwind Trading",
            doc_date=None, db_session=db,
        )
    assert [i.id for i in result["invoices"]] == [target.id]


def test_tier3_never_proposes_another_tenants_invoice(db):
    """Isolation is structural -- `query_invoice_chunks()` reads a per-tenant
    collection (Gap 55) -- but the row lookup re-asserts `tenant_id` as a second,
    independent check. A row this returns is about to be compared against money,
    and two independent guarantees is the right number for that.

    Simulated by a Chroma result that (impossibly) names another tenant's
    invoice: even then, nothing crosses.
    """
    theirs = _invoice(db, tenant_id=OTHER_TENANT, number="INV-THEIRS")

    with patch("chroma_client.query_invoice_chunks", return_value=_chunks(theirs.id)):
        result = find_candidate_invoices(
            tenant_id=TENANT, po_number=None, party_name="Nobody",
            doc_date=None, db_session=db,
        )
    assert result["tier"] == 0
    assert result["invoices"] == []


def test_tier3_never_proposes_a_soft_deleted_invoice(db):
    """Chroma has no idea a row was deleted -- Gap 192's soft delete is a Postgres
    concern -- so a deleted invoice's chunks are still indexed and would be
    proposed by a retrieval-only implementation."""
    gone = _invoice(db, number="INV-GONE", vendor="Northwind Trading",
                    deleted_at=date(2026, 4, 1))

    with patch("chroma_client.query_invoice_chunks", return_value=_chunks(gone.id)):
        result = find_candidate_invoices(
            tenant_id=TENANT, po_number=None, party_name="Northwind Trading",
            doc_date=None, db_session=db,
        )
    assert result["invoices"] == []


def test_an_unreachable_chroma_degrades_to_no_matches_not_an_error(db):
    """Tier 3 is a fallback for a case that already returned nothing. If
    retrieval is down the user gets Part 1's honest "no matches found" -- exactly
    what they would have got before this tier existed -- rather than a 500."""
    with patch("chroma_client.query_invoice_chunks", side_effect=RuntimeError("chroma down")):
        result = find_candidate_invoices(
            tenant_id=TENANT, po_number=None, party_name="Nobody",
            doc_date=None, db_session=db,
        )
    assert result == {"tier": 0, "invoices": [], "truncated": False}


def test_tier3_makes_no_llm_call(db):
    """Hard rule 3. Tier 3 chooses which invoices are compared, which is a
    financial decision one step removed, so nothing here may consult a model.
    Asserted structurally on the module, since the ranking comes from an
    embedding search and the temptation to "let a model pick the best one" is
    exactly what this forbids."""
    import inspect

    source = inspect.getsource(dc)
    for forbidden in ("get_llm", "with_structured_output", "llm.invoke"):
        assert forbidden not in source, forbidden
