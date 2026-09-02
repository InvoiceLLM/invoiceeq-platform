"""Feature 26 (Gap 366) — attached reference documents.

Narrow tests for the three pieces that decide correctness:
  * the deterministic matcher (Tier 1 exact, Tier 2 fallback, cap, zero-match),
  * the deterministic comparison (including the currency-mismatch hard stop),
  * the pre-route gate (an `attachment_id` means `classify_query()` is never
    called — asserted on the mock, not inferred from the answer looking right),
  * the REFERENCE extraction profile being additive.

SQLite here, per this repo's narrow-test convention. Hard rule 2 still applies to
any "verified" claim: the Postgres run is functional-tester's (T3), not this
file's.
"""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy.pool import StaticPool

from models import ChatAttachment, ChatSession, Invoice
from services.document_comparison import (
    CANDIDATE_LIMIT,
    build_confirmation_payload,
    build_suggested_actions,
    compare_reference_to_invoices,
    find_candidate_invoices,
    normalize_doc_number,
)

sqlite_url = "sqlite:///:memory:"
engine = create_engine(
    sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool
)

TENANT = uuid4()
OTHER_TENANT = uuid4()


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


def _invoice(db, **kw):
    defaults = dict(
        tenant_id=TENANT,
        file_path="x.pdf",
        vendor_name="Acme Supplies Ltd",
        invoice_number="INV-1",
        invoice_date=date(2026, 3, 1),
        currency="INR",
        subtotal=1000.0,
        tax_amount=180.0,
        grand_total=1180.0,
        status="COMPLETED",
        flow_direction="INBOUND",
    )
    defaults.update(kw)
    row = Invoice(**defaults)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# ---------------------------------------------------------------------------
# normalize_doc_number
# ---------------------------------------------------------------------------
def test_normalize_doc_number_collapses_formatting_not_digits():
    assert normalize_doc_number("PO-2024/0043") == "PO20240043"
    assert normalize_doc_number("po 2024 0043") == "PO20240043"
    # Formatting equivalence only. Two genuinely different POs must not collapse.
    assert normalize_doc_number("PO-1") != normalize_doc_number("PO-11")
    assert normalize_doc_number(None) == ""


# ---------------------------------------------------------------------------
# Tier 1 / Tier 2
# ---------------------------------------------------------------------------
def test_tier1_exact_po_match_wins_and_skips_tier2(db_session):
    hit = _invoice(db_session, po_number="PO-2024/0043", invoice_number="INV-HIT")
    # A same-vendor, in-window invoice that Tier 2 WOULD return. It must not be
    # in the result: Tier 2 is a fallback, not a supplement.
    _invoice(db_session, po_number="PO-9999", invoice_number="INV-NOISE")

    found = find_candidate_invoices(
        tenant_id=TENANT,
        po_number="po 2024 0043",
        party_name="Acme Supplies Ltd",
        doc_date="2026-03-01",
        db_session=db_session,
    )
    assert found["tier"] == 1
    assert [i.id for i in found["invoices"]] == [hit.id]


def test_tier2_only_fires_when_tier1_empty_and_respects_window(db_session):
    in_window = _invoice(db_session, invoice_number="INV-NEAR", invoice_date=date(2026, 3, 20))
    _invoice(db_session, invoice_number="INV-FAR", invoice_date=date(2025, 1, 1))

    found = find_candidate_invoices(
        tenant_id=TENANT,
        po_number="PO-NOT-PRESENT",
        party_name="Acme Supplies",
        doc_date="2026-03-01",
        db_session=db_session,
    )
    assert found["tier"] == 2
    assert [i.id for i in found["invoices"]] == [in_window.id]


