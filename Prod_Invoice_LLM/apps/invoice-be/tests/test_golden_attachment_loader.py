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
