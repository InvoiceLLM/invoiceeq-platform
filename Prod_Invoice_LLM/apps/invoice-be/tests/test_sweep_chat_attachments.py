"""Feature 26 E-7 / task H8 — the chat-attachment TTL sweeper.

The assertion that matters most here is a NEGATIVE one: a row with
`expires_at IS NULL` must never be selected. H4's build note flags this as the
one catastrophic misreading available — every Part 1 attachment predates the
column, so treating NULL as "expired at the epoch" deletes the entire back
catalogue on the first run.
"""
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from models import ChatAttachment
from scripts.sweep_chat_attachments import expired_attachments, purge_attachment

engine = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TENANT = uuid4()


@pytest.fixture(name="db")
def db_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


def _attachment(db, expires_at):
    row = ChatAttachment(
        id=uuid4(), tenant_id=TENANT, session_id=uuid4(), filename="po.pdf",
        blob_path=f"tenants/{TENANT}/chat-attachments/po.pdf", doc_type="PURCHASE_ORDER",
        file_size_bytes=1024, extraction_status="EXTRACTED", expires_at=expires_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_a_null_expires_at_is_never_swept():
    """KEEP, not "expired at the epoch". This is the assertion H4's build note
    asks for by name, and getting it backwards deletes every Part 1 attachment
    on the first run."""
    with Session(engine) as db:
        SQLModel.metadata.create_all(engine)
        _attachment(db, None)
        assert expired_attachments(db) == []
        SQLModel.metadata.drop_all(engine)


def test_a_future_expiry_is_not_swept(db):
    _attachment(db, datetime.utcnow() + timedelta(days=7))
    assert expired_attachments(db) == []


def test_a_past_expiry_is_swept(db):
    row = _attachment(db, datetime.utcnow() - timedelta(days=1))
    assert [r.id for r in expired_attachments(db)] == [row.id]


def test_expired_rows_come_back_oldest_first(db):
    """So a --limit'ed run makes progress on the genuine backlog rather than
    repeatedly taking whatever the database returned first."""
    newer = _attachment(db, datetime.utcnow() - timedelta(days=1))
    older = _attachment(db, datetime.utcnow() - timedelta(days=30))
    assert [r.id for r in expired_attachments(db)] == [older.id, newer.id]


def test_limit_bounds_the_run(db):
    for days in (10, 20, 30):
        _attachment(db, datetime.utcnow() - timedelta(days=days))
    assert len(expired_attachments(db, limit=2)) == 2


def test_dry_run_changes_nothing(db):
    row = _attachment(db, datetime.utcnow() - timedelta(days=1))
    outcome = purge_attachment(db, row, dry_run=True)
    assert outcome["row_deleted"] is False
    assert db.get(ChatAttachment, row.id) is not None


def test_a_failing_chunk_delete_does_not_strand_the_row(db, monkeypatch):
    """Each step is best-effort and independent. An unreachable Chroma must not
    stop the row being removed -- a leftover chunk set is inspectable and
    sweepable, whereas an undeletable row grows forever, which is the unbounded
    growth E-7 exists to prevent."""
    import services.chat_document_search as cds
    import services.storage as storage

    monkeypatch.setattr(
        cds, "delete_attachment_chunks",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("chroma down")),
    )
    monkeypatch.setattr(storage, "delete_pdf_from_storage", lambda *a, **k: None)

    row = _attachment(db, datetime.utcnow() - timedelta(days=1))
    outcome = purge_attachment(db, row)
    db.commit()

    assert outcome["chunks_deleted"] is False
    assert outcome["row_deleted"] is True
    assert db.get(ChatAttachment, row.id) is None
