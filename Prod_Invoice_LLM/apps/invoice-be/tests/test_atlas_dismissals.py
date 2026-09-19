"""Feature 34 / D49 — a dismissed line does not come back.

Spec: `docs/feature_34_atlas.md` §16 · `atlas_discussion.md` D49.

Real Postgres only (hard rule 2) — `tests/atlas_pg.py` is the guard, and it
**fails rather than skips** on a configured-but-unreachable database (BE Gap
689), so a green run here means these assertions actually ran.

What is asserted, and why each one is here
------------------------------------------
1. **The line is gone from the payload, not flagged in it.** The founder's rule
   is that the filter is server-side, before the response is assembled; the FE
   filters nothing. So the assertion is on the response body's ids.
2. **It survives a recompute.** D38 rebuilds every line on every open, so the
   test dismisses, then makes a second, entirely independent request.
3. **It applies to the doubt asks too**, not only the skills. Those are produced
   by a different code path in the same router and were the exact case D49 was
   raised about ("attach the quotation and compare", done in chat, line returns).
4. **Recommendation ids are deterministic.** The whole mechanism rests on it and
   nothing else would fail if an emitter started minting UUIDs — the dismissal
   would just silently stop working. Asserted directly.
5. **Per user and per tenant.** One Auditor marking their line done must not
   blind the Admin, who is the superset (§2.2).
6. **Idempotent.** A repeat click writes no second row.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from dependencies import TenantContext, get_db_session, get_tenant_context
from main import app
from models import AtlasDismissal, Invoice, Tenant
from services.atlas_dismissals import dismissed_ids
from tests.atlas_pg import open_session, unique_tag

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
    """A fresh tenant per test; everything it wrote is removed afterwards."""
    tag = unique_tag()
    tenant = Tenant(name=f"atlas-dismiss-{tag}", domain=f"atlas-dismiss-{tag}.test")
    pg_session.add(tenant)
    pg_session.commit()
    pg_session.refresh(tenant)
    written: list = []
    try:
        yield pg_session, tenant, written
    finally:
        pg_session.rollback()
        for row in pg_session.exec(
            select(AtlasDismissal).where(AtlasDismissal.tenant_id == tenant.id)
        ).all():
            pg_session.delete(row)
        for row in written:
            pg_session.delete(row)
        pg_session.commit()
        pg_session.delete(tenant)
        pg_session.commit()


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _client(session, tenant, *, user_id: str, role: str = "Auditor", **grants):
    context = TenantContext(
        tenant_id=tenant.id,
        user_id=user_id,
        role=role,
        billing_plan="active",
        can_audit=grants.pop("can_audit", True),
        can_train=grants.pop("can_train", False),
        can_load=grants.pop("can_load", False),
    )
    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[get_tenant_context] = lambda: context
    return TestClient(app)


def _invoice(session, written, tenant, **fields) -> Invoice:
    defaults = dict(
        tenant_id=tenant.id,
        file_path=f"tests/{uuid4().hex}.pdf",
        status="AUDIT_REQUIRED",
        flow_direction="INBOUND",
        currency="INR",
        invoice_number=uuid4().hex[:6].upper(),
        vendor_name="Kumar Supplies",
        grand_total=50000.0,
        due_date=TODAY + timedelta(days=3),
    )
    defaults.update(fields)
    inv = Invoice(**defaults)
    session.add(inv)
    session.commit()
    session.refresh(inv)
    written.append(inv)
    return inv


def _ids(client) -> list[str]:
    response = client.get("/api/v1/atlas/lines")
    assert response.status_code == 200, response.text
    return [line["id"] for line in response.json()["lines"]]


# ═════════════════════════════════════════════════════════════════════════════
# The mechanism it all rests on
# ═════════════════════════════════════════════════════════════════════════════


def test_recommendation_ids_are_stable_across_recomputes(pg):
    """No per-run UUIDs. If this ever fails, dismissal silently stops working."""
    session, tenant, written = pg
    _invoice(session, written, tenant)
    _invoice(session, written, tenant)
    client = _client(session, tenant, user_id="user_stable")

    first = _ids(client)
    second = _ids(client)

    assert first, "the fixture produced no lines, so this proves nothing"
    assert first == second


# ═════════════════════════════════════════════════════════════════════════════
# D49 — the dismissal itself
# ═════════════════════════════════════════════════════════════════════════════


def test_a_dismissed_line_is_absent_from_the_next_response(pg):
    """The assertion that matters: absent from the payload, not flagged in it."""
    session, tenant, written = pg
    _invoice(session, written, tenant)
    _invoice(session, written, tenant)
    client = _client(session, tenant, user_id="user_dismisser")

    before = _ids(client)
    assert len(before) >= 2, before
    target = before[0]

    dismissed = client.post(f"/api/v1/atlas/lines/{target}/dismiss")
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json() == {
        "recommendation_id": target,
        "dismissed": True,
        "created": True,
    }

    after = _ids(client)
    assert target not in after
    assert set(after) == set(before) - {target}

    # And nothing on the wire carries it in any other form -- no flag, no
    # tombstone, no "dismissed": true entry the FE would have to honour.
    body = client.get("/api/v1/atlas/lines").text
    assert target not in body


def test_a_doubt_ask_can_be_dismissed_too(pg):
    """The §3.3 asks are produced by a different path in the same router.

    This is the case D49 was raised about: "attach the quotation and compare",
    the user does exactly that in chat (D47), and nothing the recompute can see
    has changed.
    """
    session, tenant, written = pg
    # A vendor baseline, then one invoice far outside it -- how a doubt is made.
    for _ in range(4):
        _invoice(session, written, tenant, status="APPROVED", grand_total=50000.0)
    _invoice(session, written, tenant, invoice_number="1041", grand_total=241300.0)

    client = _client(session, tenant, user_id="user_doubt")
    doubts = [i for i in _ids(client) if i.startswith("doubt-")]
    assert doubts, f"no doubt line was produced; ids were {_ids(client)}"

    target = doubts[0]
    assert client.post(f"/api/v1/atlas/lines/{target}/dismiss").status_code == 200
    assert target not in _ids(client)


def test_a_dismissal_is_per_user(pg):
    """One person marking their line done does not blind the Admin (§2.2)."""
    session, tenant, written = pg
    _invoice(session, written, tenant)
    mine = _client(session, tenant, user_id="user_one")
    target = _ids(mine)[0]
    assert client_post(mine, target)

    theirs = _client(session, tenant, user_id="user_two", role="Admin")
    assert target in _ids(theirs)


def test_a_dismissal_is_per_tenant(pg, pg_session):
    """Deterministic ids are only unique inside a tenant; the store is scoped."""
    session, tenant, written = pg
    _invoice(session, written, tenant)
    client = _client(session, tenant, user_id="user_shared")
    target = _ids(client)[0]
    assert client_post(client, target)

    other_tag = unique_tag()
    other = Tenant(name=f"atlas-other-{other_tag}", domain=f"atlas-other-{other_tag}.test")
    pg_session.add(other)
    pg_session.commit()
    pg_session.refresh(other)
    try:
        # The same user id, the same recommendation id, a different tenant:
        # the store must not carry it across. Asserted on the service rather
        # than the endpoint because a second tenant's lines would need a second
        # tenant's invoices, which proves less about the scoping than this does.
        assert target in dismissed_ids(pg_session, tenant.id, "user_shared")
        assert target not in dismissed_ids(pg_session, other.id, "user_shared")
    finally:
        pg_session.delete(other)
        pg_session.commit()


def test_dismissing_twice_writes_one_row(pg):
    """Idempotent: a repeat click from a stale screen is not a second row.

    D12's noise pruning ("dismissed 40 times -- remove the alert?") will read
    these rows, and a double-counted dismissal would make that recommendation
    wrong.
    """
    session, tenant, written = pg
    _invoice(session, written, tenant)
    client = _client(session, tenant, user_id="user_twice")
    target = _ids(client)[0]

    first = client.post(f"/api/v1/atlas/lines/{target}/dismiss").json()
    second = client.post(f"/api/v1/atlas/lines/{target}/dismiss").json()
    assert first["created"] is True
    assert second["created"] is False
    assert second["dismissed"] is True

    rows = session.exec(
        select(AtlasDismissal).where(
            AtlasDismissal.tenant_id == tenant.id,
            AtlasDismissal.recommendation_id == target,
        )
    ).all()
    assert len(rows) == 1


def test_dismissing_an_unknown_id_is_accepted_and_suppresses_nothing(pg):
    """Stated behaviour, not an accident -- see `atlas_dismissals.dismiss()`."""
    session, tenant, written = pg
    _invoice(session, written, tenant)
    client = _client(session, tenant, user_id="user_unknown")
    before = _ids(client)

    response = client.post("/api/v1/atlas/lines/audit-approve-not-a-real-line/dismiss")
    assert response.status_code == 200
    assert _ids(client) == before


def client_post(client, recommendation_id: str) -> bool:
    response = client.post(f"/api/v1/atlas/lines/{recommendation_id}/dismiss")
    assert response.status_code == 200, response.text
    return response.json()["dismissed"]
