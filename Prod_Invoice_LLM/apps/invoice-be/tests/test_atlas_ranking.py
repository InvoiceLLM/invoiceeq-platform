"""Feature 34 / tasks 34.7f and 34.7g — ranking, and collapse by area.

Spec: `docs/feature_34_atlas.md` §7.3 (D30), §2.2 (D20), §13.1 Q5 (D41) · §17.

Real Postgres only (hard rule 2) for anything touching the wire —
`tests/atlas_pg.py` is the guard, and it **fails rather than skips** on a
configured-but-unreachable database (BE Gap 697). The pure-arithmetic tests at
the top need no database, and are not given one: a test that stands up Postgres
to sort a list in memory is a test that will eventually be skipped for being
slow.

What is asserted, and why each one is here
------------------------------------------
1. **A larger, sooner-expiring item outranks a smaller, later one.** D30's own
   example, as a test.
2. **Ranking is arithmetic, not an opinion** (hard rule 3). The same input on
   the same day produces the same order, asserted over a shuffled input rather
   than claimed in a docstring.
3. **Nothing below the cut is unreachable** (D30, "ATLAS ranks; it does not
   hide"). The response body is asserted to contain every line, cut or not.
4. **A collapsed area carries its count and its aging figure and opens in
   place** — `line_ids` point into the same payload's `lines`, which is what
   makes "openable" a client-side expansion rather than a second request.
5. **A solo owner collapses nothing.** Not special-cased in the code, so
   asserted as behaviour.
6. **A non-Admin gets no area rows at all.** They see only their own work;
   a summary row above it would be noise, and worse, would imply somebody else
   is handling something.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from dependencies import TenantContext, get_db_session, get_tenant_context
from main import app
from models import AtlasActionLog, AtlasDismissal, Invoice, Tenant, User
from services.atlas_capabilities import AtlasCapability, GrantSet
from services.atlas_collapse import (
    COLLAPSE_THRESHOLD,
    UNTOUCHED_DAYS,
    WORKING_WITHIN_DAYS,
    capabilities_worked_by_others,
    collapse,
)
from services.atlas_contract import (
    Action,
    Recommendation,
    Verify,
    What,
    Why,
)
from services.atlas_ranking import RANK_CUT, days_left, rank, rank_score
from tests.atlas_pg import open_session, unique_tag

TODAY = date(2026, 9, 18)


def _line(
    line_id: str,
    *,
    stake: str | None = None,
    fixable_until: date | None = None,
    since: date | None = None,
    capability: AtlasCapability = AtlasCapability.AUDIT,
    entity_kind: str = "invoice",
    entity_id: str | None = None,
) -> Recommendation:
    """A minimal valid line. Only the ranking inputs vary between cases."""
    return Recommendation(
        id=line_id,
        capability=capability,
        skill="test_skill",
        what=What(
            headline="A thing",
            entity_kind=entity_kind,
            entity_id=entity_id or line_id,
        ),
        why=Why(text="Because of a reason with no numbers in it."),
        action=Action(kind="open_field_review", label="Look", target_id=line_id),
        verify=Verify(question="Is this right?"),
        stake=Decimal(stake) if stake is not None else None,
        fixable_until=fixable_until,
        since=since,
        currency="INR",
    )


# ─────────────────────────────────────────────────────────────────────────────
# 34.7f — the arithmetic
# ─────────────────────────────────────────────────────────────────────────────

def test_bigger_and_sooner_beats_smaller_and_later():
    """D30's own example: a large duplicate before tomorrow's payment run beats
    a small one from last month."""
    urgent = _line("big-soon", stake="240000", fixable_until=TODAY + timedelta(days=1))
    stale = _line("small-late", stake="4000", fixable_until=TODAY + timedelta(days=40))
    assert [line.id for line in rank([stale, urgent], TODAY)] == ["big-soon", "small-late"]


def test_the_same_money_sooner_ranks_higher():
    """The deadline is the whole second term, so hold the money still."""
    soon = _line("soon", stake="50000", fixable_until=TODAY + timedelta(days=2))
    later = _line("later", stake="50000", fixable_until=TODAY + timedelta(days=30))
    assert [line.id for line in rank([later, soon], TODAY)] == ["soon", "later"]


def test_an_overdue_line_is_maximally_urgent_not_negatively_urgent():
    """A missed deadline does not make the money stop mattering — `days_left` is
    floored at zero rather than going negative and sorting below everything."""
    overdue = _line("overdue", stake="10000", fixable_until=TODAY - timedelta(days=30))
    today_due = _line("today", stake="10000", fixable_until=TODAY)
    assert days_left(overdue, TODAY) == 0
    assert rank_score(overdue, TODAY) == rank_score(today_due, TODAY)


def test_no_deadline_ranks_as_far_off_never_as_urgent():
    """Inventing urgency for a line that stated none would make the ordering
    mean less every time an emitter forgot the field."""
    undated = _line("undated", stake="100000")
    dated = _line("dated", stake="100000", fixable_until=TODAY + timedelta(days=1))
    assert [line.id for line in rank([undated, dated], TODAY)] == ["dated", "undated"]
    assert days_left(undated, TODAY) > 30


def test_a_line_with_no_stake_sorts_below_one_with_money():
    moneyless = _line("moneyless", fixable_until=TODAY)
    small = _line("small", stake="1", fixable_until=TODAY + timedelta(days=60))
    assert [line.id for line in rank([moneyless, small], TODAY)] == ["small", "moneyless"]


def test_ranking_is_deterministic_and_total():
    """Hard rule 3. Same lines, same day, same order — including for two lines
    that are identical on both ranking terms, where the id breaks the tie."""
    twins = [
        _line("b-twin", stake="1000", fixable_until=TODAY),
        _line("a-twin", stake="1000", fixable_until=TODAY),
    ]
    first = [line.id for line in rank(twins, TODAY)]
    second = [line.id for line in rank(list(reversed(twins)), TODAY)]
    assert first == second == ["a-twin", "b-twin"]


def test_rank_returns_every_line_it_was_given():
    """"ATLAS ranks; it does not hide" (D30), asserted on the function before it
    is asserted on the wire."""
    lines = [_line(f"line-{i}", stake=str(i * 1000)) for i in range(RANK_CUT + 5)]
    assert len(rank(lines, TODAY)) == len(lines)
    assert {line.id for line in rank(lines, TODAY)} == {line.id for line in lines}


# ─────────────────────────────────────────────────────────────────────────────
# 34.7g — collapse, as pure logic
# ─────────────────────────────────────────────────────────────────────────────

ADMIN = GrantSet(can_audit=True, can_train=True, can_load=True, is_admin=True)
TRAINER = GrantSet(can_train=True)


def test_a_non_admin_gets_no_area_rows():
    lines = [_line(f"t-{i}", capability=AtlasCapability.TRAIN) for i in range(40)]
    assert collapse(lines, TRAINER, held_by_others={AtlasCapability.TRAIN}, today=TODAY) == []


def test_a_solo_owner_collapses_nothing():
    """Not special-cased in the code: with no other grant-holder and a small
    list there is simply no reason to collapse."""
    lines = [_line(f"t-{i}", capability=AtlasCapability.TRAIN) for i in range(3)]
    assert collapse(lines, ADMIN, held_by_others=set(), today=TODAY) == []


def test_another_grant_holder_collapses_the_area_with_its_aging_figure():
    """§2.2: "Corrections — 34 pending, 3 untouched for a week"."""
    old = TODAY - timedelta(days=UNTOUCHED_DAYS + 1)
    lines = [
        _line("t-1", capability=AtlasCapability.TRAIN, since=old),
        _line("t-2", capability=AtlasCapability.TRAIN, since=old),
        _line("t-3", capability=AtlasCapability.TRAIN, since=TODAY),
    ]
    rows = collapse(lines, ADMIN, held_by_others={AtlasCapability.TRAIN}, today=TODAY)
    assert len(rows) == 1
    row = rows[0]
    assert row.label == "Corrections"
    assert row.count == 3
    assert row.untouched == 2
    assert row.line_ids == ["t-1", "t-2", "t-3"]
    assert "3 pending" in row.headline and "2 untouched for a week" in row.headline


def test_a_line_of_unknown_age_is_not_counted_as_fresh():
    """"I do not know how old this is" and "this is fresh" are different facts."""
    lines = [_line("t-1", capability=AtlasCapability.TRAIN)]
    row = collapse(lines, ADMIN, held_by_others={AtlasCapability.TRAIN}, today=TODAY)[0]
    assert row.untouched == 0
    assert row.age_unknown == 1
    assert "unknown age" in row.headline


def test_volume_alone_collapses_an_area_with_nobody_else_working_it():
    """D41: §7.3's volume threshold reuses this mechanism rather than inventing
    a queue mode."""
    lines = [
        _line(f"t-{i}", capability=AtlasCapability.TRAIN)
        for i in range(COLLAPSE_THRESHOLD)
    ]
    rows = collapse(lines, ADMIN, held_by_others=set(), today=TODAY)
    assert len(rows) == 1
    assert rows[0].reason == "there is a lot of it"


def test_an_area_counts_work_not_lines():
    """**The defect real data found (2026-09-18).** "Decisions — 5 pending" on a
    tenant with two invoices awaiting a decision: two approve lines, two doubt
    asks about *the same two invoices*, and the cash tile. Two invoices is two
    pieces of work, and that is the sentence a person acts on."""
    lines = [
        _line("audit-approve-a", entity_id="inv-a"),
        _line("doubt-rate-a", entity_id="inv-a"),
        _line("audit-approve-b", entity_id="inv-b"),
        _line("doubt-rate-b", entity_id="inv-b"),
    ]
    row = collapse(lines, ADMIN, held_by_others={AtlasCapability.AUDIT}, today=TODAY)[0]
    assert row.count == 2
    assert "2 pending" in row.headline
    # Every line is still reachable by opening the row: the count is about the
    # sentence, not about what the row contains.
    assert len(row.line_ids) == 4


def test_the_cash_tile_is_not_a_decision_and_is_not_in_the_area():
    """`audit-cash-INR` declares `AUDIT` (D44), so grouping by capability alone
    swept a standing position into the decisions queue and counted it as a fifth
    decision. A tenant-level line is not work, is never collapsed, and stays in
    the plain list where the Admin can always see it (§2.2, "nothing withheld").
    """
    lines = [
        _line("audit-approve-a", entity_id="inv-a"),
        _line("doubt-rate-a", entity_id="inv-a"),
        _line("audit-approve-b", entity_id="inv-b"),
        _line("doubt-rate-b", entity_id="inv-b"),
        _line("audit-cash-INR", entity_kind="tenant", entity_id="tenant-1"),
    ]
    row = collapse(lines, ADMIN, held_by_others={AtlasCapability.AUDIT}, today=TODAY)[0]
    assert row.count == 2
    assert "audit-cash-INR" not in row.line_ids


def test_an_area_of_only_tiles_does_not_collapse_at_all():
    """There is no work in it to fold up, and a row saying "Decisions — 0
    pending" above a cash position is worse than no row."""
    lines = [
        _line(f"audit-cash-{c}", entity_kind="tenant", entity_id="tenant-1")
        for c in ("INR", "USD")
    ]
    assert collapse(lines, ADMIN, held_by_others={AtlasCapability.AUDIT}, today=TODAY) == []


