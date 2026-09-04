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
import inspect
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


@pytest.fixture(name="no_vector_tier3")
def no_vector_tier3_fixture():
    """Gap 401 — keep the TIER-SELECTION tests off the real embedding model.

    Tier 3 (E-4) made `find_candidate_invoices()` call `query_invoice_chunks()`
    whenever tiers 1 and 2 both come back empty, which is precisely the state the
    two tests below construct on purpose. `.env` carries `MOCK_EMBEDDINGS=false`,
    so those two SQL-tiering unit tests began loading a real SentenceTransformer
    and running a real vector query -- and on Windows, under memory pressure from
    a concurrent Playwright run, torch took the whole pytest process down with a
    native access violation mid-suite. No traceback, no failure list, 2600 results
    lost; only re-running the suite alone revealed the actual 16.

    Patched at `chroma_client.query_invoice_chunks` because
    `_tier3_candidates()` imports it inside the function body.

    Deliberately a NAMED fixture rather than module-autouse: the sections lower in
    this file run against conftest's real in-memory `EphemeralClient` on purpose,
    and blanketing the module would silently gut them.
    """
    with patch("chroma_client.query_invoice_chunks", return_value=[]) as stub:
        yield stub


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


def test_zero_match_is_reported_not_widened(db_session, no_vector_tier3):
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
    # Tier 3 was consulted and had nothing -- asserted, because "tier 0" would
    # also be the answer if tier 3 had never been reached at all, and that is the
    # regression this call ordering is worth protecting.
    no_vector_tier3.assert_called_once()


def test_matching_is_tenant_scoped(db_session, no_vector_tier3):
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


def test_the_answer_turn_calls_get_llm_with_a_signature_the_real_one_accepts(db_session):
    """Gap 367: the same path as the test above, but against an autospec'd `get_llm`.

    The test above patches `get_llm` with a bare `MagicMock`, which accepts any
    keyword argument at all. That is exactly how `get_llm(temperature=0)` sat on
    line 3028 passing its test while raising `TypeError` on every real call —
    `get_llm()`'s signature is `(max_tokens=None)` and it forwards no `**kwargs`,
    so the answer turn died and `routers/chat.py`'s broad handler turned it into a
    generic "something went wrong".

    `autospec=True` binds the mock to the real `utils.llm.get_llm` signature, so
    an argument the real function would reject fails here the same way it failed
    in production. This is the only autospec'd patch in the suite — deliberately
    scoped to this one call site, not a suite-wide convention change.
    """
    import agents.query_agent as qa

    _, attachment = _attachment(db_session)
    inv = _invoice(db_session, po_number="PO-2024/0043", grand_total=1380.0)
    attachment.confirmed_invoice_ids = [str(inv.id)]
    db_session.add(attachment)
    db_session.commit()

    turn = MagicMock()

    with patch.object(qa, "classify_query"), patch.object(
        qa, "get_llm", autospec=True
    ) as get_llm, patch.object(qa, "tracked_llm_call"):
        get_llm.return_value.invoke.return_value = MagicMock(
            content="The invoice is 200 higher than the PO."
        )
        result = qa._run_query_agent(
            session_id=str(attachment.session_id),
            user_message="was I over-billed?",
            tenant_id=str(TENANT),
            db_session=db_session,
            turn=turn,
            attachment_id=str(attachment.id),
        )

    # The call happened (this is the answer path, not the confirmation path) and
    # survived signature checking.
    get_llm.assert_called_once()
    # Belt and braces: the signature is checkable, so check it explicitly rather
    # than relying only on the call above not having raised.
    from utils.llm import get_llm as real_get_llm

    inspect.signature(real_get_llm).bind(
        *get_llm.call_args.args, **get_llm.call_args.kwargs
    )
    assert "temperature" not in get_llm.call_args.kwargs

    # And the turn still produced its answer, so the fix did not just silence the
    # call — the narration came back and the deterministic diff is still attached.
    assert result["content"] == "The invoice is 200 higher than the PO."
    assert result["attachment_comparison"]["compared_count"] == 1


