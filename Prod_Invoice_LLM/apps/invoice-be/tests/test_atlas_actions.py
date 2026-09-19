"""Feature 34 / task 34.7 — ATLAS can act, on exactly two kinds.

Spec: `docs/feature_34_atlas.md` §17 · `atlas_discussion.md` **D50, D51**.

Real Postgres only (hard rule 2) — `tests/atlas_pg.py` is the guard, and it
**fails rather than skips** on a configured-but-unreachable database (BE Gap
697), so a green run here means these assertions actually ran.

What is asserted, and why each one is here
------------------------------------------
1. **A user without the grant cannot ACT, not merely cannot see.** The seeing
   check (`visible_to()`) already existed and drops the line from the payload.
   This is the second, separate decision (34.7b): a request naming a line id
   arrives whatever was rendered, so the refusal has to be at the endpoint. The
   test posts the id a Loader was never shown and asserts 403.
2. **A suggest-only kind never performs a write** (D50). Asserted twice over:
   the endpoint answers 409, *and* the invoice row is re-read afterwards and is
   byte-for-byte what it was. A status code alone would not prove nothing
   happened.
3. **A performed action appears in the log, attributed and timestamped** (§5.3),
   and so does a refused one — a list that held only successes would answer
   "did ATLAS touch this?" with a confident no on the occasions it matters.
4. **A kind with no working path is absent from `PERFORMABLE_ACTION_KINDS`.**
   Asserted as an exact set, not a superset: this is the honesty mechanism from
   Slice B and a "contains" assertion would let a kind be enabled ahead of its
   endpoint without failing.
5. **Every kind an emitter produces has a disposition.** Grep-shaped over the
   three emitter modules, because the failure mode is a skill added later whose
   kind falls through to a 422 nobody expected.
6. **`params` are not passed through.** A `resolve_invoice` click carrying
   `corrections` and `apply_as_standing_rule` must not teach a standing rule —
   that is `apply_field_correction`, which D50 made suggest-only. This is the
   one test that proves the ruling holds at field level and not just at kind
   level.
7. **The acting gate matches the audit router's own gate.** `perform_action`
   calls `resolve_audit_invoice` directly, which does not run
   `Depends(require_actions_scope)`. If the two rules ever disagreed, ATLAS
   would become a way around a permission check, so the equivalence is asserted
   rather than described in a docstring.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from dependencies import TenantContext, get_db_session, get_tenant_context
from main import app
from models import AtlasActionLog, Invoice, RoleMapper, Tenant
from services.atlas_actions import (
    ACTION_CAPABILITY,
    ACTION_DISPOSITIONS,
    PERFORMABLE_ACTION_KINDS,
    SUGGEST_ONLY_ACTION_KINDS,
    ActionDisposition,
)
from services.atlas_capabilities import AtlasCapability, GrantSet
from tests.atlas_pg import open_session, unique_tag

TODAY = date.today()

#: D50/D51, as an exact set. Adding a kind here without an endpoint behind it is
#: the failure this assertion exists to make loud.
EXPECTED_PERFORMABLE = {"resolve_invoice", "retry_ingestion_source"}
EXPECTED_SUGGEST_ONLY = {"apply_field_correction", "requeue_invoices"}


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
    tenant = Tenant(name=f"atlas-act-{tag}", domain=f"atlas-act-{tag}.test")
    pg_session.add(tenant)
    pg_session.commit()
    pg_session.refresh(tenant)
    written: list = []
    try:
        yield pg_session, tenant, written
    finally:
        pg_session.rollback()
        for row in pg_session.exec(
            select(AtlasActionLog).where(AtlasActionLog.tenant_id == tenant.id)
        ).all():
            pg_session.delete(row)
        pg_session.commit()
        for row in written:
            pg_session.delete(row)
        pg_session.commit()
        pg_session.delete(tenant)
        pg_session.commit()


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _client(session, tenant, *, user_id: str = "user-atlas", role: str = "Auditor", **grants):
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


def _log_rows(session, tenant) -> list[AtlasActionLog]:
    return list(
        session.exec(
            select(AtlasActionLog).where(AtlasActionLog.tenant_id == tenant.id)
        ).all()
    )


# ─────────────────────────────────────────────────────────────────────────────
# 34.7d — the performable set is exact, and populated one kind at a time
# ─────────────────────────────────────────────────────────────────────────────

def test_performable_set_is_exactly_the_two_ruled_kinds():
    """D50/D51. An exact set, deliberately: `>=` would let a kind be enabled
    ahead of its endpoint without anything going red."""
    assert set(PERFORMABLE_ACTION_KINDS) == EXPECTED_PERFORMABLE
    assert set(SUGGEST_ONLY_ACTION_KINDS) == EXPECTED_SUGGEST_ONLY


def test_every_emitted_action_kind_has_a_disposition():
    """Grep-shaped over the emitters, so a skill added later cannot ship a kind
    the dispatcher has never heard of."""
    root = Path(__file__).resolve().parents[1] / "services"
    emitted: set[str] = set()
    for name in ("atlas_skills.py", "atlas_recon.py", "atlas_doubt.py"):
        text = (root / name).read_text(encoding="utf-8")
        # `(?<!entity_)` because `What.entity_kind="invoice"` is not an action
        # kind and sweeping it in here would make this test fail for a reason
        # that has nothing to do with the thing it is guarding.
        emitted |= set(re.findall(r'(?<!entity_)kind="([a-z_]+)"', text))
    assert emitted, "no action kinds found - the grep, not the code, is broken"
    missing = emitted - set(ACTION_DISPOSITIONS)
    assert not missing, f"emitted kinds with no disposition: {sorted(missing)}"


def test_every_kind_marked_performable_has_a_dispatch_branch():
    """The table and the `perform_action` branches are two lists that must not
    drift; a kind in one and not the other is a 500 waiting for a click."""
    import inspect

    from services import atlas_actions

    source = inspect.getsource(atlas_actions.perform_action)
    for kind, disposition in ACTION_DISPOSITIONS.items():
        if disposition is ActionDisposition.PERFORM:
            assert f'kind == "{kind}"' in source, f"{kind} has no dispatch branch"


def test_action_kinds_endpoint_serves_the_same_table(pg):
    """34.7d: the FE reads this rather than keeping a second copy of it."""
    session, tenant, _ = pg
    client = _client(session, tenant)
    body = client.get("/api/v1/atlas/actions/kinds").json()
    assert set(body["performable"]) == EXPECTED_PERFORMABLE
    assert set(body["suggest_only"]) == EXPECTED_SUGGEST_ONLY
    assert body["dispositions"]["attach_witness_document"] == "instruct"


# ─────────────────────────────────────────────────────────────────────────────
# 34.7a — the dispatcher actually resolves an invoice
# ─────────────────────────────────────────────────────────────────────────────

def test_resolve_invoice_marks_the_invoice_paid_in_postgres(pg):
    """The whole point of Slice C: a click on a line changes a record.

    Asserted against the row, re-read from the database, not against the
    response body — the response is what the endpoint claims and the row is what
    happened.
    """
    session, tenant, written = pg
    inv = _invoice(session, written, tenant)
    client = _client(session, tenant, role="Admin")

    res = client.post(
        f"/api/v1/atlas/lines/audit-approve-{inv.id}/act",
        json={"kind": "resolve_invoice", "target_id": str(inv.id), "params": {"status": "PAID"}},
    )
    assert res.status_code == 200, res.text
    assert res.json()["performed"] is True

    session.expire_all()
    reread = session.get(Invoice, inv.id)
    assert reread.status == "PAID"


def test_resolve_invoice_rejects_a_status_no_atlas_line_offers(pg):
    """`AuditResolutionPayload` accepts five statuses; an ATLAS line offers two.

    `AUDIT_REQUIRED` is Gap 193's Admin-only reopen of someone else's finalized
    decision, and it must not be reachable through a surface whose lines never
    propose it.
    """
    session, tenant, written = pg
    inv = _invoice(session, written, tenant, status="PAID")
    client = _client(session, tenant, role="Admin")

    res = client.post(
        f"/api/v1/atlas/lines/audit-approve-{inv.id}/act",
        json={
            "kind": "resolve_invoice",
            "target_id": str(inv.id),
            "params": {"status": "AUDIT_REQUIRED"},
        },
    )
    assert res.status_code == 422
    session.expire_all()
    assert session.get(Invoice, inv.id).status == "PAID"


def test_resolve_invoice_ignores_a_smuggled_standing_rule(pg):
    """Rule 4: `params` are rebuilt from a whitelist, never forwarded.

    A correction plus `apply_as_standing_rule` arriving under `resolve_invoice`'s
    name would teach a vendor-scoped rule — which is `apply_field_correction`,
    suggest-only by D50. The vendor name is re-read afterwards to prove the
    correction was dropped rather than merely unreported.
    """
    session, tenant, written = pg
    inv = _invoice(session, written, tenant, vendor_name="Kumar Supplies")
    client = _client(session, tenant, role="Admin")

    res = client.post(
        f"/api/v1/atlas/lines/audit-approve-{inv.id}/act",
        json={
            "kind": "resolve_invoice",
            "target_id": str(inv.id),
            "params": {
                "status": "PAID",
                "corrections": {"vendor_name": "Someone Else Entirely"},
                "apply_as_standing_rule": True,
            },
        },
    )
    assert res.status_code == 200, res.text
    session.expire_all()
    reread = session.get(Invoice, inv.id)
    assert reread.status == "PAID"
    assert reread.vendor_name == "Kumar Supplies"
    assert res.json()["detail"].get("corrections_applied") in (None, [], {})


# ─────────────────────────────────────────────────────────────────────────────
# 34.7b — the capability check on ACTING
# ─────────────────────────────────────────────────────────────────────────────

def test_a_caller_without_the_grant_is_refused_at_the_endpoint(pg):
    """Not merely shown a disabled button.

    The Loader below never saw this line — `visible_to()` drops it — but a
    disabled button is a client-side fact and this request does not care what
    was rendered.
    """
    session, tenant, written = pg
    inv = _invoice(session, written, tenant)
    client = _client(
        session, tenant, role="Loader", can_audit=False, can_train=False, can_load=True
    )

    res = client.post(
        f"/api/v1/atlas/lines/audit-approve-{inv.id}/act",
        json={"kind": "resolve_invoice", "target_id": str(inv.id), "params": {"status": "PAID"}},
    )
    assert res.status_code == 403
    session.expire_all()
    assert session.get(Invoice, inv.id).status == "AUDIT_REQUIRED"


def test_acting_gate_agrees_with_the_audit_router_gate():
    """`perform_action` calls `resolve_audit_invoice` directly, so the router's
    own `Depends(require_actions_scope)` never runs. If the two rules disagreed,
    ATLAS would be a way around a permission check.

    `require_actions_scope`'s human branch is `context.can_audit`; ATLAS's is
    `GrantSet.holds(AUDIT)`. Asserted over every role the mapper defines.
    """
    for role in ("Admin", "Auditor", "Trainer", "Loader", "NO_ROLE"):
        can_train, can_audit, can_load, _ = RoleMapper.resolve_permissions(role, None)
        grants = GrantSet.from_user(role, None)
        assert grants.holds(AtlasCapability.AUDIT) == bool(can_audit), role
        assert grants.holds(AtlasCapability.LOAD) == bool(can_load), role
        assert grants.holds(AtlasCapability.TRAIN) == bool(can_train), role


def test_acting_capability_is_declared_for_every_kind():
    """34.7b: the capability to act is its own table, and it has no holes."""
    assert set(ACTION_CAPABILITY) == set(ACTION_DISPOSITIONS)


# ─────────────────────────────────────────────────────────────────────────────
# 34.7e — suggest-only kinds never become writes
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind", sorted(EXPECTED_SUGGEST_ONLY))
def test_a_suggest_only_kind_is_refused_and_writes_nothing(pg, kind):
    """D50, asserted as a refusal **and** as an unchanged row.

    409 rather than 403: the caller may hold every grant. What conflicts is the
    ruling, and the message says which.
    """
    session, tenant, written = pg
    inv = _invoice(session, written, tenant)
    before = (inv.status, inv.vendor_name, inv.grand_total)
    client = _client(session, tenant, role="Admin")

    res = client.post(
        f"/api/v1/atlas/lines/train-arithmetic-{inv.id}/act",
        json={
            "kind": kind,
            "target_id": str(inv.id),
            "params": {"field": "grand_total", "value": "1.00"},
        },
    )
    assert res.status_code == 409, res.text
    session.expire_all()
    reread = session.get(Invoice, inv.id)
    assert (reread.status, reread.vendor_name, reread.grand_total) == before


@pytest.mark.parametrize(
    "kind", ["open_field_review", "open_upcoming_payments", "attach_witness_document"]
)
def test_navigation_and_instruction_kinds_are_refused(pg, kind):
    """They never were writes, and the endpoint says so rather than 404ing —
    a 404 would read as "not built yet", which is the wrong expectation to set
    about a ruling."""
    session, tenant, _ = pg
    client = _client(session, tenant, role="Admin")
    res = client.post(
        f"/api/v1/atlas/lines/whatever/act",
        json={"kind": kind, "target_id": str(tenant.id), "params": {}},
    )
    assert res.status_code == 409


def test_an_unknown_kind_is_refused_without_a_log_row(pg):
    """Nothing was attempted, so there is nothing for the log to record. A row
    here would be a record of the client's typo."""
    session, tenant, _ = pg
    client = _client(session, tenant, role="Admin")
    res = client.post(
        "/api/v1/atlas/lines/whatever/act",
        json={"kind": "delete_everything", "target_id": str(tenant.id)},
    )
    assert res.status_code == 422
    assert _log_rows(session, tenant) == []