def test_a_subject_is_aged_by_its_oldest_line_not_by_each_line():
    """One invoice with a week-old approve line and a fresh doubt ask is one
    piece of work, a week old — not "1 untouched, 1 of unknown age"."""
    old = TODAY - timedelta(days=UNTOUCHED_DAYS + 1)
    lines = [
        _line("audit-approve-a", entity_id="inv-a", since=old),
        _line("doubt-rate-a", entity_id="inv-a"),
    ]
    row = collapse(lines, ADMIN, held_by_others={AtlasCapability.AUDIT}, today=TODAY)[0]
    assert (row.count, row.untouched, row.age_unknown) == (1, 1, 0)


def test_the_volume_threshold_counts_work_too():
    """D41's threshold is about how much there is to do. Counting lines would
    collapse an area the moment ATLAS had two things to say about six invoices."""
    lines = [
        _line(f"audit-approve-{i}", entity_id=f"inv-{i}")
        for i in range(COLLAPSE_THRESHOLD - 1)
    ] + [
        _line(f"doubt-rate-{i}", entity_id=f"inv-{i}")
        for i in range(COLLAPSE_THRESHOLD - 1)
    ]
    assert collapse(lines, ADMIN, held_by_others=set(), today=TODAY) == []


def test_the_admins_own_position_is_never_collapsed_away_from_them():
    """§2.2's "nothing withheld". The cash position is not somebody else's work."""
    lines = [
        _line(f"a-{i}", capability=AtlasCapability.ADMIN)
        for i in range(COLLAPSE_THRESHOLD + 5)
    ]
    assert collapse(lines, ADMIN, held_by_others=set(), today=TODAY) == []