def test_tier2_caps_candidates(db_session):
    for n in range(CANDIDATE_LIMIT + 5):
        _invoice(
            db_session,
            invoice_number=f"INV-{n}",
            invoice_date=date(2026, 3, 1) + timedelta(days=n),
        )
    found = find_candidate_invoices(
        tenant_id=TENANT,
        po_number=None,
        party_name="Acme Supplies Ltd",
        doc_date="2026-03-01",
        db_session=db_session,
    )
    assert found["tier"] == 2
    assert found["truncated"] is True
    assert len(found["invoices"]) == CANDIDATE_LIMIT


def test_zero_match_is_reported_not_widened(db_session):
    _invoice(db_session, vendor_name="Completely Different Co")
    found = find_candidate_invoices(
        tenant_id=TENANT,
        po_number="PO-NOPE",
        party_name="Acme Supplies Ltd",
        doc_date="2026-03-01",
        db_session=db_session,
    )
    assert found["tier"] == 0
    assert found["invoices"] == []


def test_matching_is_tenant_scoped(db_session):
    _invoice(db_session, tenant_id=OTHER_TENANT, po_number="PO-2024/0043")
    found = find_candidate_invoices(
        tenant_id=TENANT,
        po_number="PO-2024/0043",
        party_name="Acme Supplies Ltd",
        doc_date="2026-03-01",
        db_session=db_session,
    )
    assert found["invoices"] == []


# ---------------------------------------------------------------------------
# compare_reference_to_invoices
# ---------------------------------------------------------------------------
_REF = {
    "doc_type": "PURCHASE_ORDER",
    "doc_number": "PO-2024/0043",
    "party_name": "Acme Supplies Ltd",
    "doc_date": "2026-03-01",
    "currency": "INR",
    "subtotal": 1000.0,
    "tax_amount": 180.0,
    "grand_total": 1180.0,
    "items": [{"description": "Widget", "amount": 1000.0}],
}


def test_exact_match(db_session):
    inv = _invoice(db_session, items=[{"description": "Widget", "amount": 1000.0}])
    diff = compare_reference_to_invoices(_REF, [inv])
    assert diff["comparisons"][0]["outcome"] == "match"
    assert all(f["status"] == "match" for f in diff["comparisons"][0]["fields"])


def test_over_billed_reports_invoice_higher_with_exact_delta(db_session):
    inv = _invoice(db_session, grand_total=1380.0)
    diff = compare_reference_to_invoices(_REF, [inv])
    c = diff["comparisons"][0]
    assert c["outcome"] == "variance"
    gt = next(f for f in c["fields"] if f["field"] == "grand_total")
    assert gt["status"] == "invoice_higher"
    # Decimal arithmetic, not float: 1380.0 - 1180.0 must be exactly 200.
    assert Decimal(gt["delta"]) == Decimal("200")


def test_under_billed_reports_invoice_lower(db_session):
    inv = _invoice(db_session, grand_total=1000.0)
    c = compare_reference_to_invoices(_REF, [inv])["comparisons"][0]
    gt = next(f for f in c["fields"] if f["field"] == "grand_total")
    assert gt["status"] == "invoice_lower"


def test_missing_value_is_not_treated_as_zero(db_session):
    inv = _invoice(db_session, tax_amount=None)
    c = compare_reference_to_invoices(_REF, [inv])["comparisons"][0]
    tax = next(f for f in c["fields"] if f["field"] == "tax_amount")
    assert tax["status"] == "missing"
    assert tax["delta"] is None
    assert c["outcome"] == "incomplete"


def test_line_count_delta_reported(db_session):
    inv = _invoice(
        db_session,
        items=[{"description": "Widget", "amount": 1000.0}, {"description": "Extra", "amount": 0.0}],
    )
    c = compare_reference_to_invoices(_REF, [inv])["comparisons"][0]
    assert c["line_count_delta"] == 1


def test_currency_mismatch_is_a_hard_stop_not_a_diff_row(db_session):
    inv = _invoice(db_session, currency="EUR")
    diff = compare_reference_to_invoices(_REF, [inv])
    c = diff["comparisons"][0]
    assert c["outcome"] == "currency_mismatch"
    # The whole point: NO amounts were compared, and the reason is stated.
    assert c["fields"] == []
    assert "INR" in c["blocked_reason"] and "EUR" in c["blocked_reason"]
    assert diff["blocked_count"] == 1