# ---------------------------------------------------------------------------
# The REFERENCE extraction profile (C2) — additive
# ---------------------------------------------------------------------------
def test_reference_profile_exists_and_is_additive():
    """Updated by Feature 27 G6 (BE Gap 384): the last assertion used to read
    `resolve_direction_profile("NONSENSE").schema is InvoiceExtractionSchema` —
    the silent-INBOUND fallback E9 exists to remove. The property this test cares
    about ("nothing can reach REFERENCE by accident") is unchanged and now holds
    more strongly: an unknown direction reaches no profile at all."""
    from agents.extraction_agent import (
        InvoiceExtractionSchema,
        OutboundInvoiceExtractionSchema,
        ReferenceDocExtractionSchema,
        UnknownFlowDirectionError,
        resolve_direction_profile,
    )

    ref = resolve_direction_profile("REFERENCE")
    assert ref.schema is ReferenceDocExtractionSchema
    assert ref.required_fields == ()
    assert ref.passed_status == "EXTRACTED"
    assert ref.review_status == "EXTRACT_FAILED"
    assert ref.legacy_audit_path_shim is False

    # The two existing profiles are untouched, and the absent-direction default
    # is still INBOUND — nothing can reach REFERENCE by accident.
    assert resolve_direction_profile("INBOUND").schema is InvoiceExtractionSchema
    assert resolve_direction_profile("OUTBOUND").schema is OutboundInvoiceExtractionSchema
    assert resolve_direction_profile(None).schema is InvoiceExtractionSchema
    with pytest.raises(UnknownFlowDirectionError):
        resolve_direction_profile("NONSENSE")


def test_reference_schema_carries_the_doc_type_discriminator():
    from agents.extraction_agent import ReferenceDocExtractionSchema

    doc = ReferenceDocExtractionSchema(doc_type="QUOTATION", grand_total=1180.0)
    assert doc.doc_type == "QUOTATION"
    # One schema with a discriminator, not two parallel schemas.
    assert "doc_type" in ReferenceDocExtractionSchema.model_fields


# ---------------------------------------------------------------------------
# MockInvoiceLLM's content-branch marker (Feature 26 Part 2, task H1 / Gap 368)
#
# `MockInvoiceLLM` is not just a test convenience: `build_llm()` returns it for
# `LLM_PROVIDER=mock`, for this suite, AND as the fail-safe fallback when
# `LLM_PROVIDER=azure` with no usable `AZURE_OPENAI_API_KEY` — so a misconfigured
# real deployment gets it too. Without a content-branch marker, every one of
# those three situations answers a document-content question with the SAGE
# greeting about spend summaries.
#
# H5 has not landed yet, so these test the mock directly rather than through
# `_run_attached_document_turn()`. The contract they pin down is the marker
# string itself, which H5's prompt is required to carry.
# ---------------------------------------------------------------------------
def test_mock_llm_answers_the_content_branch_marker_with_document_content():
    from utils.llm import CONTENT_BRANCH_PROMPT_MARKER, MockInvoiceLLM

    prompt = (
        f"{CONTENT_BRANCH_PROMPT_MARKER}.\n\n"
        "<<<DOCUMENT_TEXT_START>>>\nPayment terms: Net 30.\n<<<DOCUMENT_TEXT_END>>>\n\n"
        "<<<USER_QUESTION_START>>>what are the payment terms?<<<USER_QUESTION_END>>>"
    )

    content = MockInvoiceLLM().invoke(prompt).content

    # The canned document answer, not the greeting fall-through.
    assert "Attached Document" in content
    assert "Payment terms" in content
    assert "SAGE" not in content
    # It also carries E-3's refusal-with-redirect wording, so a mock-mode run
    # exercises the shape the real content branch is specified to produce
    # rather than an unrelated placeholder.
    assert "ask me to compare them" in content


