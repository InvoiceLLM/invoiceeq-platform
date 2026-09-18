"""Feature 34 / tasks 34.10, 34.12 and 34.14 — memory, cold start, "you missed this".

Spec: `docs/feature_34_atlas.md` §7.1 (D24, D25) · §7.2 (D31, bounded by D40) ·
§5.2 Q13 (D34) · D12's noise pruning.

Real Postgres only (hard rule 2) — `tests/atlas_pg.py` is the guard, and it
**fails rather than skips** on a configured-but-unreachable database (BE Gap
697).

What is asserted, and why each one is here
------------------------------------------
1. **A rule can be read, changed and deleted** (§7.2). All three, because the
   promise is all three: a lesson that can be read and not removed is still one
   that haunts the system.
2. **Delete is a hard delete.** The founder's rule, and §7.2's reason agrees —
   a soft-deleted lesson is exactly a lesson that cannot be found. Asserted by
   counting rows, not by reading a flag.
3. **D40's boundary holds**: no emitter module imports the memory store, so a
   derived vendor baseline cannot quietly become a stored belief. Asserted
   grep-shaped, because nothing would fail if it did.
4. **D12 suggests and never writes** (§5.3, "never learns a permanent rule from
   one instance"). The suggestion appears; the rules table stays empty.
5. **A reported miss becomes a readable lesson, in the user's own words**
   (D34) — the sentence is copied, not paraphrased, because it is the evidence
   ATLAS was wrong.
6. **The cold start says what ATLAS cannot do yet** (§7.1 part 3). That sentence
   is the one that turns a weak first month from a broken product into an honest
   one, and it is the one most likely to be quietly dropped.
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
from models import AtlasDismissal, AtlasMemoryRule, AtlasMissedReport, Invoice, Tenant
from services.atlas_capabilities import GrantSet
from services.atlas_memory import (
    ID_FAMILIES,
    NOISE_THRESHOLD,
    RuleSource,
    add_rule,
    delete_rule,
    edit_rule,
    family_of,
    list_rules,
    noise_suggestions,
    report_missed,
)
from services.atlas_orientation import orientation
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
    tag = unique_tag()
    tenant = Tenant(name=f"atlas-mem-{tag}", domain=f"atlas-mem-{tag}.test")
    pg_session.add(tenant)
    pg_session.commit()
    pg_session.refresh(tenant)
    written: list = []
    try:
        yield pg_session, tenant, written
    finally:
        pg_session.rollback()
        for model in (AtlasMissedReport, AtlasMemoryRule, AtlasDismissal):
            for row in pg_session.exec(
                select(model).where(model.tenant_id == tenant.id)
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


def _client(session, tenant, *, role: str = "Admin", user_id: str = "clerk-admin", **grants):
    context = TenantContext(
        tenant_id=tenant.id,
        user_id=user_id,
        role=role,
        billing_plan="active",
        can_audit=grants.pop("can_audit", True),
        can_train=grants.pop("can_train", True),
        can_load=grants.pop("can_load", True),
    )
    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[get_tenant_context] = lambda: context
    return TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# 34.10 — the rules, read, changed, removed
# ─────────────────────────────────────────────────────────────────────────────

def test_a_lesson_can_be_read_changed_and_deleted(pg):
    """§7.2's promise, all three parts of it."""
    session, tenant, _ = pg
    client = _client(session, tenant)

    created = client.post("/api/v1/atlas/memory", json={"text": "Kumar bills quarterly, not monthly."})
    assert created.status_code == 201, created.text
    rule_id = created.json()["id"]
    assert created.json()["source"] == RuleSource.TOLD

    listed = client.get("/api/v1/atlas/memory").json()
    assert [r["text"] for r in listed["rules"]] == ["Kumar bills quarterly, not monthly."]

    edited = client.patch(f"/api/v1/atlas/memory/{rule_id}", json={"text": "Kumar bills quarterly."})
    assert edited.status_code == 200
    assert edited.json()["text"] == "Kumar bills quarterly."

    assert client.delete(f"/api/v1/atlas/memory/{rule_id}").status_code == 204
    assert client.get("/api/v1/atlas/memory").json()["rules"] == []


def test_delete_removes_the_row(pg):
    """A hard delete. Counted in the table, not read off a flag: a soft-deleted
    lesson is precisely the lesson §7.2 says haunts the system."""
    session, tenant, _ = pg
    rule = add_rule(session, tenant.id, "u1", text="Something wrong")
    assert delete_rule(session, tenant.id, rule.id) is True
    remaining = session.exec(
        select(AtlasMemoryRule).where(AtlasMemoryRule.tenant_id == tenant.id)
    ).all()
    assert remaining == []


