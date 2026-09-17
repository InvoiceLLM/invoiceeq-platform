"""Gap 483 (Feature 29 phase-2) -- the golden harness can seed a case's attachments.

Before this, 12 of the 16 attachment golden cases and all 5 long-document cases were
authored but unrunnable: `scripts/attach_chat_eval.py` gets its documents by uploading
PDFs over HTTP and waiting for the queue worker, while `run_agent_eval.py` runs in-process
with neither a backend nor a worker. CP1's "57 golden turns" was 36 plus a separate probe.

`seed_case_attachments()` closes it by going through **the product's own pipeline** --
`upload_pdf_to_blob_storage()` then `services.attachment_extraction.extract_attachment()`,
the same function the queue worker calls. That choice is the point of the design and is
what these tests protect: a hand-made `extracted_json` would have been far faster and would
have graded the chat prompt against evidence no user could ever produce, which is precisely
the failure Gap 478 turned out to be.

Extraction is mocked here (`LLM_PROVIDER=mock`, no live OCR or LLM) because this file tests
the SEAM, not the extractor. The rows land in real Postgres.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.run_agent_eval import build_attachment_fixtures, seed_case_attachments


@dataclass(frozen=True)
class _Case:
    case_id: str
    attachment_keys: tuple
    attachment_intent: str | None = None


def _pg_session():
    import os

    from sqlmodel import Session, create_engine

    url = os.environ.get("DATABASE_URL") or ""
    if not url:
        from config import get_settings

        url = get_settings().DATABASE_URL or ""
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        engine = create_engine(url)
        with engine.connect():
            pass
    except Exception as exc:  # pragma: no cover - environment
        pytest.skip(f"local Postgres not reachable: {exc}")
    return Session(engine)


# --- the fixture builders ---------------------------------------------------

def test_both_fixture_sets_are_built_and_their_keys_do_not_collide(tmp_path):
    paths = build_attachment_fixtures(str(tmp_path))
    # the probe's eight plus the five long documents
    assert len(paths) >= 13, sorted(paths)
    for key in ("po_apex", "cn_apex", "ct_redwood", "lc_contract", "lc_statement"):
        assert key in paths, f"{key} was not built"
    for path in paths.values():
        assert Path(path).exists() and Path(path).stat().st_size > 0


def test_a_key_claimed_by_two_builders_is_an_error_not_a_silent_overwrite(tmp_path):
    """Two fixture sets quietly sharing a key would swap one document for another
    and grade the answer against the wrong ground truth."""
    with patch(
        "scripts.run_agent_eval._FIXTURE_BUILDERS",
        ("scripts.attach_chat_eval:build_documents",
         "scripts.attach_chat_eval:build_documents"),
    ):
        with pytest.raises(AssertionError, match="same key"):
            build_attachment_fixtures(str(tmp_path))


# --- seeding ----------------------------------------------------------------

def _fake_extract(row, db_session):
    """Stand in for the real extractor: mark the row read, as the pipeline would."""
    row.extraction_status = "EXTRACTED"
    row.doc_type = "PURCHASE_ORDER"
    db_session.add(row)
    db_session.commit()
    return row


def test_a_case_with_no_attachments_touches_nothing(tmp_path):
    """A plain SQL case must not pay for a blob upload or an extraction."""
    with patch("services.storage.upload_pdf_to_blob_storage") as up:
        session_id, ids = seed_case_attachments(
            _Case("plain", ()), None, str(uuid.uuid4()), {}
        )
    assert ids == []
    # no documents means no chat session either -- nothing was created to hold them
    assert session_id is None
    up.assert_not_called()


def test_seeding_goes_through_the_real_extraction_pipeline_on_postgres(tmp_path):
    paths = build_attachment_fixtures(str(tmp_path))
    tenant = str(uuid.uuid4())
    case = _Case("attach_a4", ("po_apex", "cn_apex"), "read")

    from sqlmodel import select

    from models import ChatAttachment, ChatSession

    with _pg_session() as session:
        with patch(
            "services.storage.upload_pdf_to_blob_storage",
            side_effect=lambda data, t, p: f"{t}/{p}.pdf",
        ) as up, patch(
            "services.attachment_extraction.extract_attachment",
            side_effect=_fake_extract,
        ) as ex:
            chat_session_id, ids = seed_case_attachments(case, session, tenant, paths)

        try:
            # one attachment per key, in the case's own order -- the pair branch
            # depends on there being exactly two
            assert len(ids) == 2
            # and the turn must be asked ON that session, or the agent answers
            # "I can't find that attachment on this conversation"
            assert chat_session_id is not None
            assert up.call_count == 2 and ex.call_count == 2
            # the real pipeline function was called, not a shortcut
            assert ex.call_args[0][0].tenant_id == uuid.UUID(tenant)

            rows = session.exec(
                select(ChatAttachment).where(ChatAttachment.tenant_id == uuid.UUID(tenant))
            ).all()
            assert len(rows) == 2
            assert {r.filename for r in rows} == {"po_apex.pdf", "cn_apex.pdf"}
            assert all(r.extraction_status == "EXTRACTED" for r in rows)
            assert all(r.file_size_bytes > 0 for r in rows)
            # both hang off ONE session, as a real user's two attachments would
            assert len({r.session_id for r in rows}) == 1
        finally:
            for row in session.exec(
                select(ChatAttachment).where(ChatAttachment.tenant_id == uuid.UUID(tenant))
            ).all():
                session.delete(row)
            for chat in session.exec(
                select(ChatSession).where(ChatSession.tenant_id == str(tenant))
            ).all():
                session.delete(chat)
            session.commit()


def test_a_missing_fixture_is_a_loud_failure_not_a_turn_asked_with_no_document(tmp_path):
    """Silently asking an attachment question with no attachment would score the
    turn as a model failure when it is a harness failure."""
    with _pg_session() as session:
        with pytest.raises(AssertionError, match="no fixture built"):
            seed_case_attachments(
                _Case("bad", ("does_not_exist",)), session, str(uuid.uuid4()), {}
            )
        session.rollback()


# --- the turn is told which documents it got --------------------------------

def test_the_turn_record_carries_the_attachment_ids_and_keys():
    src = (Path(__file__).resolve().parents[1] / "scripts" / "run_agent_eval.py").read_text(
        encoding="utf-8"
    )
    assert '"attachment_ids": list(attachment_ids or []),' in src
    assert '"attachment_keys": list(getattr(case, "attachment_keys", ()) or ()),' in src


def test_one_document_takes_the_single_branch_and_two_take_the_pair_branch():
    """A4, A6 and B5 exist to exercise the pair branch; collapsing the two would
    silently retire three of the five turns that failed on every model."""
    src = (Path(__file__).resolve().parents[1] / "scripts" / "run_agent_eval.py").read_text(
        encoding="utf-8"
    )
    assert "attachment_id=_att[0] if len(_att) == 1 else None," in src
    assert "attachment_ids=_att if len(_att) > 1 else None," in src
    assert 'attachment_intent=getattr(case, "attachment_intent", None),' in src


# --- BE Gap 565: the confirmation card is a step, not the answer -----------------
#
# Feature 26's D4 gate answers a `compare`/`reconcile` question with a card listing
# candidate invoices and calls no model until the user confirms one. The original
# probe (`scripts/attach_chat_eval.py`) confirms and re-asks; this harness never did,
# so nine of the sixteen attachment golden cases were graded on the card itself --
# a 5-15 ms zero-LLM turn -- and failed on every nightly run by construction.


def _attachment_row(tenant: uuid.UUID, chat_id, candidates, confirmed=()):
    from models import ChatAttachment

    return ChatAttachment(
        id=uuid.uuid4(),
        tenant_id=tenant,
        session_id=chat_id,
        filename="po.pdf",
        blob_path=f"{tenant}/po.pdf",
        file_size_bytes=1,
        extraction_status="EXTRACTED",
        candidate_invoice_ids=[str(c) for c in candidates],
        confirmed_invoice_ids=[str(c) for c in confirmed],
    )


def test_confirming_takes_exactly_the_proposed_candidates_on_postgres():
    """Mirrors `confirm_attachment_matches`: only what the matcher proposed can be
    confirmed, and all of it is -- the same click the probe makes on the card."""
    from sqlmodel import select

    from models import ChatAttachment, ChatSession
    from scripts.run_agent_eval import confirm_proposed_candidates

    tenant = uuid.uuid4()
    a, b = uuid.uuid4(), uuid.uuid4()
    with _pg_session() as session:
        chat = ChatSession(tenant_id=tenant, title="gap-565")
        session.add(chat)
        session.commit()
        session.refresh(chat)
        row = _attachment_row(tenant, chat.id, [a, b])
        session.add(row)
        session.commit()
        try:
            done = confirm_proposed_candidates([str(row.id)], session)
            assert done == [str(row.id)]
            session.refresh(row)
            assert row.confirmed_invoice_ids == [str(a), str(b)]
        finally:
            for r in session.exec(
                select(ChatAttachment).where(ChatAttachment.tenant_id == tenant)
            ).all():
                session.delete(r)
            for c in session.exec(select(ChatSession).where(ChatSession.tenant_id == tenant)).all():
                session.delete(c)
            session.commit()


def test_an_already_confirmed_or_candidate_less_row_is_left_alone_on_postgres():
    """Tier 0 ("nothing matches") is a real answer and must not be turned into a
    confirmation; an existing confirmation is the user's and is never overwritten."""
    from sqlmodel import select

    from models import ChatAttachment, ChatSession
    from scripts.run_agent_eval import confirm_proposed_candidates

    tenant = uuid.uuid4()
    chosen, other = uuid.uuid4(), uuid.uuid4()
    with _pg_session() as session:
        chat = ChatSession(tenant_id=tenant, title="gap-565")
        session.add(chat)
        session.commit()
        session.refresh(chat)
        empty = _attachment_row(tenant, chat.id, [])
        already = _attachment_row(tenant, chat.id, [chosen, other], confirmed=[chosen])
        session.add(empty)
        session.add(already)
        session.commit()
        try:
            assert confirm_proposed_candidates([str(empty.id), str(already.id), "not-a-uuid"], session) == []
            session.refresh(empty)
            session.refresh(already)
            assert empty.confirmed_invoice_ids == []
            assert already.confirmed_invoice_ids == [str(chosen)]
        finally:
            for r in session.exec(
                select(ChatAttachment).where(ChatAttachment.tenant_id == tenant)
            ).all():
                session.delete(r)
            for c in session.exec(select(ChatSession).where(ChatSession.tenant_id == tenant)).all():
                session.delete(c)
            session.commit()


