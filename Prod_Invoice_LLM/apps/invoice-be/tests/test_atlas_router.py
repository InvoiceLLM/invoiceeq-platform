"""BE Gap 691 — `routers/atlas.py`, the work screen's read surface.

Spec: `docs/feature_34_atlas.md` §15 (the two envelopes) · §12.2 (the contract
served verbatim) · §2.1 (absent, not disabled) · D3 (zero grants, zero lines).

Every test runs against the real dev Postgres (hard rule 2) through a
`TestClient`, with **only** the two dependencies a deployment also swaps
overridden -- the database session and the resolved `TenantContext`. The
capability filtering under test is `GrantSet.from_context()`'s, on the same
context shape `dependencies.get_tenant_context()` builds, so a grant resolved in
a test and a grant resolved in production cannot disagree.

What these tests are *for*: FE Feature 23 renders whatever this returns. The
F33/F22 seam was a field one side read and the other never sent, so the
assertions below are about the wire -- the keys, the empty state, and the fact
that a line the caller may not act on is not in the payload at all.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from dependencies import TenantContext, get_db_session, get_tenant_context
from main import app
from models import Document, Invoice, Tenant
from tests.atlas_pg import open_session, postgres_only, unique_tag

TODAY = date.today()


@pytest.fixture(scope="module")
def pg_session():
    session = open_session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def pg(pg_session):
    """A fresh tenant per test; every row it writes is deleted afterwards.

    Per test, not per module: these endpoints read *everything* the tenant has,
    so one test's invoice would silently become another test's cash position.
    """
    tag = unique_tag()
    tenant = Tenant(name=f"atlas-router-{tag}", domain=f"atlas-router-{tag}.test")
    pg_session.add(tenant)
    pg_session.commit()
    pg_session.refresh(tenant)
    written: list = []
    try:
        yield pg_session, tenant, written
    finally:
        pg_session.rollback()
        for row in written:
            pg_session.delete(row)
        pg_session.commit()
        pg_session.delete(tenant)
        pg_session.commit()


def _client(session, tenant, **grants) -> TestClient:
    context = TenantContext(
        tenant_id=tenant.id,
        user_id=f"user_{uuid4().hex[:8]}",
        role=grants.pop("role", "Auditor"),
        billing_plan="active",
        can_audit=grants.pop("can_audit", False),
        can_train=grants.pop("can_train", False),
        can_load=grants.pop("can_load", False),
    )
    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[get_tenant_context] = lambda: context
    client = TestClient(app)
    client.__exit__ = None  # documentation: the overrides are cleared by the fixture
    return client


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _invoice(session, written, tenant, **fields) -> Invoice:
    defaults = dict(
        tenant_id=tenant.id,
        file_path=f"tests/{uuid4().hex}.pdf",
        status="AUDIT_REQUIRED",
        flow_direction="INBOUND",
        currency="INR",
    )
    defaults.update(fields)
    inv = Invoice(**defaults)
    session.add(inv)
    session.commit()
    session.refresh(inv)
    written.append(inv)
    return inv


def _statement_doc(session, written, tenant, *, vendor, items, currency="INR") -> Document:
    doc = Document(
        tenant_id=tenant.id,
        file_path=f"tests/{uuid4().hex}.pdf",
        doc_type="STATEMENT_OF_ACCOUNT",
        counterparty_name=vendor,
        currency=currency,
        items=items,
        status="EXTRACTED",
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    written.append(doc)
    return doc


# ═════════════════════════════════════════════════════════════════════════════
# GET /atlas/lines
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_a_caller_with_no_grants_gets_the_stated_empty_position(pg):
    """D3, and the reason `ungranted` is a field rather than `len(lines) == 0`.

    "No tasks assigned" and "nothing needs you today" are different sentences,
    and a client that inferred between them would tell a busy Auditor they have
    no access on the one morning they are clear.
    """
    session, tenant, written = pg
    _invoice(
        session, written, tenant,
        vendor_name="Kumar Supplies", invoice_number="1041",
        grand_total=241300.0, due_date=TODAY + timedelta(days=3),
    )
    client = _client(session, tenant, role="NO_ROLE")

    body = client.get("/api/v1/atlas/lines").json()

    assert body["ungranted"] is True
    assert body["lines"] == []
    assert body["capabilities"] == []


@postgres_only
def test_an_auditor_receives_the_whole_line_and_every_part_of_it(pg):
    """§2: what / why / action / verify, and `batchable` computed on the wire."""
    session, tenant, written = pg
    inv = _invoice(
        session, written, tenant,
        vendor_name="Kumar Supplies", invoice_number="1041",
        grand_total=241300.0, due_date=TODAY + timedelta(days=3),
    )
    client = _client(session, tenant, can_audit=True)

    body = client.get("/api/v1/atlas/lines").json()

    assert body["ungranted"] is False
    assert body["capabilities"] == ["audit"]
    mine = [line for line in body["lines"] if line["what"]["entity_id"] == str(inv.id)]
    assert mine, "the invoice awaiting a decision produced no line"
    line = mine[0]
    for part in ("what", "why", "action", "verify"):
        assert line[part], f"{part} missing from the wire payload"
    assert line["what"]["headline"]
    assert line["why"]["text"]
    assert line["action"]["kind"] and line["action"]["label"]
    assert line["verify"]["question"]
    assert isinstance(line["batchable"], bool)
    assert line["capability"] == "audit"
    # §5.3 on the wire, not only in the service: the exact number, never rounded.
    assert "2,41,300.00" in line["why"]["text"]


@postgres_only
def test_a_line_the_caller_cannot_act_on_is_absent_not_disabled(pg):
    """§2.1. A greyed-out row still leaks the vendor, the amount and the doubt."""
    session, tenant, written = pg
    _invoice(
        session, written, tenant,
        vendor_name="Kumar Supplies", invoice_number="1041",
        grand_total=241300.0, due_date=TODAY + timedelta(days=3),
    )
    loader = _client(session, tenant, can_load=True, role="Loader")

    body = loader.get("/api/v1/atlas/lines").json()

    assert body["ungranted"] is False
    assert body["capabilities"] == ["load"]
    assert [line for line in body["lines"] if line["capability"] == "audit"] == []
    assert all(line["capability"] == "load" for line in body["lines"])
    # And nothing annotates the dropped ones: there is no disabled/visible flag
    # to leak them through.
    assert all("disabled" not in line for line in body["lines"])


@postgres_only
def test_the_doubt_checks_report_what_they_did_not_run(pg):
    """§13.5's cost, made visible rather than silently truncated."""
    session, tenant, written = pg
    _invoice(
        session, written, tenant,
        vendor_name="Kumar Supplies", invoice_number="1041",
        grand_total=241300.0, due_date=TODAY + timedelta(days=3),
    )
    client = _client(session, tenant, can_audit=True)

    body = client.get("/api/v1/atlas/lines").json()

    assert body["doubt_checks_run"] == 1
    assert body["doubt_checks_skipped"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# POST /atlas/recon
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_recon_returns_the_four_groups_from_the_servers_own_rows(pg):
    """§6. Four groups, every amount already rendered by the server."""
    session, tenant, written = pg
    agreed = _invoice(
        session, written, tenant,
        vendor_name="Kumar Supplies", invoice_number="1041",
        grand_total=50000.0, invoice_date=TODAY - timedelta(days=20),
    )
    short = _invoice(
        session, written, tenant,
        vendor_name="Kumar Supplies", invoice_number="1042",
        grand_total=100000.0, invoice_date=TODAY - timedelta(days=18),
    )
    _invoice(
        session, written, tenant,
        vendor_name="Kumar Supplies", invoice_number="1043",
        grand_total=25000.0, invoice_date=TODAY - timedelta(days=15),
    )
    doc = _statement_doc(
        session, written, tenant,
        vendor="Kumar Supplies",
        items=[
            {"description": "INV-1041 05/08/2026", "amount": 50000.0},
            {"description": "INV-1042 08/08/2026", "amount": 98000.0},
            {"description": "INV-9999 09/08/2026", "amount": 12000.0},
            {"description": "opening balance carried forward", "amount": 4000.0},
        ],
    )
    client = _client(session, tenant, can_audit=True)

    response = client.post("/api/v1/atlas/recon", json={"document_id": str(doc.id)})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["vendor_name"] == "Kumar Supplies"
    assert body["currency"] == "INR"
    assert body["agrees"] is False
    groups = body["groups"]
    assert [row["invoice_id"] for row in groups["matched"]] == [str(agreed.id)]
    assert groups["matched"][0]["amount_rendered"] == "50,000.00"
    assert [row["invoice_number"] for row in groups["they_show_we_do_not"]] == ["INV-9999"]
    assert [row["invoice_number"] for row in groups["we_show_they_do_not"]] == ["1043"]
    differs = groups["amount_differs"]
    assert [row["invoice_id"] for row in differs] == [str(short.id)]
    assert differs[0]["theirs_rendered"] == "98,000.00"
    assert differs[0]["ours_rendered"] == "1,00,000.00"
    assert differs[0]["difference_rendered"] == "-2,000.00"
    # The row with no readable invoice number is reported as unreadable, never
    # as a finding about the vendor.
    assert len(groups["unmatchable"]) == 1
    assert groups["unmatchable"][0]["invoice_number"] is None
    # Agreement is not work (§14.4): one line per non-empty *disagreement*
    # bucket and none for `matched`, whose count appears inside the other lines
    # as context. Asserted by count and by id, not by phrasing -- the lines do
    # say "everything else agrees", which is the context, not a finding.
    assert len(body["lines"]) == 3
    assert all(not line["id"].startswith("recon-matched") for line in body["lines"])


@postgres_only
def test_recon_refuses_rather_than_guessing_when_it_cannot_tell_whose_statement_it_is(pg):
    session, tenant, written = pg
    doc = _statement_doc(
        session, written, tenant, vendor=None,
        items=[{"description": "INV-1041", "amount": 50000.0}],
    )
    client = _client(session, tenant, can_audit=True)

    response = client.post("/api/v1/atlas/recon", json={"document_id": str(doc.id)})

    assert response.status_code == 422
    assert "whose statement" in response.json()["detail"]


@postgres_only
def test_recon_404s_on_a_document_this_tenant_does_not_own(pg):
    """404, never 403 -- a 403 confirms the row exists."""
    session, tenant, written = pg
    client = _client(session, tenant, can_audit=True)

    response = client.post("/api/v1/atlas/recon", json={"document_id": str(uuid4())})

    assert response.status_code == 404


@postgres_only
def test_recon_counts_the_rows_it_could_not_read_rather_than_reading_them_as_zero(pg):
    """Gap 283's lesson: `None` is not zero, least of all in a vendor's statement."""
    session, tenant, written = pg
    _invoice(
        session, written, tenant,
        vendor_name="Kumar Supplies", invoice_number="1041", grand_total=50000.0,
    )
    doc = _statement_doc(
        session, written, tenant, vendor="Kumar Supplies",
        items=[
            {"description": "INV-1041", "amount": 50000.0},
            {"description": "brought forward", "amount": None},
        ],
    )
    client = _client(session, tenant, can_audit=True)

    body = client.post(
        "/api/v1/atlas/recon", json={"document_id": str(doc.id)}
    ).json()

    assert body["unreadable_rows"] == 1
    assert body["agrees"] is True
    assert body["lines"] == []
