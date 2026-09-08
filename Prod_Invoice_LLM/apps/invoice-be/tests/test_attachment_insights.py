"""Feature 30 tasks 30.1 / 30.2 / 30.12 — the chat-attachment intelligence
bubble, against REAL Postgres with `LLM_PROVIDER=mock`.

Verification plan 30.1: "INVOICE and OTHER attachments -> no turn, rows
byte-identical; PO with billed invoices -> one assistant turn,
`agreed_vs_billed.status == ok` with exact figures; a card that raises ->
`blocked`, turn still posts; flag off -> nothing."

Verification plan 30.2: "sync bubble posted before the job runs; job updates the
same message, `insights_version` 1->2; answer-contract gate rejects a narration
with a figure not in the facts JSON and the template text stands."

No live model anywhere: the narration LLM is a stub object with an `invoke()`,
and the two tests that exercise the gate assert on the gate's decision, not on
any wording a real model would produce.
"""
import os
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from models import ChatAttachment, ChatMessage, ChatSession, Insight, Invoice  # noqa: E402
from services import attachment_insights as ai  # noqa: E402


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


@pytest.fixture(name="flag_on")
def flag_on_fixture(monkeypatch):
    """`ENABLE_ATTACHMENT_INSIGHTS` forced ON for one test.

    Forced with monkeypatch rather than read from the environment — Gap 461's
    lesson: a parity test that reads the flag at import time asserts flag-OFF
    behaviour while running flag-ON, and passes for the wrong reason.
    """
    from config import get_settings

    monkeypatch.setattr(get_settings(), "ENABLE_ATTACHMENT_INSIGHTS", True, raising=False)
    yield


@pytest.fixture(name="world")
def world_fixture(pg_session):
    """A tenant with a PO attachment, and an invoice that bills 23,200 over it."""
    tenant_id = uuid4()
    session_row = ChatSession(tenant_id=tenant_id, title="F30 bubble test")
    pg_session.add(session_row)
    pg_session.commit()
    pg_session.refresh(session_row)

    invoice = Invoice(
        tenant_id=tenant_id,
        invoice_number="INV-2026-014",
        file_path="test/f30-bubble.pdf",
        vendor_name="Shree Packaging Pvt Ltd",
        subtotal=123200.0,
        grand_total=123200.0,
        currency="INR",
        invoice_date=date(2026, 3, 1),
        due_date=date(2026, 4, 15),
        status="PROCESSING",
        items=[{"description": "Corrugated boxes", "quantity": 1000, "amount": 123200.0}],
    )
    pg_session.add(invoice)
    pg_session.commit()
    pg_session.refresh(invoice)

    att = ChatAttachment(
        tenant_id=tenant_id,
        session_id=session_row.id,
        filename="po.pdf",
        blob_path="",
        doc_type="PURCHASE_ORDER",
        extraction_status="EXTRACTED",
        doc_number="PO-2026-0043",
        party_name="Shree Packaging Pvt Ltd",
        doc_date=date(2026, 2, 20),
        currency="INR",
        grand_total=100000.0,
        match_tier=1,
        candidate_invoice_ids=[str(invoice.id)],
        confirmed_invoice_ids=[str(invoice.id)],
        extracted_json={
            "doc_type": "PURCHASE_ORDER",
            "doc_number": "PO-2026-0043",
            "party_name": "Shree Packaging Pvt Ltd",
            "currency": "INR",
            "subtotal": 100000.0,
            "grand_total": 100000.0,
            "payment_terms": "Net 30",
            "items": [{"description": "Corrugated boxes", "quantity": 1000, "amount": 100000.0}],
            "field_confidence": {"doc_number": 0.95, "grand_total": 0.4},
        },
    )
    pg_session.add(att)
    pg_session.commit()
    pg_session.refresh(att)

    yield {
        "tenant_id": tenant_id,
        "session": session_row,
        "attachment": att,
        "invoice": invoice,
    }

    for row in pg_session.exec(select(Insight).where(Insight.tenant_id == tenant_id)).all():
        pg_session.delete(row)
    for msg in pg_session.exec(
        select(ChatMessage).where(ChatMessage.session_id == session_row.id)
    ).all():
        pg_session.delete(msg)
    pg_session.commit()
    for row in pg_session.exec(
        select(ChatAttachment).where(ChatAttachment.tenant_id == tenant_id)
    ).all():
        pg_session.delete(row)
    pg_session.delete(invoice)
    pg_session.delete(session_row)
    pg_session.commit()


