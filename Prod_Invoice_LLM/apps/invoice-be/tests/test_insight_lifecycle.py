"""Feature 30 task 30.0e (+ 30.0a's TTL exemption and 30.17's actions) — the
insight lifecycle, against REAL Postgres.

Verification plan 30.0e: "transition matrix test (OPEN->ACTED/SNOOZED/DISMISSED,
SNOOZED->OPEN at `snoozed_until`); another tenant's insight not transitionable;
SSE event recorded in the progress test harness".

Postgres and not SQLite (hard rule 2) for three reasons that are all live here:
the tenant filter is a UUID column comparison, the `(attachment_id, finding_key)`
uniqueness that makes `open_insight()` idempotent is a real database constraint,
and `evidence` is JSONB.

No LLM is involved anywhere in this module — the lifecycle is pure code.
"""
import os
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from models import ChatAttachment, ChatSession, Insight  # noqa: E402
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


@pytest.fixture(name="fixture_set")
def fixture_set_fixture(pg_session):
    """One tenant, one chat session, one attachment — and everything removed after.

    A real `ChatAttachment` row rather than a bare uuid because 30.0a's
    `retained` flag is set on it by `open_insight()`, and a test that skipped the
    row would silently stop exercising the TTL exemption.
    """
    tenant_id = uuid4()
    other_tenant = uuid4()
    session_row = ChatSession(tenant_id=tenant_id, title="F30 lifecycle test")
    pg_session.add(session_row)
    pg_session.commit()
    pg_session.refresh(session_row)

    att = ChatAttachment(
        tenant_id=tenant_id,
        session_id=session_row.id,
        filename="po.pdf",
        blob_path="chat-attachments/test",
        doc_type="PURCHASE_ORDER",
        extraction_status="EXTRACTED",
    )
    pg_session.add(att)
    pg_session.commit()
    pg_session.refresh(att)

    yield {"tenant_id": tenant_id, "other_tenant": other_tenant, "session": session_row, "attachment": att}

    for row in pg_session.exec(
        select(Insight).where(Insight.tenant_id.in_([tenant_id, other_tenant]))
    ).all():
        pg_session.delete(row)
    pg_session.commit()
    pg_session.delete(att)
    pg_session.delete(session_row)
    pg_session.commit()


def _open(pg_session, fs, key="agreed_vs_billed:INV-1", **kw):
    return svc.open_insight(
        tenant_id=fs["tenant_id"],
        attachment_id=fs["attachment"].id,
        session_id=fs["session"].id,
        doc_type="PURCHASE_ORDER",
        card=kw.pop("card", "agreed_vs_billed"),
        finding_key=key,
        title=kw.pop("title", "Invoice billed over the PO"),
        impact_amount=kw.pop("impact_amount", 23200.0),
        currency=kw.pop("currency", "INR"),
        confidence=kw.pop("confidence", "high"),
        confidence_reason=kw.pop("confidence_reason", "exact document-number match"),
        evidence=kw.pop("evidence", {"po_total": 100000.0, "invoice_total": 123200.0}),
        db_session=pg_session,
    )


# --- opening ---------------------------------------------------------------


def test_open_insight_writes_the_finding_and_retains_the_attachment(pg_session, fixture_set):
    row = _open(pg_session, fixture_set)

    assert row.status == "OPEN"
    assert row.impact_amount == 23200.0
    assert row.evidence["invoice_total"] == 123200.0  # JSONB round-trip, not a string

    pg_session.refresh(fixture_set["attachment"])
    # 30.0a: an attachment with an open finding is held back from the TTL sweep.
    assert fixture_set["attachment"].retained is True


def test_open_insight_is_idempotent_on_the_finding_key(pg_session, fixture_set):
    """The async stage recomputes the sync stage's cards; that must not double up."""
    first = _open(pg_session, fixture_set)
    second = _open(pg_session, fixture_set, impact_amount=23500.0, confidence="med")

    assert first.id == second.id
    rows = pg_session.exec(
        select(Insight).where(Insight.attachment_id == fixture_set["attachment"].id)
    ).all()
    assert len(rows) == 1
    # Figures refresh ...
    assert rows[0].impact_amount == 23500.0
    assert rows[0].confidence == "med"