# ─────────────────────────────────────────────────────────────────────────────
# On the wire, against real Postgres
# ─────────────────────────────────────────────────────────────────────────────

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
    tenant = Tenant(name=f"atlas-rank-{tag}", domain=f"atlas-rank-{tag}.test")
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


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def _client(session, tenant, *, role: str = "Admin", user_id: str = "clerk-admin"):
    context = TenantContext(
        tenant_id=tenant.id,
        user_id=user_id,
        role=role,
        billing_plan="active",
        can_audit=True,
        can_train=True,
        can_load=True,
    )
    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[get_tenant_context] = lambda: context
    return TestClient(app)


def _invoice(session, written, tenant, *, total: float, due_in: int) -> Invoice:
    inv = Invoice(
        tenant_id=tenant.id,
        file_path=f"tests/{uuid4().hex}.pdf",
        status="AUDIT_REQUIRED",
        flow_direction="INBOUND",
        currency="INR",
        invoice_number=uuid4().hex[:6].upper(),
        vendor_name="Kumar Supplies",
        grand_total=total,
        due_date=date.today() + timedelta(days=due_in),
    )
    session.add(inv)
    session.commit()
    session.refresh(inv)
    written.append(inv)
    return inv


def test_the_wire_is_ranked_and_carries_the_cut(pg):
    """The big-and-soon invoice arrives above the small-and-late one, and the
    payload says where the fold is without truncating anything."""
    session, tenant, written = pg
    small_late = _invoice(session, written, tenant, total=4000.0, due_in=60)
    big_soon = _invoice(session, written, tenant, total=240000.0, due_in=1)

    body = _client(session, tenant).get("/api/v1/atlas/lines").json()
    approvals = [
        line["id"] for line in body["lines"] if line["skill"] == "invoice_awaiting_decision"
    ]
    assert approvals.index(f"audit-approve-{big_soon.id}") < approvals.index(
        f"audit-approve-{small_late.id}"
    )
    assert body["rank_cut"] == RANK_CUT