def test_mock_llm_content_branch_is_checked_before_the_rag_substring_marker():
    """The RAG branch matches the bare substring "rag" — inside "storage" too.

    The content-branch prompt interpolates verbatim document text, so this
    collision is not hypothetical. Ordering is the fix, and this is the test
    that keeps a future edit from reordering the branches back.
    """
    from utils.llm import CONTENT_BRANCH_PROMPT_MARKER, MockInvoiceLLM

    prompt = (
        f"{CONTENT_BRANCH_PROMPT_MARKER}.\n\n"
        "<<<DOCUMENT_TEXT_START>>>\nLine 1: cold storage handling charge, average rate.\n"
        "<<<DOCUMENT_TEXT_END>>>"
    )

    content = MockInvoiceLLM().invoke(prompt).content

    assert "Attached Document" in content
    # The invoice-RAG canned answer must not be what a document question gets.
    assert "Document Content Insights" not in content
    assert "citation pills" not in content


def test_mock_llm_without_the_marker_still_falls_through_to_the_sage_greeting():
    """Regression guard: the new branch is additive to all three existing ones."""
    from utils.llm import MockInvoiceLLM

    llm = MockInvoiceLLM()

    greeting = llm.invoke("The user said: hello there").content
    assert "I am **SAGE**" in greeting
    assert "Attached Document" not in greeting

    sql = llm.invoke("Database query results:\n[{'total_spend': 1180}]").content
    assert "Invoice Data Analysis" in sql

    rag = llm.invoke("Context chunks:\n--- CHUNK ---\nNet 30\n").content
    assert "Document Content Insights" in rag


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
    db_session, router_client, monkeypatch
):
    """POST /chat/sessions/{id}/message with an attachment_id reaches the branch.

    Asserted on the mock of `_run_attached_document_turn` — the same shape as
    the gate test above, and for the same reason: a 200 with a plausible-looking
    answer while the attachment was dropped and the question answered as an
    ordinary SQL turn is exactly the bug, and is indistinguishable from success
    if you only check the response body.

    THE SYNC PATH IS PINNED EXPLICITLY (task H7). Until H7 this test did not have
    to say so: `use_async_queue` carried `and payload.attachment_id is None`, so
    an attachment turn was FORCED synchronous and this assertion held whatever
    the flag said. H7 removed that condition — the queue now carries the id
    through all four sites — so with `ENABLE_ASYNC_CHAT_QUEUE=true` in the
    developer `.env` and Redis reachable, the same request correctly returns 202
    and the agent runs later in the worker.

    What this test is about is the ROUTER threading the id into the agent, which
    is a synchronous-path claim, so the path is now stated rather than inherited.
    The async half is V-16..V-18's, against real Redis. Leaving it unpinned would
    make the result depend on whether a container happens to be running — BE Gap
    390's exact shape.
    """
    import agents.query_agent as qa
    import config

    monkeypatch.setattr(config.settings, "ENABLE_ASYNC_CHAT_QUEUE", False)

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


# ---------------------------------------------------------------------------
# The embed step + E-6's three columns (Feature 26 Part 2, task H4 / Gap 374)
#
# These are deliberately driven through the REAL upload endpoint rather than by
# calling `index_attachment_chunks()` directly. `tests/test_chat_document_search.py`
# already proves that function works in isolation (task H3); what was missing
# after H3 was that **nothing called it**, so a test that calls it again would
# re-prove the module and still not prove the wiring. Every assertion below
# starts at `POST /chat/sessions/{id}/attachments`.
#
# What is stubbed and what is real, stated so the evidence is not overclaimed:
#   * Document Intelligence (`_run_ocr`) and the extraction graph are stubbed --
#     they need Azure, and neither is what H4 changed.
#   * Blob storage is a local file (the same fallback `services/storage.py`
#     already has for offline dev), so the indexer's `fitz` read of the stored
#     PDF is a real read of a real PDF.
#   * Chroma is REAL (conftest's session-autouse in-memory `EphemeralClient`),
#     so "the chunks are queryable afterwards" is an actual vector-store round
#     trip, not a mock's return value.
#   * Embeddings are mocked (`get_embedding_model() -> None`, the same thing
#     `MOCK_EMBEDDINGS=true` does), so nothing here asserts on *ranking* -- the
#     assertions are about which chunks exist and which attachment they belong
#     to, both of which are exact.
# SQLite, no Postgres: not a hard-rule-2 verification and none is claimed.
# ---------------------------------------------------------------------------
from contextlib import contextmanager  # noqa: E402
from uuid import UUID  # noqa: E402