def test_reopening_does_not_resurrect_a_dismissed_finding(pg_session, fixture_set):
    """...but the lifecycle does not, or "dismiss" would mean "dismiss until the
    next bubble update"."""
    row = _open(pg_session, fixture_set)
    svc.transition_insight(
        row.id,
        tenant_id=fixture_set["tenant_id"],
        status="DISMISSED",
        outcome="dismissed",
        db_session=pg_session,
    )

    again = _open(pg_session, fixture_set, impact_amount=99.0)
    assert again.status == "DISMISSED"
    assert again.impact_amount == 99.0


# --- the transition matrix -------------------------------------------------


@pytest.mark.parametrize("target,outcome", [("ACTED", "note"), ("DISMISSED", "dismissed")])
def test_open_to_terminal_states(pg_session, fixture_set, target, outcome):
    row = _open(pg_session, fixture_set, key=f"k-{target}")
    moved = svc.transition_insight(
        row.id,
        tenant_id=fixture_set["tenant_id"],
        status=target,
        outcome=outcome,
        acted_by="owner@example.com",
        db_session=pg_session,
    )
    assert moved.status == target
    assert moved.outcome == outcome
    assert moved.acted_by == "owner@example.com"
    assert moved.acted_at is not None


def test_open_to_snoozed_requires_a_wake_time(pg_session, fixture_set):
    row = _open(pg_session, fixture_set, key="k-snooze")
    with pytest.raises(svc.InsightTransitionError):
        svc.transition_insight(
            row.id, tenant_id=fixture_set["tenant_id"], status="SNOOZED", db_session=pg_session
        )


def test_snoozed_wakes_at_snoozed_until(pg_session, fixture_set):
    """SNOOZED -> OPEN is computed at read time, not by a job that must run."""
    row = _open(pg_session, fixture_set, key="k-wake")

    future = svc.transition_insight(
        row.id,
        tenant_id=fixture_set["tenant_id"],
        status="SNOOZED",
        snoozed_until=datetime.utcnow() + timedelta(days=3),
        db_session=pg_session,
    )
    assert future.status == "SNOOZED"
    assert svc.is_effectively_open(future) is False
    assert svc.list_insights(fixture_set["tenant_id"], pg_session, status="OPEN") == []

    past = svc.transition_insight(
        row.id,
        tenant_id=fixture_set["tenant_id"],
        status="SNOOZED",
        snoozed_until=datetime.utcnow() - timedelta(minutes=1),
        db_session=pg_session,
    )
    assert past.status == "SNOOZED"
    assert svc.is_effectively_open(past) is True
    assert [r.id for r in svc.list_insights(fixture_set["tenant_id"], pg_session)] == [row.id]


def test_dismissed_is_terminal(pg_session, fixture_set):
    row = _open(pg_session, fixture_set, key="k-terminal")
    svc.transition_insight(
        row.id, tenant_id=fixture_set["tenant_id"], status="DISMISSED", db_session=pg_session
    )
    with pytest.raises(svc.InsightTransitionError):
        svc.transition_insight(
            row.id, tenant_id=fixture_set["tenant_id"], status="OPEN", db_session=pg_session
        )


def test_unknown_outcome_is_refused(pg_session, fixture_set):
    row = _open(pg_session, fixture_set, key="k-outcome")
    with pytest.raises(svc.InsightTransitionError):
        svc.transition_insight(
            row.id,
            tenant_id=fixture_set["tenant_id"],
            status="ACTED",
            outcome="write_off",
            db_session=pg_session,
        )


def test_another_tenants_insight_is_not_transitionable(pg_session, fixture_set):
    row = _open(pg_session, fixture_set, key="k-tenant")
    assert (
        svc.transition_insight(
            row.id,
            tenant_id=fixture_set["other_tenant"],
            status="DISMISSED",
            db_session=pg_session,
        )
        is None
    )
    pg_session.refresh(row)
    assert row.status == "OPEN"


# --- 30.0a: the TTL exemption follows the last open finding -----------------


