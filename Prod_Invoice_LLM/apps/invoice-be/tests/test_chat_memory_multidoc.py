"""Feature 26 Phase 2 — memory and multi-document (Gaps 436–441).

One file per concern would have split six changes that share a fixture and a
turn-driver; they are tested together because they are one behaviour from the
user's side: the conversation remembers what it is about, and knows which
documents are on the table.

Nothing here asserts on prose. Every assertion is on a payload key, a database
column, a cache key, or which branch ran — the things that are true or false
regardless of how a model words the sentence.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import config
from models import ChatAttachment, ChatMessage, ChatSession, Invoice

engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)

TENANT = uuid4()


@pytest.fixture(autouse=True)
def generic_doc_chat_on(monkeypatch):
    """Every behaviour in this file is Part 2 behaviour, so the flag is ON for
    the whole file -- the same shape `test_chat_doc_content_branch.py` uses."""
    monkeypatch.setattr(config.settings, "ENABLE_GENERIC_DOC_CHAT", True)


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


# ---------------------------------------------------------------------------
# Fixtures — a real session, real rows, no network
# ---------------------------------------------------------------------------
def _session(db):
    s = ChatSession(tenant_id=TENANT, title="t")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _attachment(db, session, doc_type="PURCHASE_ORDER", **kw):
    defaults = dict(
        tenant_id=TENANT,
        session_id=session.id,
        filename=f"{doc_type.lower()}.pdf",
        blob_path=f"x/{uuid4()}.pdf",
        doc_type=doc_type,
        extraction_status="EXTRACTED",
        doc_number=kw.pop("doc_number", f"{doc_type[:3]}-1"),
        party_name=kw.pop("party_name", "Deccan Chemicals"),
        currency="INR",
        grand_total=kw.pop("grand_total", 1000.0),
        extracted_json=kw.pop(
            "extracted_json",
            {
                "doc_type": doc_type,
                "currency": "INR",
                "grand_total": 1000.0,
                "items": [
                    {"description": "Catalysts", "quantity": 8, "unit_price": 100, "amount": 800}
                ],
            },
        ),
    )
    defaults.update(kw)
    row = ChatAttachment(**defaults)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _message(db, session, role, content):
    m = ChatMessage(session_id=session.id, role=role, content=content)
    db.add(m)
    db.commit()
    return m


def _run(db, attachment, message, *, session=None, intent=None, attachment_ids=None):
    """Drive a real turn through the pre-route gate.

    The prompt is captured off `_answer_text`, which is what every narration
    branch actually calls -- capturing it on the LLM object would miss the
    streaming path (A3) entirely."""
    import agents.query_agent as qa

    seen = {}
    spans = [
        {
            "id": "p1",
            "document": "[Document type: CONTRACT | Page 1] Payment terms: Net 45 days.",
            "metadata": {"page": 1},
            "page": 1,
            "distance": 0.2,
        }
    ]

    def _capture(llm, system_prompt, progress, *a, **kw):
        seen["prompt"] = system_prompt
        return SimpleNamespace(content="ok")

    session_id = str(attachment.session_id) if attachment is not None else str(session.id)
    with patch(
        "services.chat_document_search.search_attachment_chunks", return_value=spans
    ) as search, patch.object(qa, "classify_query") as classify, patch.object(
        qa, "get_llm", autospec=True
    ), patch.object(qa, "tracked_llm_call"), patch.object(qa, "_answer_text", side_effect=_capture):
        result = qa._run_query_agent(
            session_id=session_id,
            user_message=message,
            tenant_id=str(TENANT),
            db_session=db,
            turn=MagicMock(),
            attachment_id=str(attachment.id) if attachment is not None else None,
            attachment_intent=intent,
            attachment_ids=attachment_ids,
        )
    return SimpleNamespace(
        result=result, search=search, prompt=seen.get("prompt", ""), classify=classify
    )


# ---------------------------------------------------------------------------
# Gap 438 — the answer cache key carries the tenant's rule set
# ---------------------------------------------------------------------------
def test_gap_438_the_cache_key_changes_when_a_chat_rule_is_committed(db_session):
    """A committed rule changes how every future answer is worded and filtered.
    Keyed without it, up to an hour of pre-rule answers kept being served."""
    from agents.query_agent import _cache_key, chat_rules_version
    from models import TenantChatRule

    before = chat_rules_version(str(TENANT), db_session)
    assert before == "none", "a tenant with no rules has a stable, non-empty marker"

    db_session.add(
        TenantChatRule(
            tenant_id=TENANT,
            category="terminology",
            pattern="spend",
            context_text="Always show amounts in lakhs",
            enabled=True,
        )
    )
    db_session.commit()
    after = chat_rules_version(str(TENANT), db_session)

    assert after != before
    assert _cache_key(str(TENANT), "what is my spend?", before) != _cache_key(
        str(TENANT), "what is my spend?", after
    )


def test_gap_438_a_rules_version_failure_degrades_to_an_unkeyed_cache(db_session):
    """The cache is an optimisation. A failure to read the rules must cost a
    cache dimension, never the turn."""
    from agents.query_agent import chat_rules_version

    broken = MagicMock()
    broken.exec.side_effect = RuntimeError("db down")
    assert chat_rules_version(str(TENANT), broken) == "na"


# ---------------------------------------------------------------------------
# Gap 436 — session focus
# ---------------------------------------------------------------------------
def test_gap_436_focus_is_written_from_the_result_and_rendered_as_one_line(db_session):
    from agents.query_agent import session_focus_block, update_session_focus

    session = _session(db_session)
    assert session_focus_block(str(session.id), db_session) == ""

    update_session_focus(
        str(session.id),
        db_session,
        {"result_invoice_ids": [str(uuid4()), str(uuid4())], "focus": {"vendor": "Deccan Chemicals"}},
    )
    db_session.refresh(session)

    assert session.focus["vendor"] == "Deccan Chemicals"
    assert len(session.focus["invoice_ids"]) == 2
    line = session_focus_block(str(session.id), db_session)
    assert "Deccan Chemicals" in line and "2 invoice(s)" in line


def test_gap_436_focus_is_a_snapshot_not_an_accumulator(db_session):
    """Turn 20 must not still be answering about a vendor abandoned at turn 3."""
    from agents.query_agent import update_session_focus

    session = _session(db_session)
    update_session_focus(str(session.id), db_session, {"focus": {"vendor": "Vendor A"}})
    update_session_focus(str(session.id), db_session, {"focus": {"vendor": "Vendor B"}})
    db_session.refresh(session)

    assert session.focus == {"vendor": "Vendor B"}


def test_gap_436_an_empty_result_leaves_the_previous_focus_alone(db_session):
    from agents.query_agent import update_session_focus

    session = _session(db_session)
    update_session_focus(str(session.id), db_session, {"focus": {"vendor": "Vendor A"}})
    update_session_focus(str(session.id), db_session, {"content": "hello"})
    db_session.refresh(session)

    assert session.focus == {"vendor": "Vendor A"}


# ---------------------------------------------------------------------------
# Gap 437 — the rolling history summary
# ---------------------------------------------------------------------------
def test_gap_437_history_beyond_the_window_is_condensed_once_and_reused(db_session):
    from agents.query_agent import get_chat_history

    session = _session(db_session)
    for i in range(30):
        _message(db_session, session, "user", f"question number {i} " + ("padding " * 60))

    window = get_chat_history(str(session.id), db_session, max_tokens=200)
    db_session.refresh(session)

    assert session.history_summary, "the dropped half is condensed onto the session"
    assert "EARLIER IN THIS CONVERSATION" in window

    first = session.history_summary
    get_chat_history(str(session.id), db_session, max_tokens=200)
    db_session.refresh(session)
    assert session.history_summary == first, "condensed once, then reused"


def test_gap_437_a_short_conversation_writes_no_summary(db_session):
    from agents.query_agent import get_chat_history

    session = _session(db_session)
    _message(db_session, session, "user", "hello")
    get_chat_history(str(session.id), db_session)
    db_session.refresh(session)

    assert session.history_summary is None


def test_gap_437_the_summary_is_deterministic_and_makes_no_model_call(db_session):
    """Hard rule 3: no model between the user and text attributed to them."""
    import agents.query_agent as qa

    session = _session(db_session)
    for i in range(30):
        _message(db_session, session, "user", f"turn {i} " + ("padding " * 60))

    with patch.object(qa, "get_llm") as get_llm, patch.object(qa, "_fast_llm") as fast:
        qa.get_chat_history(str(session.id), db_session, max_tokens=200)
    get_llm.assert_not_called()
    fast.assert_not_called()


# ---------------------------------------------------------------------------
# Gap 439 — the manifest: every document on the table
# ---------------------------------------------------------------------------
def test_gap_439_the_manifest_lists_every_extracted_attachment_and_marks_the_active_one(db_session):
    from agents.query_agent import attachment_manifest_block, session_attachments

    session = _session(db_session)
    po = _attachment(db_session, session, "PURCHASE_ORDER", doc_number="PO-1")
    dn = _attachment(db_session, session, "DELIVERY_NOTE", doc_number="DN-1")
    _attachment(db_session, session, "GRN", doc_number="GRN-1", extraction_status="EXTRACT_FAILED")

    rows = session_attachments(str(session.id), TENANT, db_session)
    assert [r.doc_number for r in rows] == ["PO-1", "DN-1"], "failed extractions are not on the table"

    block = attachment_manifest_block(rows, active_id=str(po.id))
    assert "PO-1" in block and "DN-1" in block
    assert "1 line(s)" in block
    active_line = [ln for ln in block.splitlines() if "PO-1" in ln][0]
    assert "the document this question is about" in active_line
    assert "the document this question is about" not in [
        ln for ln in block.splitlines() if "DN-1" in ln
    ][0]
    assert str(dn.id) not in block, "ids are not prompt material; the numbers identify documents"


def test_gap_439_another_tenants_attachment_is_never_on_the_table(db_session):
    from agents.query_agent import session_attachments

    session = _session(db_session)
    _attachment(db_session, session, "PURCHASE_ORDER", doc_number="MINE")
    assert session_attachments(str(session.id), uuid4(), db_session) == []


def test_gap_439_the_comparison_prompt_carries_the_manifest(db_session):
    session = _session(db_session)
    po = _attachment(db_session, session, "PURCHASE_ORDER", doc_number="PO-1")
    _attachment(db_session, session, "CONTRACT", doc_number="MSA-1")
    inv = Invoice(
        tenant_id=TENANT,
        file_path="x.pdf",
        invoice_number="INV-1",
        currency="INR",
        grand_total=1000.0,
        status="COMPLETED",
        items=[{"description": "Catalysts", "quantity": 10, "unit_price": 100, "amount": 1000}],
    )
    db_session.add(inv)
    db_session.commit()
    po.confirmed_invoice_ids = [str(inv.id)]
    db_session.add(po)
    db_session.commit()

    run = _run(db_session, po, "does this match my invoice?")
    run.classify.assert_not_called()
    assert "DOCUMENTS ATTACHED TO THIS CONVERSATION" in run.prompt
    assert "MSA-1" in run.prompt


# ---------------------------------------------------------------------------
# Gap 440 — attachment turns see recent history
# ---------------------------------------------------------------------------
def test_gap_440_the_digest_is_summaries_not_transcript(db_session):
    from agents.query_agent import recent_turn_digest

    session = _session(db_session)
    _message(db_session, session, "user", "which line is over-billed?")
    _message(db_session, session, "assistant", "x" * 400)

    digest = recent_turn_digest(str(session.id), db_session)
    assert "which line is over-billed?" in digest
    assert "..." in digest, "long turns are truncated, never pasted whole"
    assert len(digest) < 600


def test_gap_440_the_content_branch_prompt_carries_the_digest(db_session):
    session = _session(db_session)
    contract = _attachment(db_session, session, "CONTRACT", doc_number="MSA-1")
    _message(db_session, session, "user", "an earlier question about freight")

    run = _run(db_session, contract, "what are the payment terms?", )
    assert "RECENT TURNS IN THIS CONVERSATION" in run.prompt
    assert "an earlier question about freight" in run.prompt


# ---------------------------------------------------------------------------
# Gap 441 — carrying the attachment forward
# ---------------------------------------------------------------------------
def test_gap_441_a_deictic_question_is_carried_onto_the_attached_document(db_session):
    session = _session(db_session)
    po = _attachment(db_session, session, "PURCHASE_ORDER")

    run = _run(
        db_session, None, "what does the purchase order say about delivery?", session=session
    )
    # The gate fired: no routing call was made, and the turn came back on the
    # attachment contract rather than as an ordinary answer.
    run.classify.assert_not_called()
    assert "attachment_clarification" in run.result or run.search.called
    assert po.extraction_status == "EXTRACTED"


@pytest.mark.parametrize(
    "message",
    ["what did we spend last month?", "show me overdue invoices", "hello"],
)
def test_gap_441_an_ordinary_question_is_not_re_routed(db_session, message):
    """The carry-forward must be narrow. An ordinary ledger question in a session
    that happens to have an attachment is still an ordinary ledger question."""
    import agents.query_agent as qa

    session = _session(db_session)
    _attachment(db_session, session, "PURCHASE_ORDER")

    with patch.object(qa, "_run_attached_document_turn") as attached, patch.object(
        qa, "classify_query", return_value="CHAT"
    ), patch.object(qa, "get_llm"), patch.object(qa, "tracked_llm_call"), patch.object(
        qa, "_answer_text", return_value=SimpleNamespace(content="ok")
    ), patch.object(qa, "get_cached_answer", return_value=None):
        qa._run_query_agent(
            session_id=str(session.id),
            user_message=message,
            tenant_id=str(TENANT),
            db_session=db_session,
            turn=MagicMock(),
        )
    attached.assert_not_called()


def test_gap_441_a_session_with_no_attachment_is_untouched(db_session):
    import agents.query_agent as qa

    session = _session(db_session)
    with patch.object(qa, "_run_attached_document_turn") as attached, patch.object(
        qa, "classify_query", return_value="CHAT"
    ), patch.object(qa, "get_llm"), patch.object(qa, "tracked_llm_call"), patch.object(
        qa, "_answer_text", return_value=SimpleNamespace(content="ok")
    ), patch.object(qa, "get_cached_answer", return_value=None):
        qa._run_query_agent(
            session_id=str(session.id),
            user_message="what does the purchase order say?",
            tenant_id=str(TENANT),
            db_session=db_session,
            turn=MagicMock(),
        )
    attached.assert_not_called()


# ---------------------------------------------------------------------------
# Gap 387 — attachment vs attachment
# ---------------------------------------------------------------------------
def test_gap_387_a_po_against_a_delivery_note_compares_the_two_documents(db_session):
    """The v1 boundary, closed. No invoice is read; the answer is a line diff of
    two documents the user attached."""
    session = _session(db_session)
    po = _attachment(db_session, session, "PURCHASE_ORDER", doc_number="PO-1")
    _attachment(
        db_session,
        session,
        "DELIVERY_NOTE",
        doc_number="DN-1",
        grand_total=None,
        extracted_json={
            "doc_type": "DELIVERY_NOTE",
            "items": [
                {"description": "Catalysts", "quantity": 6, "amount": None},
                {"description": "Spare gasket", "quantity": 1, "amount": None},
            ],
        },
    )

    run = _run(db_session, po, "compare this against the delivery note")
    payload = run.result["attachment_pair_comparison"]

    assert payload["mode"] == "quantity", "a delivery note prices nothing; money is not compared"
    assert [d["doc_number"] for d in payload["documents"]] == ["PO-1", "DN-1"]
    assert run.result["line_items"], "the matched line is reported"
    assert [r["description"] for r in run.result["unmatched"]["invoice_lines"]] == ["Spare gasket"]
    assert run.result["result_invoice_ids"] == [], "no invoice was involved"
    assert "attachment_comparison" not in run.result


def test_gap_387_two_priced_documents_compare_on_both_money_and_quantity(db_session):
    from agents.query_agent import pair_comparison_mode

    assert pair_comparison_mode("QUOTATION", "PURCHASE_ORDER") == "both"
    assert pair_comparison_mode("PURCHASE_ORDER", "GRN") == "quantity"
    assert pair_comparison_mode("GRN", "PURCHASE_ORDER") == "quantity"


def test_gap_387_an_explicit_second_id_selects_the_partner(db_session):
    session = _session(db_session)
    po = _attachment(db_session, session, "PURCHASE_ORDER", doc_number="PO-1")
    grn = _attachment(db_session, session, "GRN", doc_number="GRN-1")
    _attachment(db_session, session, "CONTRACT", doc_number="MSA-1")

    run = _run(db_session, po, "do these agree?", attachment_ids=[str(po.id), str(grn.id)])
    assert [d["doc_number"] for d in run.result["attachment_pair_comparison"]["documents"]] == [
        "PO-1",
        "GRN-1",
    ]


def test_gap_387_an_ambiguous_pairing_is_never_guessed(db_session):
    """Two candidate documents and nothing naming a type: the turn must fall back
    to the invoice comparison it was always going to run, not pick one."""
    from agents.query_agent import select_comparison_partner

    session = _session(db_session)
    po = _attachment(db_session, session, "PURCHASE_ORDER")
    a = _attachment(db_session, session, "DELIVERY_NOTE", doc_number="DN-1")
    b = _attachment(db_session, session, "GRN", doc_number="GRN-1")

    assert select_comparison_partner(po, [a, b], "do these agree?") is None
    assert select_comparison_partner(po, [a, b], "compare this to the GRN") is b
    assert select_comparison_partner(po, [a], "do these agree?") is a


def test_gap_387_the_pair_branch_reads_no_invoice_at_all(db_session):
    """Structural, not by wording: the ledger is not consulted, so no unconfirmed
    figure about a payable can reach this answer."""
    import agents.query_agent as qa

    session = _session(db_session)
    po = _attachment(db_session, session, "PURCHASE_ORDER")
    _attachment(db_session, session, "DELIVERY_NOTE", doc_number="DN-1")

    with patch(
        "services.document_comparison.find_candidate_invoices"
    ) as find, patch(
        "services.document_comparison.compare_reference_to_invoices"
    ) as compare_inv, patch.object(qa, "get_llm"), patch.object(
        qa, "tracked_llm_call"
    ), patch.object(qa, "_answer_text", return_value=SimpleNamespace(content="ok")):
        qa._run_query_agent(
            session_id=str(session.id),
            user_message="compare this to the delivery note",
            tenant_id=str(TENANT),
            db_session=db_session,
            turn=MagicMock(),
            attachment_id=str(po.id),
        )
    find.assert_not_called()
    compare_inv.assert_not_called()