class _StubLLM:
    """Stands in for the `chat_summary` model. Never reaches the network."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)

        class _R:
            content = self.reply

        return _R()


# --- the gate (30.1) -------------------------------------------------------


@pytest.mark.parametrize(
    "doc_type,expected",
    [
        ("PURCHASE_ORDER", True),
        ("QUOTATION", True),
        ("CREDIT_NOTE", True),
        ("GRN", True),
        ("STATEMENT_OF_ACCOUNT", True),
        ("INVOICE", False),
        ("OTHER", False),
        ("", False),
        (None, False),
    ],
)
def test_is_insight_doc_type(doc_type, expected):
    assert ai.is_insight_doc_type(doc_type) is expected


def test_the_eight_r2_types_are_all_covered_by_a_card_list():
    """Every type that passes the gate must have cards, or the bubble is empty
    for a document we told the user we would analyse."""
    assert set(ai.CARDS_BY_DOC_TYPE) == set(ai.INSIGHT_DOC_TYPES)


# --- flag off (hard rule 5) ------------------------------------------------


def test_flag_off_posts_nothing_and_touches_nothing(pg_session, world):
    """The parity assertion: with the flag off, Feature 26's behaviour stands."""
    before_version = world["attachment"].insights_version

    assert ai.run_sync_insights(world["attachment"], pg_session) is None

    pg_session.refresh(world["attachment"])
    assert world["attachment"].insights is None
    assert world["attachment"].insights_version == before_version
    assert world["attachment"].retained is False
    assert (
        pg_session.exec(
            select(ChatMessage).where(ChatMessage.session_id == world["session"].id)
        ).all()
        == []
    )
    assert (
        pg_session.exec(
            select(Insight).where(Insight.tenant_id == world["tenant_id"])
        ).all()
        == []
    )


def test_an_invoice_attachment_gets_no_bubble_even_with_the_flag_on(
    pg_session, world, flag_on
):
    world["attachment"].doc_type = "INVOICE"
    pg_session.add(world["attachment"])
    pg_session.commit()

    assert ai.run_sync_insights(world["attachment"], pg_session) is None
    assert (
        pg_session.exec(
            select(ChatMessage).where(ChatMessage.session_id == world["session"].id)
        ).all()
        == []
    )


# --- the sync block (30.1) -------------------------------------------------


def test_po_with_a_billed_invoice_reports_the_exact_overbill(pg_session, world, flag_on):
    block = ai.build_insight_block(
        world["attachment"], pg_session, world["tenant_id"], stage="sync"
    )

    cards = {c["card"]: c for c in block["cards"]}
    assert cards["agreed_vs_billed"]["status"] == "ok"
    # 123200 - 100000, computed in `document_comparison`, not by a model.
    assert block["figures"]["overbilled_INV-2026-014"] == 23200.0
    assert block["figures"]["agreed_INV-2026-014"] == 100000.0
    assert block["figures"]["billed_INV-2026-014"] == 123200.0

    top = block["findings"][0]
    assert top["finding_key"] == "agreed_vs_billed:INV-2026-014"
    assert top["impact_amount"] == 23200.0
    assert top["currency"] == "INR"
    # Confirmed link -> high confidence, and the reason is in the user's words.
    assert top["confidence"] == "high"
    assert "confirmed" in top["confidence_reason"]


def test_the_terms_card_reads_the_payment_window(pg_session, world, flag_on):
    """Net 30 on the PO vs 45 days between the invoice's dates."""
    block = ai.build_insight_block(world["attachment"], pg_session, stage="sync")
    cards = {c["card"]: c for c in block["cards"]}
    assert cards["terms_check"]["status"] == "ok"
    assert block["figures"]["agreed_payment_days"] == 30.0
    assert block["figures"]["payment_days_INV-2026-014"] == 45.0
    assert any(f["card"] == "terms_check" for f in block["findings"])


