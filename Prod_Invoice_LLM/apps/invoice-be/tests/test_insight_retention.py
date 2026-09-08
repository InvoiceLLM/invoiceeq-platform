"""Feature 30 task 30.0a — the chat-document TTL sweep skips retained rows.

Verification plan 30.0a: "TTL job fixture: attachment with an OPEN insight
survives; after DISMISSED it is removed on the next run."

Real Postgres (hard rule 2): the thing under test is a SQL predicate on a
column that was added by migration `a1b2c3f30001`, and the fixture's expiry
comparison is a real timestamp comparison.

`expired_attachments()` is exercised directly rather than through `main()`.
`purge_attachment()` deletes a blob and a Chroma collection, neither of which
exists for a fixture row, and the selection predicate is the whole of what 30.0a
changed.
"""
import os
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from models import ChatAttachment, ChatSession, Insight  # noqa: E402
from scripts.sweep_chat_attachments import expired_attachments  # noqa: E402
from services import insights as svc  # noqa: E402


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


@pytest.fixture(name="expired")
def expired_fixture(pg_session):
    """One EXPIRED attachment, so it is a sweep candidate from the first line."""
    tenant_id = uuid4()
    session_row = ChatSession(tenant_id=tenant_id, title="F30 TTL test")
    pg_session.add(session_row)
    pg_session.commit()
    pg_session.refresh(session_row)

    att = ChatAttachment(
        tenant_id=tenant_id,
        session_id=session_row.id,
        filename="po.pdf",
        blob_path="",  # nothing to delete; the predicate is what is under test
        doc_type="PURCHASE_ORDER",
        extraction_status="EXTRACTED",
        expires_at=datetime.utcnow() - timedelta(days=1),
    )
    pg_session.add(att)
    pg_session.commit()
    pg_session.refresh(att)

    yield {"tenant_id": tenant_id, "session": session_row, "attachment": att}

    for row in pg_session.exec(select(Insight).where(Insight.tenant_id == tenant_id)).all():
        pg_session.delete(row)
    pg_session.commit()
    still_there = pg_session.get(ChatAttachment, att.id)
    if still_there is not None:
        pg_session.delete(still_there)
    pg_session.delete(session_row)
    pg_session.commit()


def _ids(rows):
    return {r.id for r in rows}


def test_an_expired_attachment_with_no_findings_is_a_candidate(pg_session, expired):
    """The control: without 30.0a this row sweeps, and it still must."""
    assert expired["attachment"].id in _ids(expired_attachments(pg_session))


def test_an_open_finding_holds_the_attachment_back(pg_session, expired):
    svc.open_insight(
        tenant_id=expired["tenant_id"],
        attachment_id=expired["attachment"].id,
        session_id=expired["session"].id,
        card="agreed_vs_billed",
        finding_key="ttl:open",
        title="Invoice billed over the PO",
        impact_amount=23200.0,
        db_session=pg_session,
    )
    pg_session.refresh(expired["attachment"])
    assert expired["attachment"].retained is True
    assert expired["attachment"].id not in _ids(expired_attachments(pg_session))


def test_it_sweeps_again_once_the_finding_is_dismissed(pg_session, expired):
    row = svc.open_insight(
        tenant_id=expired["tenant_id"],
        attachment_id=expired["attachment"].id,
        card="agreed_vs_billed",
        finding_key="ttl:dismiss",
        title="Invoice billed over the PO",
        db_session=pg_session,
    )
    assert expired["attachment"].id not in _ids(expired_attachments(pg_session))

    svc.transition_insight(
        row.id,
        tenant_id=expired["tenant_id"],
        status="DISMISSED",
        outcome="dismissed",
        db_session=pg_session,
    )
    pg_session.refresh(expired["attachment"])
    assert expired["attachment"].retained is False
    assert expired["attachment"].id in _ids(expired_attachments(pg_session))


def test_a_snoozed_finding_still_retains_until_it_wakes_and_is_closed(pg_session, expired):
    """A snooze is deferral, not closure: the evidence must survive the wait."""
    row = svc.open_insight(
        tenant_id=expired["tenant_id"],
        attachment_id=expired["attachment"].id,
        card="agreed_vs_billed",
        finding_key="ttl:snooze",
        title="Invoice billed over the PO",
        db_session=pg_session,
    )
    svc.transition_insight(
        row.id,
        tenant_id=expired["tenant_id"],
        status="SNOOZED",
        snoozed_until=datetime.utcnow() + timedelta(days=7),
        db_session=pg_session,
    )
    pg_session.refresh(expired["attachment"])
    # A snooze defers the finding; it does not resolve it. If the attachment
    # were swept while the finding slept, it would wake with its evidence
    # deleted -- a claim about money with nothing behind it. So SNOOZED retains
    # too, which is wider than §8.4 30.0a's literal "while any insight is OPEN"
    # and is recorded here as a test so the reading is visible.
    assert expired["attachment"].retained is True
    assert expired["attachment"].id not in _ids(expired_attachments(pg_session))

    # ... and once it is genuinely closed, the row sweeps.
    svc.transition_insight(
        row.id,
        tenant_id=expired["tenant_id"],
        status="DISMISSED",
        db_session=pg_session,
    )
    pg_session.refresh(expired["attachment"])
    assert expired["attachment"].retained is False
    assert expired["attachment"].id in _ids(expired_attachments(pg_session))