def test_switching_a_rule_off_is_not_deleting_it(pg):
    """`active=False` keeps what it said, and keeps it findable."""
    session, tenant, _ = pg
    rule = add_rule(session, tenant.id, "u1", text="Ignore freight lines under a rupee")
    edit_rule(session, tenant.id, rule.id, active=False)

    still_there = list_rules(session, tenant.id)
    assert len(still_there) == 1
    assert still_there[0].active is False
    assert list_rules(session, tenant.id, include_inactive=False) == []


def test_a_rule_is_scoped_to_its_tenant(pg):
    session, tenant, _ = pg
    other = Tenant(name=f"other-{unique_tag()}", domain=f"other-{unique_tag()}.test")
    session.add(other)
    session.commit()
    session.refresh(other)
    try:
        rule = add_rule(session, tenant.id, "u1", text="Ours")
        assert edit_rule(session, other.id, rule.id, text="Theirs") is None
        assert delete_rule(session, other.id, rule.id) is False
    finally:
        session.delete(other)
        session.commit()


def test_a_rule_must_say_something(pg):
    session, tenant, _ = pg
    with pytest.raises(ValueError):
        add_rule(session, tenant.id, "u1", text="   ")


def test_no_emitter_writes_to_the_memory_store(pg):
    """D40's boundary, and it is invisible: nothing would fail if a vendor
    baseline were written here, so it is asserted grep-shaped.

    A derived observation that became a stored belief would outlive the invoices
    that produced it, which is the exact failure D39/D40 were ruled to prevent.
    """
    root = Path(__file__).resolve().parents[1] / "services"
    for name in ("atlas_skills.py", "atlas_doubt.py", "atlas_recon.py", "atlas_forecast.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "atlas_memory" not in text, f"{name} reaches into the memory store"


# ─────────────────────────────────────────────────────────────────────────────
# D12 — noise pruning suggests, and never writes
# ─────────────────────────────────────────────────────────────────────────────

def test_every_emitted_id_prefix_has_a_family(pg):
    """A registry, not a parse — and one with no holes.

    The tail of a recommendation id is a UUID, which is full of hyphens, so
    splitting on them cannot find where the family ends. This is what keeps D12's
    sentence from naming a family it made up.
    """
    root = Path(__file__).resolve().parents[1] / "services"
    prefixes: set[str] = set()
    for name in ("atlas_skills.py", "atlas_doubt.py", "atlas_recon.py", "atlas_forecast.py"):
        text = (root / name).read_text(encoding="utf-8")
        for raw in re.findall(r'id=f"([^"]+)"', text):
            # Everything up to the first interpolation is the fixed prefix.
            prefixes.add(raw.split("{", 1)[0])
    assert prefixes
    for prefix in prefixes:
        assert family_of(f"{prefix}x") is not None, f"no family covers {prefix!r}"


def test_a_repeatedly_dismissed_family_produces_a_suggestion_and_no_rule(pg):
    """§5.3: one dismissal is noise, forty are a pattern — and even forty are a
    pattern a person gets the last word on."""
    session, tenant, _ = pg
    for i in range(NOISE_THRESHOLD):
        session.add(
            AtlasDismissal(
                tenant_id=tenant.id,
                user_id=f"u{i % 3}",
                recommendation_id=f"train-lowconf-{uuid4()}",
            )
        )
    session.commit()

    suggestions = noise_suggestions(session, tenant.id)
    assert len(suggestions) == 1
    assert suggestions[0].family == "train-lowconf-"
    assert suggestions[0].count == NOISE_THRESHOLD
    assert ID_FAMILIES["train-lowconf-"] in suggestions[0].text
    # It suggested. It did not learn.
    assert list_rules(session, tenant.id) == []


def test_below_the_threshold_nothing_is_suggested(pg):
    session, tenant, _ = pg
    for _ in range(3):
        session.add(
            AtlasDismissal(
                tenant_id=tenant.id,
                user_id="u1",
                recommendation_id=f"train-lowconf-{uuid4()}",
            )
        )
    session.commit()
    assert noise_suggestions(session, tenant.id) == []


def test_an_unknown_id_family_is_counted_into_nothing(pg):
    """Inventing "you have dismissed `weird-prefix-` 40 times" would be a
    suggestion the user cannot evaluate."""
    session, tenant, _ = pg
    for _ in range(NOISE_THRESHOLD + 5):
        session.add(
            AtlasDismissal(
                tenant_id=tenant.id,
                user_id="u1",
                recommendation_id=f"something-nobody-emits-{uuid4()}",
            )
        )
    session.commit()
    assert noise_suggestions(session, tenant.id) == []


# ─────────────────────────────────────────────────────────────────────────────
# 34.14 — "you missed this"
# ─────────────────────────────────────────────────────────────────────────────

def test_a_reported_miss_becomes_a_readable_lesson_in_the_users_words(pg):
    """D34. The sentence is the evidence ATLAS was wrong; paraphrasing it would
    be the system editing its own report card."""
    session, tenant, _ = pg
    client = _client(session, tenant)

    said = "You did not flag that Kumar billed us twice for the same delivery note."
    created = client.post(
        "/api/v1/atlas/missed",
        json={"entity_kind": "invoice", "entity_id": str(uuid4()), "description": said},
    )
    assert created.status_code == 201, created.text
    rule = created.json()["rule"]
    assert said in rule["text"]
    assert rule["source"] == RuleSource.MISSED_REPORT

    # And it is in the memory a user can go and read, edit or delete.
    listed = client.get("/api/v1/atlas/memory").json()
    assert any(said in r["text"] for r in listed["rules"])


def test_a_miss_can_be_reported_by_any_grant_holder(pg):
    """Deliberately not capability-gated: a miss is noticed by whoever happens
    to be looking, and gating it would suppress exactly the evidence §5.2 says
    is already invisible."""
    session, tenant, _ = pg
    client = _client(
        session, tenant, role="Loader", can_audit=False, can_train=False, can_load=True
    )
    res = client.post(
        "/api/v1/atlas/missed",
        json={"entity_kind": "invoice", "entity_id": str(uuid4()), "description": "Missed a duplicate."},
    )
    assert res.status_code == 201


def test_a_report_has_to_say_what_was_missed(pg):
    session, tenant, _ = pg
    client = _client(session, tenant)
    res = client.post(
        "/api/v1/atlas/missed",
        json={"entity_kind": "invoice", "entity_id": str(uuid4()), "description": "   "},
    )
    assert res.status_code == 422


def test_deleting_the_lesson_does_not_delete_the_evidence(pg):
    """`rule_id` is not a foreign key, on purpose: a user may remove a wrong
    lesson, and removing it must not take the record that ATLAS missed something
    with it."""
    session, tenant, _ = pg
    report, rule = report_missed(
        session,
        tenant.id,
        "u1",
        entity_kind="invoice",
        entity_id=str(uuid4()),
        description="Missed a duplicate.",
    )
    assert delete_rule(session, tenant.id, rule.id) is True
    session.expire_all()
    assert session.get(AtlasMissedReport, report.id) is not None


# ─────────────────────────────────────────────────────────────────────────────
# 34.12 — cold start
# ─────────────────────────────────────────────────────────────────────────────

def test_the_orientation_says_what_atlas_cannot_do_yet(pg):
    """§7.1 part 3 — a stated plan, not a disappointment, and the part most
    likely to be quietly dropped."""
    session, tenant, _ = pg
    result = orientation(session, tenant.id, GrantSet(can_audit=True))
    bodies = {part.key: part.body for part in result.parts}
    assert set(bodies) == {"your_job", "how_to_verify", "what_i_will_learn"}
    assert "I do not know your vendors" in bodies["what_i_will_learn"]
    assert "In a month" in bodies["what_i_will_learn"]


def test_the_orientation_is_needed_only_while_there_is_no_history(pg):
    """D25: teach once, then keep teaching in place. Not an onboarding flag —
    "has this workspace seen an invoice" is the fact that actually decides
    whether the explanation is still true."""
    session, tenant, written = pg
    assert orientation(session, tenant.id, GrantSet(can_audit=True)).needed is True

    inv = Invoice(
        tenant_id=tenant.id,
        file_path=f"tests/{uuid4().hex}.pdf",
        status="AUDIT_REQUIRED",
        flow_direction="INBOUND",
        currency="INR",
        invoice_number=uuid4().hex[:6].upper(),
        vendor_name="Kumar Supplies",
        grand_total=1000.0,
        due_date=TODAY + timedelta(days=5),
    )
    session.add(inv)
    session.commit()
    written.append(inv)

    assert orientation(session, tenant.id, GrantSet(can_audit=True)).needed is False


def test_an_ungranted_user_gets_no_orientation(pg):
    """D3's empty state already says the true thing. Explaining the work they
    cannot do would be describing a product they have no access to."""
    session, tenant, _ = pg
    result = orientation(session, tenant.id, GrantSet())
    assert result.needed is False
    assert result.parts == []


def test_grants_stack_into_one_orientation(pg):
    """§2.1: `can_audit` + `can_load` is one merged list, not tabs — and the
    orientation reads the way the screen does."""
    session, tenant, _ = pg
    result = orientation(session, tenant.id, GrantSet(can_audit=True, can_load=True))
    job = next(p for p in result.parts if p.key == "your_job").body
    assert "approve or reject" in job
    assert "did not load" in job


def test_the_orientation_reaches_the_wire_with_its_day_one_findings(pg):
    """"Comprehension, not findings" must not read as "nothing until next
    month" — §7.1 lists real work that needs no history at all."""
    session, tenant, _ = pg
    body = _client(session, tenant).get("/api/v1/atlas/orientation").json()
    assert body["needed"] is True
    assert len(body["parts"]) == 3
    assert body["day_one_finds"]
    # The historical import is an offer and says so, never a gate.
    assert "offer, not a step" in body["historical_import_offer"]