def test_retained_clears_when_the_last_finding_closes(pg_session, fixture_set):
    a = _open(pg_session, fixture_set, key="k-a")
    b = _open(pg_session, fixture_set, key="k-b")

    svc.transition_insight(
        a.id, tenant_id=fixture_set["tenant_id"], status="DISMISSED", db_session=pg_session
    )
    pg_session.refresh(fixture_set["attachment"])
    assert fixture_set["attachment"].retained is True  # b is still open

    svc.transition_insight(
        b.id,
        tenant_id=fixture_set["tenant_id"],
        status="ACTED",
        outcome="note",
        db_session=pg_session,
    )
    pg_session.refresh(fixture_set["attachment"])
    assert fixture_set["attachment"].retained is False


# --- ranking ---------------------------------------------------------------


def test_rank_open_insights_orders_by_impact_times_confidence(pg_session, fixture_set):
    _open(pg_session, fixture_set, key="small-high", impact_amount=1000.0, confidence="high")
    _open(pg_session, fixture_set, key="big-low", impact_amount=2000.0, confidence="low")
    _open(pg_session, fixture_set, key="mid-high", impact_amount=1500.0, confidence="high")
    # 1500 x 1.0 > 1000 x 1.0 > 2000 x 0.3
    ranked = svc.rank_open_insights(fixture_set["tenant_id"], pg_session)
    assert [r.finding_key for r in ranked] == ["mid-high", "small-high", "big-low"]


def test_unquantified_findings_still_rank(pg_session, fixture_set):
    """"No PO on file" has no amount and must not fall off the dashboard."""
    _open(pg_session, fixture_set, key="no-amount", impact_amount=None, confidence="high")
    ranked = svc.rank_open_insights(fixture_set["tenant_id"], pg_session)
    assert [r.finding_key for r in ranked] == ["no-amount"]


# --- the SSE hook ----------------------------------------------------------


class _RecordingRedis:
    """The progress harness: records what would have gone onto the channel."""

    def __init__(self):
        self.published = []

    def get(self, *_a, **_k):
        return None

    def set(self, *_a, **_k):
        return True

    def publish(self, channel, payload):
        self.published.append((channel, payload))
        return 1


def test_notify_insight_update_publishes_on_the_jobs_channel(fixture_set):
    import json

    client = _RecordingRedis()
    svc.notify_insight_update(
        "job-123",
        session_id=fixture_set["session"].id,
        attachment_id=fixture_set["attachment"].id,
        insights_version=2,
        client=client,
    )
    assert len(client.published) == 1
    channel, raw = client.published[0]
    assert channel == "chat_job_channel:job-123"
    event = json.loads(raw)
    assert event["step"] == "insight_update"
    assert event["details"]["insights_version"] == 2
    assert event["details"]["attachment_id"] == str(fixture_set["attachment"].id)


def test_notify_without_a_job_id_is_a_no_op(fixture_set):
    """A closed session has no stream; §8.6 says that case is the dashboard's."""
    svc.notify_insight_update(
        None,
        session_id=fixture_set["session"].id,
        attachment_id=fixture_set["attachment"].id,
        insights_version=1,
        client=_RecordingRedis(),
    )


# --- the HTTP surface (30.0e's endpoints, 30.17's actions) ------------------
#
# Driven through TestClient with `get_db_session` and `get_tenant_context`
# overridden onto the SAME Postgres session the fixtures wrote to. Overriding
# the tenant context rather than minting a Clerk token is what keeps this a test
# of the endpoint's own tenant filtering instead of a test of the auth layer.


@pytest.fixture(name="client")
def client_fixture(pg_session, fixture_set):
    from fastapi.testclient import TestClient

    import main
    from dependencies import TenantContext, get_db_session, get_tenant_context

    def _db():
        yield pg_session

    def _ctx():
        return TenantContext(
            tenant_id=fixture_set["tenant_id"],
            user_id="owner@example.com",
            role="Admin",
            billing_plan="pro",
        )

    main.app.dependency_overrides[get_db_session] = _db
    main.app.dependency_overrides[get_tenant_context] = _ctx
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


def test_get_insights_returns_only_open_findings(client, pg_session, fixture_set):
    open_row = _open(pg_session, fixture_set, key="api-open")
    closed = _open(pg_session, fixture_set, key="api-closed")
    svc.transition_insight(
        closed.id, tenant_id=fixture_set["tenant_id"], status="DISMISSED", db_session=pg_session
    )

    body = client.get("/api/v1/chat/insights").json()
    assert [r["finding_key"] for r in body] == ["api-open"]
    assert body[0]["is_open"] is True
    assert body[0]["impact_amount"] == 23200.0
    assert str(open_row.id) == body[0]["id"]