def test_empty_candidate_set_compares_nothing(db_session):
    diff = compare_reference_to_invoices(_REF, [])
    assert diff["comparisons"] == []
    assert diff["compared_count"] == 0


# ---------------------------------------------------------------------------
# Suggested actions (D6) — preconditions are checked, nothing is executed
# ---------------------------------------------------------------------------
def test_suggested_actions_respect_outbound_confirm_send_precondition():
    base = {"invoice_id": str(uuid4()), "outcome": "match", "flow_direction": "OUTBOUND"}
    allowed = build_suggested_actions({**base, "invoice_status": "VERIFIED"})
    assert any("confirm-send" in a["endpoint"] for a in allowed)
    # DRAFT is not a legal source state for confirm-send, so it must not be offered.
    denied = build_suggested_actions({**base, "invoice_status": "DRAFT"})
    assert not any("confirm-send" in a["endpoint"] for a in denied)


def test_mark_paid_only_offered_from_sent():
    base = {"invoice_id": str(uuid4()), "outcome": "match", "flow_direction": "OUTBOUND"}
    assert any(
        "mark-paid" in a["endpoint"]
        for a in build_suggested_actions({**base, "invoice_status": "SENT"})
    )
    assert not any(
        "mark-paid" in a["endpoint"]
        for a in build_suggested_actions({**base, "invoice_status": "VERIFIED"})
    )


def test_no_action_is_a_mutation_and_none_invented():
    actions = build_suggested_actions(
        {
            "invoice_id": str(uuid4()),
            "outcome": "variance",
            "flow_direction": "INBOUND",
            "invoice_status": "AUDIT_REQUIRED",
        }
    )
    assert actions, "an inbound AUDIT_REQUIRED variance should suggest something"
    # No flag/dispute/hold/escalate route exists and none may be suggested (D6).
    for a in actions:
        assert not any(
            word in a["endpoint"] for word in ("flag", "dispute", "hold", "escalate")
        )


# ---------------------------------------------------------------------------
# The confirmation payload (D4)
# ---------------------------------------------------------------------------
def test_zero_candidates_offers_manual_entry_and_never_guesses():
    payload = build_confirmation_payload(
        attachment_id=str(uuid4()),
        doc_type="PURCHASE_ORDER",
        doc_number="PO-1",
        tier=0,
        invoices=[],
    )
    assert payload["requires_manual_entry"] is True
    assert payload["candidates"] == []


# ---------------------------------------------------------------------------
# The pre-route gate (D4) — classify_query() must never be called
# ---------------------------------------------------------------------------
def _attachment(db, **kw):
    session = ChatSession(tenant_id=TENANT, title="t")
    db.add(session)
    db.commit()
    db.refresh(session)
    defaults = dict(
        tenant_id=TENANT,
        session_id=session.id,
        filename="po.pdf",
        blob_path="local/po.pdf",
        doc_type="PURCHASE_ORDER",
        extraction_status="EXTRACTED",
        extracted_json=dict(_REF),
        doc_number="PO-2024/0043",
        party_name="Acme Supplies Ltd",
        doc_date=date(2026, 3, 1),
        currency="INR",
        grand_total=1180.0,
    )
    defaults.update(kw)
    row = ChatAttachment(**defaults)
    db.add(row)
    db.commit()
    db.refresh(row)
    return session, row