def test_nothing_below_the_cut_is_missing_from_the_payload(pg):
    """D30. Every invoice that has a line has it *in the response*, however far
    down it ranks — the cut is a display hint, not a `LIMIT`."""
    session, tenant, written = pg
    made = [
        _invoice(session, written, tenant, total=1000.0 * (i + 1), due_in=i + 1)
        for i in range(RANK_CUT + 3)
    ]
    body = _client(session, tenant).get("/api/v1/atlas/lines").json()
    ids = {line["id"] for line in body["lines"]}
    assert len(body["lines"]) > body["rank_cut"]
    for inv in made:
        assert f"audit-approve-{inv.id}" in ids


def test_an_area_row_opens_in_place(pg):
    """Its `line_ids` are ids of lines in this same payload — which is what makes
    expanding it a client-side act rather than another request."""
    session, tenant, written = pg
    for i in range(COLLAPSE_THRESHOLD):
        _invoice(session, written, tenant, total=1000.0, due_in=i + 1)

    body = _client(session, tenant).get("/api/v1/atlas/lines").json()
    assert body["areas"], "an Admin over the volume threshold should see an area row"
    ids = {line["id"] for line in body["lines"]}
    for area in body["areas"]:
        # `count` is pieces of work and `line_ids` is every line about them, so
        # the count is a bound rather than an equality — ATLAS may have two
        # things to say about one invoice.
        assert 0 < area["count"] <= len(area["line_ids"])
        assert set(area["line_ids"]) <= ids
        assert area["headline"].strip()


