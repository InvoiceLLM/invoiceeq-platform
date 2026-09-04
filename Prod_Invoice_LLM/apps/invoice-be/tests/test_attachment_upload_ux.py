"""Feature 26 Phase 4 — what the chip can say at upload (Gaps 444, 445, 446).

The theme: everything the user needs in order to catch a mistake must be
available BEFORE they ask a question, because that is the only moment when
catching it is cheap. A misread document number found at upload costs one
re-upload; the same number found after an answer costs trust in every figure.
"""
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import config
from models import ChatAttachment, ChatSession, Invoice

engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)

TENANT = uuid4()


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


def _session(db):
    s = ChatSession(tenant_id=TENANT, title="t")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _attachment(db, session, **kw):
    defaults = dict(
        tenant_id=TENANT,
        session_id=session.id,
        filename="po.pdf",
        blob_path="x/po.pdf",
        doc_type="PURCHASE_ORDER",
        extraction_status="EXTRACTED",
        doc_number="PO-IN-5502",
        party_name="Deccan Chemicals",
        currency="INR",
        grand_total=25252.0,
        extracted_json={
            "doc_type": "PURCHASE_ORDER",
            "po_number": "PO-IN-5502",
            "subtotal": 24000.0,
            "tax_amount": 1252.0,
            "payment_terms": "Net 30",
            "items": [
                {"description": "Catalysts", "quantity": 8, "unit_price": 100, "amount": 800},
                {"description": "Reagents", "quantity": 2, "unit_price": 50, "amount": 100},
            ],
        },
    )
    defaults.update(kw)
    row = ChatAttachment(**defaults)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _invoice(db, **kw):
    defaults = dict(
        tenant_id=TENANT,
        file_path="x.pdf",
        invoice_number="DC-2026-1120",
        po_number="PO-IN-5502",
        vendor_name="Deccan Chemicals",
        currency="INR",
        grand_total=26152.0,
        status="COMPLETED",
        items=[],
    )
    defaults.update(kw)
    inv = Invoice(**defaults)
    db.add(inv)
    db.commit()
    db.refresh(inv)
    return inv


# ---------------------------------------------------------------------------
# Gap 444 — the matcher runs at upload
# ---------------------------------------------------------------------------
def test_gap_444_a_tier_1_match_is_proposed_at_upload_and_named(db_session):
    """Before this, the upload response carried an empty candidate list even when
    an exact PO match existed, so the chip could not say "found 1 match"."""
    from routers.chat_attachments import _to_out
    from services.attachment_extraction import match_attachment as _match_at_upload

    session = _session(db_session)
    row = _attachment(db_session, session)
    inv = _invoice(db_session)

    _match_at_upload(row, db_session)

    assert row.match_tier == 1
    assert row.candidate_invoice_ids == [str(inv.id)]
    assert "DC-2026-1120" in row.match_summary
    assert _to_out(row).match_summary == row.match_summary


def test_gap_444_no_match_is_stated_rather_than_left_blank(db_session):
    """An empty result is information. Silence reads as "still working"."""
    from services.attachment_extraction import match_attachment as _match_at_upload

    session = _session(db_session)
    row = _attachment(db_session, session, doc_number="PO-NOTHING", party_name="Nobody")
    row.extracted_json = {**row.extracted_json, "po_number": "PO-NOTHING"}

    _match_at_upload(row, db_session)

    assert row.candidate_invoice_ids == []
    assert row.match_summary == "no matching invoice found yet"


def test_gap_444_matching_at_upload_never_confirms_anything(db_session):
    """D4's gate is the whole safety property of this feature: a proposal must
    not be able to satisfy it, so no comparison and no figure can follow from an
    upload alone."""
    from services.attachment_extraction import match_attachment as _match_at_upload

    session = _session(db_session)
    row = _attachment(db_session, session)
    _invoice(db_session)

    _match_at_upload(row, db_session)

    assert row.candidate_invoice_ids, "a candidate WAS proposed"
    assert row.confirmed_invoice_ids == [], "and nothing was confirmed by proposing it"


def test_gap_444_a_matcher_failure_does_not_fail_the_upload(db_session):
    """The document is already stored and extracted by this point. Losing the
    proposal is a degraded chip; raising would lose the upload."""
    from services.attachment_extraction import match_attachment as _match_at_upload

    session = _session(db_session)
    row = _attachment(db_session, session)

    with patch(
        "services.document_comparison.find_candidate_invoices", side_effect=RuntimeError("boom")
    ):
        _match_at_upload(row, db_session)

    assert row.extraction_status == "EXTRACTED"
    assert row.candidate_invoice_ids == []


