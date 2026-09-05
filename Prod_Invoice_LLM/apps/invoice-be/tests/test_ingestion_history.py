"""BE Gap 464 — the durable ingestion History screen's API.

What is asserted here, and why each one exists:

  H-1  a run that produced ONLY a `documents` row is a normal row in the log,
       with `status == "NOT_LOADED"` and a summary that says so. This is the
       founder's original symptom: a delivery note vanished from the Ingest
       table with no message, because Feature 27 decision E10 deletes the
       placeholder `invoice` row. A disappearance is now an explained line.
  H-2  the drill-down returns the FULL record for both kinds — an invoice's
       extracted fields/alerts/line items, and a document's `doc_attributes` —
       and the outcome label reads "Loaded — COMPLETED" / "Not loaded —
       Delivery note".
  H-3  **the presentation guarantee.** `/dashboard/metrics` is byte-identical
       before and after the whole History surface is exercised on a tenant whose
       batch contains a `Document`. This is the same shape as
       `test_documents_table.py`'s T-E10-2 (the Gap 329-shaped test) and is the
       thing Gap 464 must not break: this feature is presentation-only, and a
       `Document` row must never enter `invoice` or any aggregate.
  H-4  archive / unarchive / archive-all, including that an archived run leaves
       the live list, appears in the Archived view, and — critically — that the
       `Invoice` row it describes is completely untouched. "Archive" means the
       log line, never the invoice.
  H-5  tenant scoping: tenant B cannot list or drill into tenant A's run, and
       gets 404 (never 403) for it.
  H-6  a `dropped_inbound_emails` row is surfaced to the tenant it concerns as a
       REJECTED run — those rows were Admin-console-only before this.
  H-7  the outcome vocabulary is total: every status the pipeline can produce
       maps to exactly one of the four outcomes, and an unknown one falls
       through to LOADED rather than to a silent fifth state.

**Evidence standard.** Everything that persists runs against real PostgreSQL
(CONVENTIONS hard rule 2) via the same `pg_engine_or_skip()` harness
`tests/test_documents_table.py` uses, and every test tags its rows with a
per-run `uuid4()` and deletes what it created in a `finally`, because this runs
against the developer's real dev database rather than a throwaway one.
"""
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from config import get_settings
from dependencies import TenantContext, get_db_session, get_tenant_context
from main import app
from models import (
    Document,
    DroppedInboundEmail,
    IngestionBatch,
    Invoice,
    Tenant,
    TenantAutopilotLog,
)
from routers.ingestion_history import (
    DUPLICATE_INVOICE_STATUSES,
    IN_PROGRESS_INVOICE_STATUSES,
    OUTCOME_IN_PROGRESS,
    OUTCOME_LOADED,
    OUTCOME_NOT_LOADED,
    OUTCOME_REJECTED,
    REJECTED_INVOICE_STATUSES,
    _invoice_outcome,
)


# ---------------------------------------------------------------------------
# Postgres harness (hard rule 2) — same shape as tests/test_documents_table.py
# ---------------------------------------------------------------------------
def pg_engine_or_skip():
    psycopg2 = pytest.importorskip("psycopg2")
    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        psycopg2.connect(url, connect_timeout=5).close()
    except psycopg2.OperationalError as exc:
        pytest.skip(f"local Postgres not reachable: {exc}")
    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="pg")
def pg_fixture():
    engine = pg_engine_or_skip()
    with Session(engine) as session:
        yield session


def _tenant(session, tag, name="A"):
    row = Tenant(
        id=uuid4(),
        name=f"G464-{name}-{tag}",
        domain=f"g464-{name.lower()}-{tag}.invalid",
        billing_plan="free",
        free_invoices_remaining=50,
    )
    session.add(row)
    session.commit()
    return row


def _cleanup(session, tenant_ids):
    session.rollback()
    for tid in tenant_ids:
        for model in (
            DroppedInboundEmail,
            TenantAutopilotLog,
            IngestionBatch,
            Document,
            Invoice,
        ):
            for row in session.exec(select(model).where(model.tenant_id == tid)).all():
                session.delete(row)
        tenant = session.get(Tenant, tid)
        if tenant:
            session.delete(tenant)
    session.commit()