import fitz  # noqa: E402

PO_PAGE_1 = "Meridian Ironworks purchase order net ninety day payment terms"
PO_PAGE_2 = "Delivery to the Basingstoke depot before the equinox"

_STUB_EXTRACTED = {
    "doc_type": "PURCHASE_ORDER",
    "doc_number": "PO-2024/0043",
    "party_name": "Meridian Ironworks",
    "doc_date": "2026-03-01",
    "currency": "INR",
    "grand_total": 1180.0,
}


@contextmanager
def _stubbed_extraction(extracted):
    """Stand in for the OCR round trip and the extraction graph.

    Patched on their defining modules because `_extract_attachment()` imports
    both *inside* the function, so the name is resolved at call time.
    """
    import agents.extraction_agent as extraction_agent
    import queue_worker.handlers as handlers

    with patch.object(
        handlers, "_run_ocr", return_value={"content": "ocr text"}
    ), patch.object(
        extraction_agent, "run_extraction_agent", return_value={"extracted_data": extracted}
    ):
        yield


@pytest.fixture(autouse=True)
def extraction_runs_inline(monkeypatch):
    """Gap 452: uploads now queue extraction when Redis is reachable. Every test
    in this file was written against the inline pipeline and asserts on the
    row's state straight after the upload returns, so the queue is made
    unavailable here -- which is a real path (Redis down), not a test-only
    shortcut -- and the pipeline runs inline exactly as those tests expect.
    The queued path has its own tests in `test_attachment_upload_ux.py`."""
    from services.chat_queue import ChatQueueService

    monkeypatch.setattr(
        ChatQueueService, "enqueue_attachment_extraction", staticmethod(lambda **kw: None)
    )


@pytest.fixture(name="mock_embeddings")
def mock_embeddings_fixture():
    """`get_embedding_model() -> None` is exactly what `MOCK_EMBEDDINGS=true`
    does, pinned here rather than depending on the developer's `.env` (which
    sets `MOCK_EMBEDDINGS=false`) or on which test module imported `config`
    first."""
    import chroma_client

    with patch.object(chroma_client, "get_embedding_model", return_value=None):
        yield


@pytest.fixture(name="local_blob")
def local_blob_fixture(tmp_path):
    """Keep the uploaded bytes on local disk so the indexer's read of the stored
    PDF is real. Patched rather than relying on `services/storage.py`'s own local
    fallback, because that fallback only triggers when
    `AZURE_STORAGE_CONNECTION_STRING` is unset and this repo's `.env` sets it."""
    import services.storage as storage

    def _fake_upload(file_data: bytes, tenant_id: str, invoice_id: str) -> str:
        path = str(tmp_path / f"{invoice_id.replace('/', '_')}.pdf")
        with open(path, "wb") as fh:
            fh.write(file_data)
        return path

    with patch.object(storage, "upload_pdf_to_blob_storage", _fake_upload):
        yield tmp_path


def _pdf_bytes(pages) -> bytes:
    doc = fitz.open()
    for text in pages:
        doc.new_page().insert_text((50, 50), text)
    data = doc.tobytes()
    doc.close()
    return data


def _owned_session(db_session) -> ChatSession:
    chat_session = ChatSession(tenant_id=MOCK_TENANT_ID, title="New Chat")
    db_session.add(chat_session)
    db_session.commit()
    db_session.refresh(chat_session)
    return chat_session