def test_gap_444_an_unreadable_document_is_never_matched(db_session):
    """Matching on fields that failed to extract would propose an invoice on the
    strength of nulls."""
    from services.attachment_extraction import match_attachment as _match_at_upload

    session = _session(db_session)
    row = _attachment(db_session, session, extraction_status="EXTRACT_FAILED")
    _invoice(db_session)

    _match_at_upload(row, db_session)
    assert row.match_tier is None


def test_gap_444_the_response_carries_the_line_count_and_the_session_cap(db_session):
    from routers.chat_attachments import MAX_ATTACHMENTS_PER_SESSION, _to_out

    session = _session(db_session)
    row = _attachment(db_session, session)

    out = _to_out(row, attachment_count=3)
    assert out.line_count == 2
    assert out.attachment_count == 3
    assert out.attachment_limit == MAX_ATTACHMENTS_PER_SESSION


# ---------------------------------------------------------------------------
# Gap 445 — show what was read, and what we were unsure of
# ---------------------------------------------------------------------------
def test_gap_445_the_preview_is_the_persisted_extraction_not_a_re_read(db_session):
    from routers.chat_attachments import _to_out

    session = _session(db_session)
    row = _attachment(db_session, session)

    preview = _to_out(row).extraction_preview
    assert preview["doc_number"] == "PO-IN-5502"
    assert preview["subtotal"] == 24000.0
    assert preview["payment_terms"] == "Net 30"
    assert [line["description"] for line in preview["lines"]] == ["Catalysts", "Reagents"]
    assert preview["line_count"] == 2


def test_gap_445_a_long_document_is_truncated_but_says_so(db_session):
    from routers.chat_attachments import _to_out

    session = _session(db_session)
    row = _attachment(
        db_session,
        session,
        extracted_json={"items": [{"description": f"line {i}"} for i in range(40)]},
    )

    preview = _to_out(row).extraction_preview
    assert len(preview["lines"]) == 20
    assert preview["line_count"] == 40, "the true count travels with the truncated list"


def test_gap_445_an_unreadable_document_has_no_preview(db_session):
    from routers.chat_attachments import _to_out

    session = _session(db_session)
    row = _attachment(db_session, session, extraction_status="EXTRACT_FAILED")
    assert _to_out(row).extraction_preview is None


def test_gap_445_only_the_fields_that_change_an_answer_are_gated(db_session):
    """A misread `notes` costs nothing. A misread document number costs the
    whole match, so it is the one worth a question."""
    from routers.chat_attachments import _to_out

    session = _session(db_session)
    row = _attachment(
        db_session,
        session,
        extracted_json={
            "items": [],
            "field_confidence": {
                "doc_number": 0.31,
                "grand_total": 0.95,
                "notes": 0.02,
            },
        },
    )

    assert _to_out(row).low_confidence_fields == ["doc_number"]


def test_gap_445_no_confidence_data_gates_nothing(db_session):
    """Absence of a score is not evidence of a bad read; every Part 1 attachment
    predates the confidence block."""
    from routers.chat_attachments import _to_out

    session = _session(db_session)
    row = _attachment(db_session, session)
    assert _to_out(row).low_confidence_fields == []


# ---------------------------------------------------------------------------
# Gap 446 — images, but only where they can actually be read
# ---------------------------------------------------------------------------
def test_gap_446_images_are_accepted_on_azure_and_refused_on_the_local_path(monkeypatch):
    """A photo of a delivery note is how a warehouse actually sends one. Local
    dev extracts with pypdf, which cannot open a PNG -- accepting one there
    would store a file that can never be read."""
    import routers.chat_attachments as ca

    monkeypatch.setattr(config.settings, "LLM_PROVIDER", "azure")
    accepted = ca._accepted_content_types()
    assert {"application/pdf", "image/png", "image/jpeg"} <= accepted

    monkeypatch.setattr(config.settings, "LLM_PROVIDER", "ollama")
    assert ca._accepted_content_types() == {"application/pdf"}


def test_gap_446_the_indexer_opens_an_image_as_an_image(db_session):
    """PyMuPDF raises on a PNG opened with `filetype="pdf"`, which would leave
    the document stored with no searchable text at all."""
    import services.chat_document_search as cds

    session = _session(db_session)
    row = _attachment(db_session, session, blob_path="tenants/x/photo.PNG", filename="photo.png")

    seen = {}

    class _Doc:
        def __iter__(self):
            return iter([])

        def __len__(self):
            return 0

        def close(self):
            pass

    def _fake_open(stream=None, filetype=None):
        seen["filetype"] = filetype
        return _Doc()

    with patch.object(cds, "fitz", SimpleNamespace(open=_fake_open)), patch.object(
        cds, "download_pdf_from_storage", return_value=b"x"
    ):
        cds.index_attachment_chunks(row, TENANT)

    assert seen["filetype"] == "png"
