"""Feature 30 task 30.0b — `link_attachment()` and the first-link confirmation.

Verification plan 30.0b: "First PO from a new vendor -> `LinkResult.requires_confirmation`;
after confirm, the second links automatically; wrong-vendor never links."

Real Postgres (hard rule 2): every step is a tenant-scoped query, the candidate
search is `find_candidate_invoices()` against real rows, and the confirmation
writes a `vendor_alias` row that the next call reads back.

Gap 492 is asserted here too: confirming a link must not change any invoice.
"""
import os
from datetime import date
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from models import ChatAttachment, ChatSession, Invoice, Vendor, VendorAlias  # noqa: E402
from services import doc_linking as dl  # noqa: E402


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


@pytest.fixture(name="world")
def world_fixture(pg_session):
    tenant_id = uuid4()
    chat = ChatSession(tenant_id=tenant_id, title="F30 linking")
    pg_session.add(chat)
    pg_session.commit()
    pg_session.refresh(chat)

    yield {"tenant_id": tenant_id, "session": chat, "session_db": pg_session}

    for model in (VendorAlias, Vendor, ChatAttachment, Invoice):
        for row in pg_session.exec(select(model).where(model.tenant_id == tenant_id)).all():
            pg_session.delete(row)
        pg_session.commit()
    pg_session.delete(chat)
    pg_session.commit()


def _invoice(pg_session, tenant_id, number, vendor, *, po=None, total=100000.0, when=date(2026, 3, 1)):
    inv = Invoice(
        tenant_id=tenant_id,
        invoice_number=number,
        file_path=f"test/{number}.pdf",
        vendor_name=vendor,
        po_number=po,
        grand_total=total,
        currency="INR",
        invoice_date=when,
        status="PROCESSING",
    )
    pg_session.add(inv)
    pg_session.commit()
    pg_session.refresh(inv)
    return inv


def _attachment(pg_session, world, *, party="Shree Packaging Pvt Ltd", doc_number="PO-1", total=100000.0, when=date(2026, 2, 25)):
    att = ChatAttachment(
        tenant_id=world["tenant_id"],
        session_id=world["session"].id,
        filename="po.pdf",
        blob_path="",
        doc_type="PURCHASE_ORDER",
        extraction_status="EXTRACTED",
        doc_number=doc_number,
        party_name=party,
        doc_date=when,
        currency="INR",
        grand_total=total,
        extracted_json={"doc_type": "PURCHASE_ORDER", "doc_number": doc_number, "party_name": party},
    )
    pg_session.add(att)
    pg_session.commit()
    pg_session.refresh(att)
    return att


# --- the vendor policy -----------------------------------------------------


def test_policy_says_ask_for_an_unknown_vendor(pg_session, world):
    policy = dl.vendor_link_policy(world["tenant_id"], None, pg_session)
    assert policy["auto_confirm"] is False
    assert "not in your vendor list" in policy["reason"]


def test_policy_auto_confirms_once_an_alias_is_confirmed(pg_session, world):
    from services.vendor_master import confirm_alias, get_or_create_vendor

    vendor = get_or_create_vendor("Shree Packaging Pvt Ltd", world["tenant_id"], pg_session)
    assert dl.vendor_link_policy(world["tenant_id"], vendor.id, pg_session)["auto_confirm"] is False

    confirm_alias(
        "Shree Packaging Pvt Ltd", vendor.id, world["tenant_id"], pg_session, confirmed_by="a@x.com"
    )
    policy = dl.vendor_link_policy(world["tenant_id"], vendor.id, pg_session)
    assert policy["auto_confirm"] is True
    assert policy["confirmed_count"] == 1


# --- linking ---------------------------------------------------------------


def test_no_candidates_is_a_reportable_outcome_not_a_link(pg_session, world):
    att = _attachment(pg_session, world)
    result = dl.link_attachment(att, world["tenant_id"], pg_session)
    assert result.status == "none"
    assert result.is_linked is False
    assert "no invoice" in result.reason


def test_an_exact_document_number_links_without_asking(pg_session, world):
    """Tier 1 is an identifier both documents were meant to share."""
    inv = _invoice(pg_session, world["tenant_id"], "INV-T1", "Shree Packaging Pvt Ltd", po="PO-1")
    att = _attachment(pg_session, world, doc_number="PO-1")

    result = dl.link_attachment(att, world["tenant_id"], pg_session)
    assert result.tier == 1
    assert result.status == "linked"
    assert result.requires_confirmation is False
    assert result.invoice_ids == [str(inv.id)]


def test_the_first_link_from_a_new_vendor_needs_confirmation(pg_session, world):
    _invoice(pg_session, world["tenant_id"], "INV-T2", "Shree Packaging Pvt Ltd")
    att = _attachment(pg_session, world, doc_number="PO-NOMATCH")

    result = dl.link_attachment(att, world["tenant_id"], pg_session)
    assert result.tier == 2
    assert result.status == "needs_confirmation"
    assert result.requires_confirmation is True
    assert result.is_linked is False  # a proposal is not a link
    assert result.invoice_ids  # but the candidates are there to show
    assert result.corroboration and result.corroboration[0]["amount_matches"] is True