@dataclass(frozen=True)
class _TurnCase:
    case_id: str
    question: str
    tenant_id: str
    attachment_keys: tuple
    attachment_intent: str | None
    expected_answer: str = ""
    expected_invoice_numbers: tuple | None = None


def _card(candidates):
    return {
        "content": "I found these invoices. Please confirm which to compare against.",
        "generated_sql": "",
        "citations": [],
        "result_invoice_ids": list(candidates),
        "attachment_confirmation": {"candidates": [{"invoice_id": c} for c in candidates]},
    }


def _run_turn_with_agent(answers, case, monkeypatch, confirmed_ids):
    """Drive `run_turn` with a scripted agent. `answers` is what each successive
    `run_query_agent` call returns; every call's kwargs are captured."""
    import scripts.run_agent_eval as harness
    from agents import query_agent

    calls = []

    def _fake_agent(session_id, question, tenant_id, session, **kwargs):
        calls.append(kwargs)
        return answers[len(calls) - 1]

    monkeypatch.setattr(query_agent, "run_query_agent", _fake_agent)
    monkeypatch.setattr(
        harness, "confirm_proposed_candidates", lambda ids, session: list(confirmed_ids)
    )
    turn = harness.run_turn(
        case, "default", session=None, stats="", chunks=[], attachment_ids=["att-1"]
    )
    return turn, calls