def test_a_card_with_no_linked_invoice_is_skipped_with_a_readable_reason(
    pg_session, world, flag_on
):
    world["attachment"].confirmed_invoice_ids = []
    world["attachment"].candidate_invoice_ids = []
    pg_session.add(world["attachment"])
    pg_session.commit()

    block = ai.build_insight_block(world["attachment"], pg_session, stage="sync")
    cards = {c["card"]: c for c in block["cards"]}
    assert cards["agreed_vs_billed"]["status"] == "skipped"
    assert "no invoice" in cards["agreed_vs_billed"]["reason"]
    # 30.12: the skip is reported to the user, not swallowed.
    assert any(c["card"] == "agreed_vs_billed" for c in block["checks_not_run"])


def test_a_card_that_raises_is_blocked_and_the_others_still_run(
    pg_session, world, flag_on, monkeypatch
):
    def _boom(row, db_session, ctx):
        raise RuntimeError("simulated card failure")

    _boom.__name__ = "card_agreed_vs_billed"
    monkeypatch.setitem(
        ai.CARDS_BY_DOC_TYPE,
        "PURCHASE_ORDER",
        (ai.card_what_this_is, _boom, ai.card_confidence_gaps),
    )

    block = ai.build_insight_block(world["attachment"], pg_session, stage="sync")
    cards = {c["card"]: c for c in block["cards"]}
    assert cards["agreed_vs_billed"]["status"] == "blocked"
    assert cards["what_this_is"]["status"] == "ok"
    assert cards["confidence_gaps"]["status"] == "ok"


def test_confidence_gaps_lists_low_confidence_fields_and_the_thresholds(
    pg_session, world, flag_on
):
    """30.12: 'checks not run + why', and the numbers the gates used."""
    block = ai.build_insight_block(world["attachment"], pg_session, stage="sync")
    gaps = next(c for c in block["cards"] if c["card"] == "confidence_gaps")
    assert gaps["evidence"]["low_confidence_fields"] == ["grand_total"]
    assert gaps["evidence"]["thresholds"]["bank_amount_tolerance"] == 1.0


def test_a_block_never_leaks_across_tenants(pg_session, world, flag_on):
    block = ai.build_insight_block(world["attachment"], pg_session, uuid4(), stage="sync")
    assert block["cards"] == []
    assert block["checks_not_run"][0]["reason"] == "tenant mismatch"


# --- verdict and ranking ---------------------------------------------------


def test_the_template_verdict_repeats_the_top_finding(pg_session, world, flag_on):
    block = ai.build_insight_block(world["attachment"], pg_session, stage="sync")
    assert block["verdict_source"] == "template"
    assert block["verdict"].startswith(block["findings"][0]["title"])


def test_findings_rank_money_first(pg_session, world, flag_on):
    block = {
        "findings": [
            {"title": "a", "impact_amount": None, "confidence": "high"},
            {"title": "b", "impact_amount": 100.0, "confidence": "low"},
            {"title": "c", "impact_amount": 5000.0, "confidence": "med"},
        ]
    }
    assert [f["title"] for f in ai.rank_findings(block)] == ["c", "b", "a"]


# --- narration and the answer-contract gate (30.2) -------------------------


def test_a_narration_that_only_repeats_given_figures_is_accepted(
    pg_session, world, flag_on
):
    block = ai.build_insight_block(world["attachment"], pg_session, stage="sync")
    llm = _StubLLM("Hold this bill - Shree Packaging billed 23200.0 more than the PO.")

    out = ai.narrate_insight_block(block, llm=llm)
    assert out["source"] == "model"
    assert out["gate"]["status"] == "ok"
    assert len(llm.calls) == 1


def test_a_narration_with_an_invented_figure_is_rejected_and_the_template_stands(
    pg_session, world, flag_on
):
    """The rule the whole feature rests on: the model may not compute."""
    block = ai.build_insight_block(world["attachment"], pg_session, stage="sync")
    template = block["verdict"]
    llm = _StubLLM("Shree Packaging has overbilled you 41999.99 across this order.")

    out = ai.narrate_insight_block(block, llm=llm)
    assert out["source"] == "template"
    assert out["gate"]["status"] == "unsupported"
    assert "41999.99" in out["gate"]["unsupported"]
    assert out["verdict"] == template