# ─────────────────────────────────────────────────────────────────────────────
# 34.7c — the action log
# ─────────────────────────────────────────────────────────────────────────────

def test_a_performed_action_is_logged_attributed_and_timestamped(pg):
    """§5.3: "every write is visible, attributed and timestamped"."""
    session, tenant, written = pg
    inv = _invoice(session, written, tenant)
    client = _client(session, tenant, role="Admin", user_id="clerk-user-77")

    client.post(
        f"/api/v1/atlas/lines/audit-approve-{inv.id}/act",
        json={"kind": "resolve_invoice", "target_id": str(inv.id), "params": {"status": "PAID"}},
    )

    rows = _log_rows(session, tenant)
    assert len(rows) == 1
    row = rows[0]
    assert row.action_kind == "resolve_invoice"
    assert row.target_id == str(inv.id)
    assert row.recommendation_id == f"audit-approve-{inv.id}"
    assert row.user_id == "clerk-user-77"
    assert row.succeeded is True
    assert row.performed_at is not None
    assert row.summary.strip()


def test_a_refused_action_is_logged_too(pg):
    """A log holding only successes answers "did ATLAS touch this?" with a
    confident no on exactly the occasions someone is asking."""
    session, tenant, written = pg
    inv = _invoice(session, written, tenant)
    client = _client(
        session, tenant, role="Loader", can_audit=False, can_train=False, can_load=True
    )
    client.post(
        f"/api/v1/atlas/lines/audit-approve-{inv.id}/act",
        json={"kind": "resolve_invoice", "target_id": str(inv.id), "params": {"status": "PAID"}},
    )

    rows = _log_rows(session, tenant)
    assert len(rows) == 1
    assert rows[0].succeeded is False
    assert "permission" in rows[0].summary.lower()