def _client(session, tenant):
    """TestClient with the session and tenant context pinned to this test's rows."""
    def _db():
        yield session

    def _ctx():
        return TenantContext(
            tenant_id=tenant.id, user_id="test-user", role="Admin", billing_plan="free"
        )

    app.dependency_overrides[get_db_session] = _db
    app.dependency_overrides[get_tenant_context] = _ctx
    return TestClient(app)


def _batch(session, tenant, trigger="manual", flow="INBOUND", file_count=1, minutes_ago=0):
    row = IngestionBatch(
        batch_id=uuid4(),
        tenant_id=tenant.id,
        flow_direction=flow,
        trigger=trigger,
        file_count=file_count,
        started_at=datetime.utcnow() - timedelta(minutes=minutes_ago),
    )
    session.add(row)
    session.commit()
    return row


def _invoice(session, tenant, batch_id, status="COMPLETED", flow="INBOUND", tag="x"):
    row = Invoice(
        id=uuid4(),
        tenant_id=tenant.id,
        batch_id=batch_id,
        file_path=f"{tenant.id}/inv-{tag}.pdf",
        vendor_name="Bharat Steels Pvt Ltd",
        invoice_number=f"INV-{tag}",
        grand_total=99120.0,
        currency="INR",
        invoice_date=date(2026, 8, 1),
        created_at=datetime(2026, 8, 1),
        status=status,
        flow_direction=flow,
        items=[{"description": "MS Angle 50x50x6", "quantity": 120.0}],
        sa_alerts=[{"type": "info", "message": "seeded"}],
    )
    session.add(row)
    session.commit()
    return row


def _document(session, tenant, batch_id, doc_type="DELIVERY_NOTE", tag="x"):
    row = Document(
        id=uuid4(),
        tenant_id=tenant.id,
        batch_id=batch_id,
        file_path=f"{tenant.id}/doc-{tag}.pdf",
        doc_type=doc_type,
        doc_type_evidence="DELIVERY CHALLAN",
        doc_type_confidence=0.94,
        doc_attributes={"direction": {"value": "INBOUND", "evidence": "Ship to"}},
        party_name="Bharat Steels Pvt Ltd",
        counterparty_name="Novatech Industries",
        doc_number=f"DC-{tag}",
        status="EXTRACTED",
        items=[{"description": "MS Flat 40x6", "quantity": 40.0}],
        created_at=datetime(2026, 8, 2),
    )
    session.add(row)
    session.commit()
    return row


def _runs(client, **params):
    res = client.get("/api/v1/ingestion-history", params=params)
    assert res.status_code == 200, res.text
    return res.json()


# ---------------------------------------------------------------------------
# H-1 — a non-invoice is a normal, explained row, never a disappearance
# ---------------------------------------------------------------------------
def test_h1_document_only_run_is_an_explained_row_not_a_disappearance(pg):
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        run = _batch(pg, tenant, trigger="manual", file_count=1)
        _document(pg, tenant, run.batch_id, tag=tag)
        client = _client(pg, tenant)
        try:
            body = _runs(client)
            mine = [i for i in body["items"] if i["run_id"] == str(run.batch_id)]
            assert len(mine) == 1, "a run that produced only a Document vanished"
            entry = mine[0]
            assert entry["status"] == "NOT_LOADED"
            assert entry["not_loaded"] == 1
            assert entry["loaded"] == 0
            assert entry["rejected"] == 0
            assert entry["summary"] == "1 file: 1 not loaded"
            assert entry["source"] == "manual"
            assert entry["flow_direction"] == "INBOUND"
        finally:
            app.dependency_overrides.clear()
    finally:
        _cleanup(pg, [tenant.id])