def _upload(router_client, session_id, pages=(PO_PAGE_1, PO_PAGE_2)):
    return router_client.post(
        f"/api/v1/chat/sessions/{session_id}/attachments",
        files={"file": ("po.pdf", _pdf_bytes(pages), "application/pdf")},
    )


def _reload_attachment(db_session, attachment_id) -> ChatAttachment:
    # The endpoint wrote through this same Session, so expire first — otherwise
    # the identity map hands back the in-memory object and a column that was
    # never actually persisted would still read as set.
    db_session.expire_all()
    return db_session.get(ChatAttachment, UUID(attachment_id))


def test_a_successful_upload_indexes_the_document_and_records_the_index_state(
    db_session, router_client, local_blob, mock_embeddings
):
    """The wiring H3 left open: an upload that extracts must also embed.

    Asserted on all three of the things that can independently be true — the
    count on the row, the timestamp on the row, and the chunks actually being in
    `chat_docs_{tenant}` and retrievable. `chunk_count > 0` alone would pass on
    a function that wrote the number and no chunks.
    """
    from services.chat_document_search import search_attachment_chunks

    chat_session = _owned_session(db_session)

    with _stubbed_extraction(_STUB_EXTRACTED):
        res = _upload(router_client, chat_session.id)

    assert res.status_code == 200, res.text
    assert res.json()["extraction_status"] == "EXTRACTED"

    row = _reload_attachment(db_session, res.json()["id"])
    assert row.chunk_count == 2, "one chunk per page, as E-2 specifies"
    assert row.indexed_at is not None

    # And the chunks are genuinely queryable — a real round trip through the
    # sibling collection, scoped to this attachment.
    hits = search_attachment_chunks(row.id, MOCK_TENANT_ID, "what are the payment terms?")
    assert len(hits) == 2
    texts = "\n".join(h["document"] for h in hits)
    assert PO_PAGE_1 in texts and PO_PAGE_2 in texts
    # E-2's header rode along, so a retrieved chunk still says what kind of
    # document it came from.
    assert "[Document type: PURCHASE_ORDER" in texts


def test_gap_430_doc_type_comes_from_the_feature_27_classifier_first(
    db_session, router_client, local_blob, mock_embeddings
):
    """The classifier's verdict is at the TOP level of the result; the
    REFERENCE schema field only knows PO/QUOTATION/OTHER. A statement of
    account must land as STATEMENT_OF_ACCOUNT, not OTHER."""
    import agents.extraction_agent as extraction_agent
    import queue_worker.handlers as handlers

    chat_session = _owned_session(db_session)
    extracted = {**_STUB_EXTRACTED, "doc_type": "OTHER", "doc_number": "SOA-2026-06"}
    with patch.object(
        handlers, "_run_ocr", return_value={"content": "ocr text"}
    ), patch.object(
        extraction_agent,
        "run_extraction_agent",
        return_value={"extracted_data": extracted, "doc_type": "STATEMENT_OF_ACCOUNT"},
    ):
        res = _upload(router_client, chat_session.id)

    assert res.status_code == 200, res.text
    assert res.json()["doc_type"] == "STATEMENT_OF_ACCOUNT"

    # Flag off / classifier absent: the schema field is still the fallback.
    with _stubbed_extraction({**_STUB_EXTRACTED, "doc_type": "QUOTATION"}):
        res = _upload(router_client, chat_session.id)
    assert res.json()["doc_type"] == "QUOTATION"


def test_a_failed_extraction_never_reaches_the_indexer(db_session, router_client, local_blob):
    """EXTRACT_FAILED means we could not read the document at all.

    Asserted on the mock rather than on `chunk_count == 0`: a call that ran and
    happened to write nothing leaves the row looking identical to one that was
    never made, and the point here is that the embedding round trip is not spent.
    """
    import services.chat_document_search as chat_document_search

    chat_session = _owned_session(db_session)

    with _stubbed_extraction({}), patch.object(
        chat_document_search, "index_attachment_chunks"
    ) as indexer:
        res = _upload(router_client, chat_session.id)

    assert res.status_code == 200, res.text
    assert res.json()["extraction_status"] == "EXTRACT_FAILED"
    indexer.assert_not_called()

    row = _reload_attachment(db_session, res.json()["id"])
    assert row.chunk_count == 0
    assert row.indexed_at is None