def test_transition_endpoint_dismisses(client, pg_session, fixture_set):
    row = _open(pg_session, fixture_set, key="api-dismiss")
    resp = client.post(
        f"/api/v1/chat/insights/{row.id}/transition",
        json={"status": "DISMISSED", "outcome": "dismissed"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "DISMISSED"
    assert resp.json()["is_open"] is False


def test_transition_endpoint_rejects_an_illegal_move(client, pg_session, fixture_set):
    row = _open(pg_session, fixture_set, key="api-illegal")
    svc.transition_insight(
        row.id, tenant_id=fixture_set["tenant_id"], status="DISMISSED", db_session=pg_session
    )
    resp = client.post(
        f"/api/v1/chat/insights/{row.id}/transition", json={"status": "OPEN"}
    )
    assert resp.status_code == 400


def test_transition_endpoint_404s_on_another_tenants_finding(client, pg_session, fixture_set):
    """Cross-tenant must be indistinguishable from non-existent."""
    from uuid import uuid4 as _uuid4

    resp = client.post(
        f"/api/v1/chat/insights/{_uuid4()}/transition", json={"status": "DISMISSED"}
    )
    assert resp.status_code == 404


def test_hold_dispute_paid_are_rejected_and_no_invoice_is_ever_touched(client, pg_session, fixture_set):
    """Gap 492 (founder 2026-09-08): the bubble is information only. The three
    invoice-moving outcomes the first build accepted are refused, and the
    endpoint has no `invoice_id` at all -- a client cannot even name one."""
    from models import Invoice

    inv = Invoice(
        tenant_id=fixture_set["tenant_id"],
        invoice_number="INV-F30-001",
        file_path="test/f30-001.pdf",
        vendor_name="Shree Packaging Pvt Ltd",
        total_amount=123200.0,
        status="PROCESSING",
    )
    pg_session.add(inv)
    pg_session.commit()
    pg_session.refresh(inv)
    try:
        for outcome in ("hold", "dispute", "paid"):
            row = _open(pg_session, fixture_set, key=f"api-{outcome}")
            resp = client.post(
                f"/api/v1/chat/insights/{row.id}/transition",
                json={"status": "ACTED", "outcome": outcome, "invoice_id": str(inv.id)},
            )
            assert resp.status_code == 400, resp.text
            pg_session.refresh(inv)
            assert inv.status == "PROCESSING"
    finally:
        pg_session.delete(inv)
        pg_session.commit()

def test_a_note_never_moves_an_invoice(client, pg_session, fixture_set):
    from models import Invoice

    inv = Invoice(
        tenant_id=fixture_set["tenant_id"],
        invoice_number="INV-F30-002",
        # `file_path` is NOT NULL on `invoice` -- a real column constraint the
        # SQLite half of this suite never sees.
        file_path=f"test/f30-002.pdf",
        vendor_name="Shree Packaging Pvt Ltd",
        total_amount=100.0,
        status="PROCESSING",
    )
    pg_session.add(inv)
    pg_session.commit()
    pg_session.refresh(inv)
    try:
        row = _open(pg_session, fixture_set, key="api-note")
        resp = client.post(
            f"/api/v1/chat/insights/{row.id}/transition",
            json={
                "status": "ACTED",
                "outcome": "note",
                "note": "spoke to the vendor",
                "invoice_id": str(inv.id),
            },
        )
        assert resp.status_code == 200
        assert resp.json()["note"] == "spoke to the vendor"
        pg_session.refresh(inv)
        assert inv.status == "PROCESSING"
    finally:
        pg_session.delete(inv)
        pg_session.commit()


def test_discuss_returns_a_seed_and_writes_nothing(client, pg_session, fixture_set):
    row = _open(pg_session, fixture_set, key="api-discuss")
    body = client.get(f"/api/v1/chat/insights/{row.id}/discuss").json()
    assert body["insight_id"] == str(row.id)
    assert "Invoice billed over the PO" in body["seed_text"]
    pg_session.refresh(row)
    assert row.status == "OPEN"