def test_after_confirming_once_the_next_document_links_automatically(pg_session, world):
    inv = _invoice(pg_session, world["tenant_id"], "INV-T3", "Shree Packaging Pvt Ltd")
    first = _attachment(pg_session, world, doc_number="PO-A")
    first.candidate_invoice_ids = [str(inv.id)]
    pg_session.add(first)
    pg_session.commit()

    dl.confirm_link(
        first, [str(inv.id)], world["tenant_id"], pg_session, confirmed_by="owner@example.com"
    )

    second = _attachment(pg_session, world, doc_number="PO-B")
    result = dl.link_attachment(second, world["tenant_id"], pg_session)
    assert result.status == "linked"
    assert result.requires_confirmation is False
    assert "already confirmed" in result.reason


def test_a_different_spelling_of_the_confirmed_vendor_still_links(pg_session, world):
    """The point of routing through the vendor master."""
    inv = _invoice(pg_session, world["tenant_id"], "INV-T4", "Shree Packaging Pvt Ltd")
    first = _attachment(pg_session, world, doc_number="PO-C")
    first.candidate_invoice_ids = [str(inv.id)]
    pg_session.add(first)
    pg_session.commit()
    dl.confirm_link(first, [str(inv.id)], world["tenant_id"], pg_session, confirmed_by="a@x.com")

    second = _attachment(pg_session, world, party="SHREE PACKAGING", doc_number="PO-D")
    result = dl.link_attachment(second, world["tenant_id"], pg_session)
    assert result.status == "linked"


def test_wrong_vendor_never_links(pg_session, world):
    """A candidate that belongs to a different confirmed supplier is rejected."""
    from services.vendor_master import confirm_alias, get_or_create_vendor

    ours = get_or_create_vendor("Shree Packaging Pvt Ltd", world["tenant_id"], pg_session)
    confirm_alias(
        "Shree Packaging Pvt Ltd", ours.id, world["tenant_id"], pg_session, confirmed_by="a@x.com"
    )
    theirs = get_or_create_vendor("Bharat Steels", world["tenant_id"], pg_session)
    confirm_alias("Bharat Steels", theirs.id, world["tenant_id"], pg_session, confirmed_by="a@x.com")

    # An invoice from the OTHER supplier, in the same date window and for the
    # same amount -- everything tier 2 would like except the supplier.
    _invoice(pg_session, world["tenant_id"], "INV-WRONG", "Bharat Steels")
    att = _attachment(pg_session, world, party="Shree Packaging Pvt Ltd", doc_number="PO-X")

    result = dl.link_attachment(att, world["tenant_id"], pg_session)
    assert result.is_linked is False
    if result.rejected:
        assert result.rejected[0]["reason"] == "belongs to a different supplier"


# --- confirmation ----------------------------------------------------------


def test_confirming_an_uncandidate_invoice_is_refused(pg_session, world):
    """The Feature 26 rule: this endpoint is not an existence oracle."""
    inv = _invoice(pg_session, world["tenant_id"], "INV-T5", "Shree Packaging Pvt Ltd")
    att = _attachment(pg_session, world)
    with pytest.raises(ValueError):
        dl.confirm_link(att, [str(inv.id)], world["tenant_id"], pg_session)


def test_confirming_records_the_vendor_identity(pg_session, world):
    inv = _invoice(pg_session, world["tenant_id"], "INV-T6", "Shree Packaging Pvt Ltd")
    att = _attachment(pg_session, world)
    att.candidate_invoice_ids = [str(inv.id)]
    pg_session.add(att)
    pg_session.commit()

    dl.confirm_link(att, [str(inv.id)], world["tenant_id"], pg_session, confirmed_by="owner@x.com")

    aliases = pg_session.exec(
        select(VendorAlias).where(VendorAlias.tenant_id == world["tenant_id"])
    ).all()
    assert len(aliases) == 1
    assert aliases[0].confirmed_by == "owner@x.com"
    pg_session.refresh(att)
    assert att.confirmed_invoice_ids == [str(inv.id)]


def test_confirming_a_link_never_touches_the_invoice(pg_session, world):
    """Gap 492: intelligence is information only."""
    inv = _invoice(pg_session, world["tenant_id"], "INV-T7", "Shree Packaging Pvt Ltd")
    before = inv.status
    att = _attachment(pg_session, world)
    att.candidate_invoice_ids = [str(inv.id)]
    pg_session.add(att)
    pg_session.commit()

    dl.confirm_link(att, [str(inv.id)], world["tenant_id"], pg_session, confirmed_by="owner@x.com")

    pg_session.refresh(inv)
    assert inv.status == before