# ---------------------------------------------------------------------------
# H-2 — the drill-down carries the full record, and the outcome labels
# ---------------------------------------------------------------------------
def test_h2_drilldown_returns_full_records_and_both_outcome_labels(pg):
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        run = _batch(pg, tenant, file_count=2)
        _invoice(pg, tenant, run.batch_id, tag=tag)
        _document(pg, tenant, run.batch_id, tag=tag)
        client = _client(pg, tenant)
        try:
            res = client.get(f"/api/v1/ingestion-history/{run.batch_id}/files")
            assert res.status_code == 200, res.text
            items = {i["kind"]: i for i in res.json()["items"]}
            assert set(items) == {"invoice", "document"}

            inv = items["invoice"]
            assert inv["outcome"] == OUTCOME_LOADED
            assert inv["outcome_label"] == "Loaded — COMPLETED"
            # The full record, fetched only because the row was expanded.
            assert inv["record"]["invoice_number"] == f"INV-{tag}"
            assert inv["record"]["grand_total"] == 99120.0
            assert inv["record"]["items"][0]["description"] == "MS Angle 50x50x6"
            assert inv["record"]["sa_alerts"][0]["message"] == "seeded"

            doc = items["document"]
            assert doc["outcome"] == OUTCOME_NOT_LOADED
            assert doc["outcome_label"] == "Not loaded — Delivery note"
            assert doc["record"]["doc_type_evidence"] == "DELIVERY CHALLAN"
            assert doc["record"]["doc_attributes"]["direction"]["value"] == "INBOUND"
            assert doc["record"]["items"][0]["description"] == "MS Flat 40x6"

            # The list row for the same run agrees with its own expansion.
            entry = [i for i in _runs(client)["items"] if i["run_id"] == str(run.batch_id)][0]
            assert entry["status"] == "PARTIAL" or entry["status"] == "LOADED"
            assert entry["loaded"] == 1 and entry["not_loaded"] == 1
            assert entry["summary"] == "2 files: 1 loaded, 1 not loaded"
        finally:
            app.dependency_overrides.clear()
    finally:
        _cleanup(pg, [tenant.id])


# ---------------------------------------------------------------------------
# H-3 — THE GUARANTEE. This feature is presentation-only.
# ---------------------------------------------------------------------------
def test_h3_history_surface_does_not_move_dashboard_aggregates(pg):
    """`/dashboard/metrics` is byte-identical across the whole History surface.

    Same construction and the same reason as
    `tests/test_documents_table.py::test_t_e10_2_...` (the Gap 329-shaped test):
    a `Document` leaking into the aggregates still renders a plausible-looking
    dashboard, so anything weaker than "the bytes did not change" passes while a
    phantom vendor bucket is being created.

    What makes this the *Gap 464* version rather than a copy: the assertion
    brackets every endpoint this gap added, INCLUDING the archive writes. An
    implementation that reached the guarantee by never touching `invoice` on
    read but stamping something on it on archive would pass T-E10-2 and fail
    here.
    """
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        run = _batch(pg, tenant, file_count=2)
        # A real payable, so the aggregates are non-trivial: an empty dashboard
        # before and after would be byte-identical for the wrong reason.
        invoice = _invoice(pg, tenant, run.batch_id, tag=tag)
        _document(pg, tenant, run.batch_id, tag=tag)
        client = _client(pg, tenant)
        try:
            before = client.get("/api/v1/dashboard/metrics")
            assert before.status_code == 200
            before_bytes = before.content

            # Exercise everything Gap 464 added: list, both filtered lists,
            # drill-down, archive, archived view, unarchive.
            _runs(client)
            _runs(client, trigger="manual")
            _runs(client, flow_direction="INBOUND")
            assert client.get(f"/api/v1/ingestion-history/{run.batch_id}/files").status_code == 200
            assert client.post(
                f"/api/v1/ingestion-history/{run.batch_id}/archive"
            ).status_code == 200
            archived = _runs(client, archived="true")
            assert any(i["run_id"] == str(run.batch_id) for i in archived["items"])
            assert client.post(
                f"/api/v1/ingestion-history/{run.batch_id}/unarchive"
            ).status_code == 200

            after = client.get("/api/v1/dashboard/metrics")
            assert after.status_code == 200
            assert after.content == before_bytes, (
                "the ingestion History surface moved /dashboard/metrics. Gap 464 is "
                "presentation-only: a Document row must never enter `invoice` or any "
                "aggregate, and archiving a log line must not touch the invoice."
            )

            # And the invoice itself is untouched, field by field.
            pg.refresh(invoice)
            assert invoice.deleted_at is None
            assert invoice.status == "COMPLETED"
            assert invoice.grand_total == 99120.0
            # No `Document` row was promoted into `invoice`.
            assert len(pg.exec(
                select(Invoice).where(Invoice.tenant_id == tenant.id)
            ).all()) == 1
        finally:
            app.dependency_overrides.clear()
    finally:
        _cleanup(pg, [tenant.id])