def test_a_compare_turn_that_gets_the_card_is_confirmed_and_re_asked(monkeypatch):
    case = _TurnCase("attach_a2", "Which invoice does this PO relate to?", str(uuid.uuid4()),
                     ("po_summit",), "compare")
    answered = {"content": "The PO relates to SOS-100442 and matches.", "citations": []}
    turn, calls = _run_turn_with_agent([_card(["inv-1"]), answered], case, monkeypatch, ["att-1"])

    assert len(calls) == 2, "the card must be answered and the question asked again"
    assert calls[0]["attachment_intent"] == "compare"
    assert calls[1]["attachment_intent"] == "compare"
    assert calls[1]["attachment_id"] == "att-1"
    assert turn["answer"] == answered["content"], "the graded answer is the second one"
    assert turn["confirm_step"] is True
    assert turn["error"] is None


def test_a_card_with_no_candidates_and_a_read_turn_are_never_re_asked(monkeypatch):
    # tier 0: the product's honest "nothing matches" is the answer
    case = _TurnCase("attach_b2", "Does this delivery note match?", str(uuid.uuid4()),
                     ("dn_cmc",), "compare")
    turn, calls = _run_turn_with_agent([_card([])], case, monkeypatch, [])
    assert len(calls) == 1
    assert turn["confirm_step"] is False
    assert "confirm which" in turn["answer"]

    # a read turn never reaches the gate, so even a card-shaped reply is not retried
    case = _TurnCase("attach_a1", "What is this document?", str(uuid.uuid4()),
                     ("po_summit",), "read")
    turn, calls = _run_turn_with_agent([_card(["inv-1"])], case, monkeypatch, ["att-1"])
    assert len(calls) == 1
    assert turn["confirm_step"] is False


def test_the_telemetry_row_carries_confirm_step_only_when_it_happened():
    src = (Path(__file__).resolve().parents[1] / "scripts" / "run_agent_eval.py").read_text(
        encoding="utf-8"
    )
    assert '("confirm_step", True if turn.get("confirm_step") else None),' in src
    assert '"confirm_step": confirm_step,' in src