def test_a_failed_narration_call_leaves_the_template(pg_session, world, flag_on):
    class _Boom:
        def invoke(self, _messages):
            raise RuntimeError("model unavailable")

    block = ai.build_insight_block(world["attachment"], pg_session, stage="sync")
    out = ai.narrate_insight_block(block, llm=_Boom())
    assert out["source"] == "template"
    assert out["verdict"] == block["verdict"]


# --- posting, and the two-stage update (30.2) ------------------------------


def test_the_sync_stage_posts_one_turn_and_opens_the_findings(
    pg_session, world, flag_on
):
    block = ai.run_sync_insights(world["attachment"], pg_session)
    assert block is not None

    messages = pg_session.exec(
        select(ChatMessage).where(ChatMessage.session_id == world["session"].id)
    ).all()
    assert len(messages) == 1
    assert messages[0].role == "assistant"
    assert messages[0].attachment_payload["insights"]["figures"][
        "overbilled_INV-2026-014"
    ] == 23200.0

    pg_session.refresh(world["attachment"])
    assert world["attachment"].insights_version == 1
    assert world["attachment"].insights is not None
    # An open finding retains the attachment past the TTL (30.0a).
    assert world["attachment"].retained is True

    findings = pg_session.exec(
        select(Insight).where(Insight.tenant_id == world["tenant_id"])
    ).all()
    assert {f.finding_key for f in findings} >= {"agreed_vs_billed:INV-2026-014"}


def test_the_async_stage_updates_the_same_message_and_bumps_the_version(
    pg_session, world, flag_on
):
    sync_block = ai.run_sync_insights(world["attachment"], pg_session)
    message_id = sync_block["message_id"]

    async_block = ai.build_insight_block(world["attachment"], pg_session, stage="async")
    narration = ai.narrate_insight_block(
        async_block, llm=_StubLLM("Shree Packaging billed 23200.0 over this purchase order.")
    )
    async_block["verdict"] = narration["verdict"]
    async_block["verdict_source"] = narration["source"]

    from uuid import UUID

    message = ai.post_insight_turn(
        world["attachment"], async_block, pg_session, message_id=UUID(message_id)
    )
    ai.open_insights_from_block(world["attachment"], async_block, pg_session)

    # ONE bubble that improved, not two that argue.
    messages = pg_session.exec(
        select(ChatMessage).where(ChatMessage.session_id == world["session"].id)
    ).all()
    assert len(messages) == 1
    assert str(message.id) == message_id
    assert message.attachment_payload["insights"]["stage"] == "async"
    assert message.attachment_payload["insights"]["verdict_source"] == "model"

    pg_session.refresh(world["attachment"])
    assert world["attachment"].insights_version == 2

    # And the findings were refreshed, not duplicated.
    findings = pg_session.exec(
        select(Insight).where(Insight.tenant_id == world["tenant_id"])
    ).all()
    assert len(findings) == len({f.finding_key for f in findings})


def test_a_dismissed_finding_is_not_reopened_by_the_async_stage(
    pg_session, world, flag_on
):
    from services.insights import transition_insight

    ai.run_sync_insights(world["attachment"], pg_session)
    # Tenant-scoped, not just keyed on `finding_key`: this file's fixtures use a
    # fresh tenant per test but a shared dev database, and a row left behind by a
    # crashed run would otherwise be the one this test dismisses.
    row = pg_session.exec(
        select(Insight).where(
            Insight.tenant_id == world["tenant_id"],
            Insight.finding_key == "agreed_vs_billed:INV-2026-014",
        )
    ).first()
    transition_insight(
        row.id,
        tenant_id=world["tenant_id"],
        status="DISMISSED",
        outcome="dismissed",
        db_session=pg_session,
    )

    async_block = ai.build_insight_block(world["attachment"], pg_session, stage="async")
    ai.open_insights_from_block(world["attachment"], async_block, pg_session)

    pg_session.refresh(row)
    assert row.status == "DISMISSED"