# ---------------------------------------------------------------------------
# H-4 — archive is a hide of the log line, never a delete of anything
# ---------------------------------------------------------------------------
def test_h4_archive_unarchive_and_archive_all(pg):
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        run_a = _batch(pg, tenant, file_count=1, minutes_ago=10)
        run_b = _batch(pg, tenant, trigger="email", file_count=1, minutes_ago=5)
        _invoice(pg, tenant, run_a.batch_id, tag=tag + "a")
        _invoice(pg, tenant, run_b.batch_id, tag=tag + "b")
        client = _client(pg, tenant)
        try:
            live = _runs(client)
            ids = {i["run_id"] for i in live["items"]}
            assert {str(run_a.batch_id), str(run_b.batch_id)} <= ids

            res = client.post(f"/api/v1/ingestion-history/{run_a.batch_id}/archive")
            assert res.status_code == 200 and res.json()["archived"] == 1
            # Archiving twice is a 404, not a silent second success.
            assert client.post(
                f"/api/v1/ingestion-history/{run_a.batch_id}/archive"
            ).status_code == 404

            live = _runs(client)
            assert str(run_a.batch_id) not in {i["run_id"] for i in live["items"]}
            archived = _runs(client, archived="true")
            assert str(run_a.batch_id) in {i["run_id"] for i in archived["items"]}
            # An archived run is still drillable — a visible row that cannot be
            # opened is a dead end (see the endpoint docstring).
            assert client.get(
                f"/api/v1/ingestion-history/{run_a.batch_id}/files"
            ).status_code == 200

            assert client.post(
                f"/api/v1/ingestion-history/{run_a.batch_id}/unarchive"
            ).json()["archived"] == 1
            assert str(run_a.batch_id) in {i["run_id"] for i in _runs(client)["items"]}

            res = client.post("/api/v1/ingestion-history/archive-all")
            assert res.status_code == 200 and res.json()["archived"] >= 2
            mine = {str(run_a.batch_id), str(run_b.batch_id)}
            assert not (mine & {i["run_id"] for i in _runs(client)["items"]})
            assert mine <= {i["run_id"] for i in _runs(client, archived="true")["items"]}

            # Nothing was deleted. Both invoices are still live payables.
            assert len(pg.exec(
                select(Invoice).where(
                    Invoice.tenant_id == tenant.id,
                    Invoice.deleted_at.is_(None),  # type: ignore[union-attr]
                )
            ).all()) == 2
        finally:
            app.dependency_overrides.clear()
    finally:
        _cleanup(pg, [tenant.id])


# ---------------------------------------------------------------------------
# H-5 — tenant scoping, 404 never 403
# ---------------------------------------------------------------------------
def test_h5_another_tenants_run_is_invisible_and_404s(pg):
    tag = uuid4().hex[:10]
    tenant_a = _tenant(pg, tag, name="A")
    tenant_b = _tenant(pg, tag, name="B")
    try:
        run_a = _batch(pg, tenant_a, file_count=1)
        _document(pg, tenant_a, run_a.batch_id, tag=tag)
        client = _client(pg, tenant_b)
        try:
            assert str(run_a.batch_id) not in {i["run_id"] for i in _runs(client)["items"]}
            assert client.get(
                f"/api/v1/ingestion-history/{run_a.batch_id}/files"
            ).status_code == 404
            assert client.post(
                f"/api/v1/ingestion-history/{run_a.batch_id}/archive"
            ).status_code == 404
            # A malformed id is a 404 too, not a 422 — indistinguishable from a
            # run that does not exist, so this cannot be used to probe.
            assert client.get(
                "/api/v1/ingestion-history/not-a-uuid/files"
            ).status_code == 404
        finally:
            app.dependency_overrides.clear()

        # And A's own run is untouched by B's attempts.
        pg.refresh(run_a)
        assert run_a.archived_at is None
    finally:
        _cleanup(pg, [tenant_a.id, tenant_b.id])