def test_a_colleague_who_merely_holds_the_grant_is_not_working_it(pg):
    """**The defect real data found (2026-09-18).**

    The old predicate was `capabilities_held_by_others()`: it returned a
    capability whenever any other *user row* held the grant, so a workspace whose
    owner was the only person actually working printed "someone else is working
    this" on every area. D20 is about work in progress, not about permissions.

    A colleague row exists here, with `can_train` granted, and has touched
    nothing. The answer must be empty.
    """
    session, tenant, _ = pg
    tag = unique_tag()
    them = User(
        tenant_id=tenant.id,
        email=f"trainer-{tag}@x.test",
        role="Trainer",
        clerk_user_id=f"clerk-trainer-{tag}",
        can_train=True,
    )
    session.add(them)
    session.commit()
    try:
        assert (
            capabilities_worked_by_others(
                session,
                tenant.id,
                exclude_user_id=f"clerk-admin-{tag}",
                line_ids_by_capability={AtlasCapability.TRAIN: ["train-lowconf-x"]},
            )
            == set()
        )
    finally:
        session.delete(them)
        session.commit()


@pytest.mark.parametrize("via", ["action", "dismissal"])
def test_a_colleague_who_touched_a_line_is_working_that_area(pg, via):
    """What "actively working" means with the evidence this product actually has:
    a write in `atlas_action_log`, or a dismissal, by another user, on a line
    currently in that area."""
    session, tenant, _ = pg
    tag = unique_tag()
    line_id = f"train-lowconf-{tag}"
    if via == "action":
        row = AtlasActionLog(
            tenant_id=tenant.id,
            user_id=f"clerk-trainer-{tag}",
            recommendation_id=line_id,
            action_kind="open_field_review",
            target_id=tag,
            succeeded=True,
            summary="Opened.",
        )
    else:
        row = AtlasDismissal(
            tenant_id=tenant.id,
            user_id=f"clerk-trainer-{tag}",
            recommendation_id=line_id,
        )
    session.add(row)
    session.commit()
    try:
        worked = capabilities_worked_by_others(
            session,
            tenant.id,
            exclude_user_id=f"clerk-admin-{tag}",
            line_ids_by_capability={AtlasCapability.TRAIN: [line_id]},
        )
        assert worked == {AtlasCapability.TRAIN}
        # The caller's own work is never somebody else's work.
        assert (
            capabilities_worked_by_others(
                session,
                tenant.id,
                exclude_user_id=f"clerk-trainer-{tag}",
                line_ids_by_capability={AtlasCapability.TRAIN: [line_id]},
            )
            == set()
        )
    finally:
        session.delete(row)
        session.commit()


def test_work_a_colleague_touched_long_ago_is_not_being_worked_now(pg):
    """"Actively" is a word with a span in it. An action from last month is a
    record of what happened, not a colleague who has this in hand."""
    session, tenant, _ = pg
    tag = unique_tag()
    line_id = f"train-lowconf-{tag}"
    row = AtlasActionLog(
        tenant_id=tenant.id,
        user_id=f"clerk-trainer-{tag}",
        recommendation_id=line_id,
        action_kind="open_field_review",
        target_id=tag,
        succeeded=True,
        summary="Opened.",
        performed_at=datetime.utcnow() - timedelta(days=WORKING_WITHIN_DAYS + 1),
    )
    session.add(row)
    session.commit()
    try:
        assert (
            capabilities_worked_by_others(
                session,
                tenant.id,
                exclude_user_id=f"clerk-admin-{tag}",
                line_ids_by_capability={AtlasCapability.TRAIN: [line_id]},
            )
            == set()
        )
    finally:
        session.delete(row)
        session.commit()


def test_a_solo_tenant_collapses_nothing_on_the_wire(pg):
    """The bar from the screen, not from the payload: with one person working,
    **no area row exists at all**, so nothing on the Admin's screen can say
    "someone else is working this"."""
    session, tenant, written = pg
    for i in range(3):
        _invoice(session, written, tenant, total=1000.0, due_in=i + 1)

    body = _client(session, tenant).get("/api/v1/atlas/lines").json()
    assert [area["reason"] for area in body["areas"]] == []