def test_attachment_id_bypasses_classify_query_entirely(db_session):
    """The gate is deterministic: with an attachment_id, no LLM decides routing.

    Asserted on the mock, not on the shape of the answer — an answer that
    happens to look right while `classify_query` ran anyway would still be the
    bug (`_SQL_KEYWORDS` would have swallowed the attachment).
    """
    import agents.query_agent as qa

    _, attachment = _attachment(db_session)
    turn = MagicMock()

    with patch.object(qa, "classify_query") as classify:
        result = qa._run_query_agent(
            session_id=str(attachment.session_id),
            user_message="does this purchase order match the vendor total?",
            tenant_id=str(TENANT),
            db_session=db_session,
            turn=turn,
            attachment_id=str(attachment.id),
        )

    classify.assert_not_called()
    assert result["generated_sql"] == ""


def test_unconfirmed_attachment_returns_confirmation_not_a_number(db_session):
    """The confirmation gate: no confirmed ids means no financial answer (D4)."""
    import agents.query_agent as qa

    _, attachment = _attachment(db_session)
    _invoice(db_session, po_number="PO-2024/0043", grand_total=1380.0)
    turn = MagicMock()

    with patch.object(qa, "classify_query") as classify, patch.object(qa, "get_llm") as get_llm:
        result = qa._run_query_agent(
            session_id=str(attachment.session_id),
            user_message="was I over-billed?",
            tenant_id=str(TENANT),
            db_session=db_session,
            turn=turn,
            attachment_id=str(attachment.id),
        )

    classify.assert_not_called()
    # No model call at all on the confirmation path.
    get_llm.assert_not_called()
    assert result["attachment_confirmation"]["kind"] == "attachment_match_confirmation"
    assert "attachment_comparison" not in result
    # The over-billed delta must not appear anywhere in the reply.
    assert "200" not in result["content"]


def test_confirmed_attachment_produces_the_deterministic_diff(db_session):
    import agents.query_agent as qa

    _, attachment = _attachment(db_session)
    inv = _invoice(db_session, po_number="PO-2024/0043", grand_total=1380.0)
    attachment.confirmed_invoice_ids = [str(inv.id)]
    db_session.add(attachment)
    db_session.commit()

    fake_llm = MagicMock()
    fake_llm.invoke.return_value = MagicMock(content="The invoice is 200 higher than the PO.")
    turn = MagicMock()

    with patch.object(qa, "classify_query") as classify, patch.object(
        qa, "get_llm", return_value=fake_llm
    ), patch.object(qa, "tracked_llm_call"):
        result = qa._run_query_agent(
            session_id=str(attachment.session_id),
            user_message="was I over-billed?",
            tenant_id=str(TENANT),
            db_session=db_session,
            turn=turn,
            attachment_id=str(attachment.id),
        )

    classify.assert_not_called()
    diff = result["attachment_comparison"]
    gt = next(
        f for f in diff["comparisons"][0]["fields"] if f["field"] == "grand_total"
    )
    assert Decimal(gt["delta"]) == Decimal("200")
    assert result["result_invoice_ids"] == [str(inv.id)]


# ---------------------------------------------------------------------------
# The REFERENCE extraction profile (C2) — additive
# ---------------------------------------------------------------------------
def test_reference_profile_exists_and_is_additive():
    from agents.extraction_agent import (
        InvoiceExtractionSchema,
        OutboundInvoiceExtractionSchema,
        ReferenceDocExtractionSchema,
        resolve_direction_profile,
    )

    ref = resolve_direction_profile("REFERENCE")
    assert ref.schema is ReferenceDocExtractionSchema
    assert ref.required_fields == ()
    assert ref.passed_status == "EXTRACTED"
    assert ref.review_status == "EXTRACT_FAILED"
    assert ref.legacy_audit_path_shim is False

    # The two existing profiles are untouched, and the unknown-direction default
    # is still INBOUND — nothing can reach REFERENCE by accident.
    assert resolve_direction_profile("INBOUND").schema is InvoiceExtractionSchema
    assert resolve_direction_profile("OUTBOUND").schema is OutboundInvoiceExtractionSchema
    assert resolve_direction_profile(None).schema is InvoiceExtractionSchema
    assert resolve_direction_profile("NONSENSE").schema is InvoiceExtractionSchema