# ---------------------------------------------------------------------------
# H-6 — a rejected inbound email is finally visible to its own tenant
# ---------------------------------------------------------------------------
def test_h6_dropped_inbound_email_is_a_rejected_run(pg):
    tag = uuid4().hex[:10]
    tenant = _tenant(pg, tag)
    try:
        dropped = DroppedInboundEmail(
            id=uuid4(),
            tenant_id=tenant.id,
            reason="no_pdf_attachment",
            detail="The message carried no PDF and no supported image.",
            from_email=f"ap-{tag}@example.invalid",
            to_email="inbound@invoice-llm.invalid",
            filename="signature.gif",
        )
        pg.add(dropped)
        pg.commit()
        client = _client(pg, tenant)
        try:
            entry = [
                i for i in _runs(client)["items"] if i["run_id"] == f"email:{dropped.id}"
            ]
            assert len(entry) == 1, (
                "a rejected inbound email is still invisible to the tenant it "
                "concerns — it was Admin-console-only before Gap 464"
            )
            assert entry[0]["status"] == "REJECTED"
            assert entry[0]["source"] == "email"
            assert entry[0]["summary"] == "Rejected — no invoice content"

            res = client.get(f"/api/v1/ingestion-history/email:{dropped.id}/files")
            assert res.status_code == 200
            item = res.json()["items"][0]
            assert item["kind"] == "rejected_email"
            assert item["outcome"] == OUTCOME_REJECTED
            assert item["file_name"] == "signature.gif"
            assert item["record"]["from_email"] == f"ap-{tag}@example.invalid"

            assert client.post(
                f"/api/v1/ingestion-history/email:{dropped.id}/archive"
            ).json()["archived"] == 1
            assert f"email:{dropped.id}" not in {i["run_id"] for i in _runs(client)["items"]}
        finally:
            app.dependency_overrides.clear()
    finally:
        _cleanup(pg, [tenant.id])


# ---------------------------------------------------------------------------
# H-7 — the outcome vocabulary is total (pure, no database)
# ---------------------------------------------------------------------------
def test_h7_every_invoice_status_maps_to_exactly_one_outcome():
    """No status falls into a fifth, silent state.

    The three frozensets are disjoint by construction and everything else is
    LOADED. Asserted rather than assumed, because the failure mode is a status
    added later that quietly reads as "Loaded" on a screen whose whole job is to
    say what happened.
    """
    assert not (IN_PROGRESS_INVOICE_STATUSES & REJECTED_INVOICE_STATUSES)
    assert not (IN_PROGRESS_INVOICE_STATUSES & DUPLICATE_INVOICE_STATUSES)
    assert not (REJECTED_INVOICE_STATUSES & DUPLICATE_INVOICE_STATUSES)

    for value in IN_PROGRESS_INVOICE_STATUSES:
        assert _invoice_outcome(value)[0] == OUTCOME_IN_PROGRESS
    for value in REJECTED_INVOICE_STATUSES:
        assert _invoice_outcome(value)[0] == OUTCOME_REJECTED
    for value in DUPLICATE_INVOICE_STATUSES:
        outcome, label = _invoice_outcome(value)
        assert outcome == OUTCOME_NOT_LOADED
        assert label == "Not loaded — duplicate of an earlier upload"

    for value in ("COMPLETED", "VERIFIED", "AUDIT_REQUIRED", "PAID", "SENT"):
        outcome, label = _invoice_outcome(value)
        assert outcome == OUTCOME_LOADED
        assert label == f"Loaded — {value}"

    # Unknown and empty both fall through to LOADED with an honest label rather
    # than to a blank chip.
    assert _invoice_outcome("SOMETHING_NEW") == (OUTCOME_LOADED, "Loaded — SOMETHING_NEW")
    assert _invoice_outcome(None) == (OUTCOME_LOADED, "Loaded — UNKNOWN")