def test_the_action_log_is_readable_over_the_wire(pg):
    """"What ATLAS did" has to be a real readable list, not a claim (§5.3)."""
    session, tenant, written = pg
    inv = _invoice(session, written, tenant)
    client = _client(session, tenant, role="Admin")
    client.post(
        f"/api/v1/atlas/lines/audit-approve-{inv.id}/act",
        json={"kind": "resolve_invoice", "target_id": str(inv.id), "params": {"status": "PAID"}},
    )

    body = client.get("/api/v1/atlas/actions").json()
    assert len(body["entries"]) == 1
    entry = body["entries"][0]
    assert entry["kind"] == "resolve_invoice"
    assert entry["succeeded"] is True
    assert entry["performed_at"]


def test_the_action_log_is_tenant_scoped(pg, pg_session):
    """A record of writes, tenant-wide by §2.2 — and no wider."""
    session, tenant, written = pg
    other = Tenant(name=f"other-{unique_tag()}", domain=f"other-{unique_tag()}.test")
    session.add(other)
    session.commit()
    session.refresh(other)
    try:
        inv = _invoice(session, written, tenant)
        _client(session, tenant, role="Admin").post(
            f"/api/v1/atlas/lines/audit-approve-{inv.id}/act",
            json={
                "kind": "resolve_invoice",
                "target_id": str(inv.id),
                "params": {"status": "PAID"},
            },
        )
        app.dependency_overrides.clear()
        body = _client(session, other, role="Admin").get("/api/v1/atlas/actions").json()
        assert body["entries"] == []
    finally:
        app.dependency_overrides.clear()
        session.delete(other)
        session.commit()