def test_an_indexing_failure_does_not_fail_the_upload_and_stays_visible(
    db_session, router_client, local_blob
):
    """Indexing is best-effort, and the failure is inspectable rather than lost.

    The asymmetry is deliberate: chunks serve Part 2's content branch, while
    Part 1's whole comparison path reads the denormalised columns and needs none
    of them — so a Chroma failure must not take away a working feature. What it
    must not do either is disappear: `chunk_count=0` with `indexed_at=None` on an
    EXTRACTED row is the state one SQL predicate can find.
    """
    import services.chat_document_search as chat_document_search

    chat_session = _owned_session(db_session)

    with _stubbed_extraction(_STUB_EXTRACTED), patch.object(
        chat_document_search,
        "index_attachment_chunks",
        side_effect=RuntimeError("chroma is down"),
    ):
        res = _upload(router_client, chat_session.id)

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["extraction_status"] == "EXTRACTED"
    # The Part 1 comparison path's inputs all survived the indexing failure.
    assert body["doc_number"] == "PO-2024/0043"
    assert body["party_name"] == "Meridian Ironworks"
    assert body["grand_total"] == 1180.0

    row = _reload_attachment(db_session, body["id"])
    assert row.chunk_count == 0
    assert row.indexed_at is None


def test_the_three_new_columns_default_safely_and_expires_at_is_stamped_at_upload(
    db_session, router_client, local_blob, mock_embeddings
):
    """E-6: every column is nullable or defaulted, so no existing row is invalid.

    A row constructed the way Part 1 constructs one — which is also the shape
    every pre-migration row has — must still be valid, and its `expires_at` must
    read as "no expiry" rather than as "expired at the epoch" (H8's sweeper
    turns on that distinction).
    """
    from config import get_settings

    _, part1_shaped = _attachment(db_session)
    assert part1_shaped.chunk_count == 0
    assert part1_shaped.indexed_at is None
    assert part1_shaped.expires_at is None

    chat_session = _owned_session(db_session)
    with _stubbed_extraction(_STUB_EXTRACTED):
        res = _upload(router_client, chat_session.id)

    row = _reload_attachment(db_session, res.json()["id"])
    assert row.expires_at is not None
    # Stamped from `created_at` at upload time, not computed at read time, so a
    # later change to the knob cannot retroactively expire this document.
    assert row.expires_at - row.created_at == timedelta(
        days=get_settings().CHAT_ATTACHMENT_TTL_DAYS
    )


def test_deleting_the_session_removes_the_attachment_row_and_its_chunks(
    db_session, router_client, local_blob, mock_embeddings
):
    """The one place a ChatAttachment is deleted today.

    `ChatAttachment.session_id` is a real FK to `chatsession.id`, so the row has
    to go before the session does — and its chunks have to go with it, because
    the row and its chunks are one object stored twice and nothing else in the
    system ever cleans a `chat_docs_*` collection up.
    """
    from services.chat_document_search import search_attachment_chunks

    chat_session = _owned_session(db_session)
    with _stubbed_extraction(_STUB_EXTRACTED):
        res = _upload(router_client, chat_session.id)

    attachment_id = UUID(res.json()["id"])
    assert search_attachment_chunks(attachment_id, MOCK_TENANT_ID, "payment terms")

    delete_res = router_client.delete(f"/api/v1/chat/sessions/{chat_session.id}")

    assert delete_res.status_code == 204, delete_res.text
    db_session.expire_all()
    assert db_session.get(ChatAttachment, attachment_id) is None
    assert search_attachment_chunks(attachment_id, MOCK_TENANT_ID, "payment terms") == []