def test_reference_schema_carries_the_doc_type_discriminator():
    from agents.extraction_agent import ReferenceDocExtractionSchema

    doc = ReferenceDocExtractionSchema(doc_type="QUOTATION", grand_total=1180.0)
    assert doc.doc_type == "QUOTATION"
    # One schema with a discriminator, not two parallel schemas.
    assert "doc_type" in ReferenceDocExtractionSchema.model_fields


# ---------------------------------------------------------------------------
# Router wiring (Gap 366 follow-up) — POST /chat/sessions/{id}/message
#
# The gate above proves `_run_query_agent()` branches on an attachment_id. This
# proves the real HTTP turn actually *supplies* one: before this, MessageCreate
# had no `attachment_id` field, so the whole feature was unreachable from the
# endpoint every production chat turn goes through.
#
# Imports are down here rather than in the header block because `main` pulls in
# chroma_client, which needs MOCK_EMBEDDINGS set before import.
# ---------------------------------------------------------------------------
import os

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from fastapi.testclient import TestClient  # noqa: E402

from dependencies import MOCK_TENANT_ID, get_db_session  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture(name="router_client")
def router_client_fixture(db_session):
    def _override_db():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_post_message_threads_attachment_id_to_the_attached_document_turn(
    db_session, router_client
):
    """POST /chat/sessions/{id}/message with an attachment_id reaches the branch.

    Asserted on the mock of `_run_attached_document_turn` — the same shape as
    the gate test above, and for the same reason: a 200 with a plausible-looking
    answer while the attachment was dropped and the question answered as an
    ordinary SQL turn is exactly the bug, and is indistinguishable from success
    if you only check the response body.
    """
    import agents.query_agent as qa

    chat_session = ChatSession(tenant_id=MOCK_TENANT_ID, title="New Chat")
    db_session.add(chat_session)
    db_session.commit()
    db_session.refresh(chat_session)

    _, attachment = _attachment(
        db_session, tenant_id=MOCK_TENANT_ID, session_id=chat_session.id
    )

    branch = MagicMock(
        return_value={
            "content": "Attached-document turn ran.",
            "generated_sql": "",
            "citations": [],
            "result_invoice_ids": [],
        }
    )

    with patch.object(qa, "_run_attached_document_turn", branch), patch.object(
        qa, "classify_query"
    ) as classify:
        res = router_client.post(
            f"/api/v1/chat/sessions/{chat_session.id}/message",
            json={"content": "does this PO match the bill?", "attachment_id": str(attachment.id)},
        )

    assert res.status_code == 200, res.text
    assert res.json()["content"] == "Attached-document turn ran."
    # The endpoint took the attachment branch, and no LLM decided that.
    classify.assert_not_called()
    branch.assert_called_once()
    assert branch.call_args.kwargs["attachment_id"] == str(attachment.id)
    assert branch.call_args.kwargs["user_message"] == "does this PO match the bill?"
    assert branch.call_args.kwargs["session_id"] == str(chat_session.id)


def test_post_message_without_attachment_id_is_unchanged(db_session, router_client):
    """The parameter is additive: a body with no attachment_id routes as before."""
    import agents.query_agent as qa

    chat_session = ChatSession(tenant_id=MOCK_TENANT_ID, title="New Chat")
    db_session.add(chat_session)
    db_session.commit()
    db_session.refresh(chat_session)

    branch = MagicMock()
    fake_llm = MagicMock()
    fake_llm.invoke.return_value = MagicMock(content="Hello.")

    with patch.object(qa, "_run_attached_document_turn", branch), patch.object(
        qa, "classify_query", return_value="CHAT"
    ) as classify, patch.object(qa, "get_llm", return_value=fake_llm):
        res = router_client.post(
            f"/api/v1/chat/sessions/{chat_session.id}/message?sync=true",
            json={"content": "hi"},
        )

    assert res.status_code == 200, res.text
    branch.assert_not_called()
    classify.assert_called_once()
