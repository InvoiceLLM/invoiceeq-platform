"""Feature 35 (ATLAS Intelligence) task 35.6 — the briefing cache, on real Postgres.

Spec: `docs/feature_35_atlas_intelligence.md` §3.1 steps 2/7/8 · §4 · §6 (task
35.6's row) · §8 ruling 4.

Real Postgres only (hard rule 2), through `tests/atlas_pg.py` -- and here that
is not ceremony: the thing under test is a **unique constraint** and a JSONB
round trip, neither of which SQLite would enforce or store the same way.

What is asserted, and why each one is here
------------------------------------------
1. **The migration is applied.** `alembic current` is checked by the run, but a
   table that exists and a table the ORM can write are different facts; the
   first test writes a row through `AtlasBriefing` and reads it back.
2. **One briefing per person per day**, enforced by the database. `store()`
   upserts, and the constraint is what makes that safe when two tabs open at
   once. The test inserts a colliding row directly and asserts the database
   refuses it -- if the check lived only in `store()`, this test would pass with
   the constraint dropped.
3. **The user is part of the key.** An Auditor's briefing and an Admin's are
   different documents about the same day, written against different tool lists.
4. **`invalidate()` sets `stale` and nothing else** -- it does not delete, does
   not regenerate, and returns whether it changed anything.
5. **A replay reproduces the frames that were streamed**, including a
   `truncated` frame and including its position (first, per the track-2 ordering
   decision) -- and it reproduces them from the stored data, not from the run.
"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa

from models import AtlasBriefing, Tenant
from services.atlas_briefing_cache import (
    get_cached,
    invalidate,
    replay_events,
    store,
)
from services.atlas_contract import BriefingEvent
from services.atlas_tools import BriefingRun
from tests.atlas_pg import open_session, postgres_only, unique_tag

TODAY = date(2026, 9, 20)


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
    tenant = Tenant(name=f"atlas-cache-{tag}", domain=f"atlas-cache-{tag}.test")
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


def _run(tenant, user_id="user-a", **fields) -> BriefingRun:
    run = BriefingRun(tenant_id=tenant.id, user_id=user_id)
    run.model = fields.pop("model", "gpt-5.6-terra")
    run.tokens_in = fields.pop("tokens_in", 1200)
    run.tokens_out = fields.pop("tokens_out", 300)
    run.cost_usd = fields.pop("cost_usd", 0.0126)
    run.tool_calls = fields.pop(
        "tool_calls", [{"tool": "list_lines", "args": {}, "ms": 41, "rows": 3, "refused": None}]
    )
    run.dropped = fields.pop("dropped", 1)
    run.truncated = fields.pop("truncated", None)
    assert not fields, f"unexpected fields {sorted(fields)}"
    return run


def _events(*, question=False, truncated=None):
    out = []
    if truncated:
        out.append(BriefingEvent(type="truncated", data={"reason": truncated}))
    out.append(
        BriefingEvent(
            type="paragraph",
            data={
                "text": "Two invoices are waiting on you.",
                "citations": [
                    {"tool": "list_lines", "record_kind": "recommendation", "record_id": "audit-approve-1"}
                ],
            },
        )
    )
    if question:
        out.append(
            BriefingEvent(
                type="question",
                data={
                    "text": "Does this vendor always bill monthly?",
                    "citations": [
                        {"tool": "memory_rules", "record_kind": "rule", "record_id": "rule-1"}
                    ],
                    "answer_kind": "free_text",
                },
            )
        )
    # An `error` frame is deliberately in the list and must not be stored: only
    # paragraphs and the question are replayable.
    out.append(BriefingEvent(type="error", data={"message": "ignored"}))
    return out


# ═════════════════════════════════════════════════════════════════════════════
# 1. The row, and the migration behind it
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_a_stored_briefing_round_trips_every_field(pg):
    """§4's columns, written by `store()` and read back by `get_cached()`."""
    session, tenant, written = pg
    run = _run(tenant)
    row = store(session, run, _events(question=True), today=TODAY)
    written.append(row)

    fetched = get_cached(session, tenant.id, "user-a", TODAY)
    assert fetched is not None
    assert fetched.id == row.id
    assert fetched.model == "gpt-5.6-terra"
    assert fetched.tokens_in == 1200 and fetched.tokens_out == 300
    assert fetched.cost_usd == pytest.approx(0.0126)
    assert fetched.dropped == 1
    assert fetched.truncated == ""
    assert fetched.stale is False
    # JSONB, not a string: the citations survive as structure.
    assert fetched.paragraphs[0]["citations"][0]["record_id"] == "audit-approve-1"
    assert fetched.question["answer_kind"] == "free_text"
    assert fetched.tool_calls[0]["tool"] == "list_lines"


@postgres_only
def test_only_the_streamed_frames_are_stored(pg):
    """An `error` frame is not a paragraph, and a cache may not invent one."""
    session, tenant, written = pg
    row = store(session, _run(tenant), _events(), today=TODAY)
    written.append(row)

    assert len(row.paragraphs) == 1
    assert row.question is None
    assert all("message" not in p for p in row.paragraphs)


@postgres_only
def test_a_second_briefing_the_same_day_replaces_the_first_row(pg):
    """§3.1 step 8: a regeneration is the same day's briefing, rewritten."""
    session, tenant, written = pg
    first = store(session, _run(tenant), _events(), today=TODAY)
    written.append(first)
    created_at = first.created_at

    second = store(
        session, _run(tenant, model="gpt-5.6-terra", dropped=0), _events(question=True), today=TODAY
    )
    assert second.id == first.id, "a regeneration reuses the day's row"
    assert second.created_at == created_at
    assert second.question is not None
    assert second.dropped == 0

    rows = session.exec(
        sa.select(AtlasBriefing).where(AtlasBriefing.tenant_id == tenant.id)
    ).all()
    assert len(rows) == 1


@postgres_only
def test_the_database_itself_refuses_two_briefings_for_one_person_and_day(pg):
    """The constraint, not `store()`, is what makes two open tabs safe.

    Asserted by inserting the collision **directly**, so this test still fails if
    the guard were moved into application code and the constraint dropped.
    """
    session, tenant, written = pg
    row = store(session, _run(tenant), _events(), today=TODAY)
    written.append(row)

    session.add(
        AtlasBriefing(tenant_id=tenant.id, user_id="user-a", briefing_date=TODAY)
    )
    with pytest.raises(sa.exc.IntegrityError):
        session.commit()
    session.rollback()


@postgres_only
def test_two_users_in_one_tenant_get_two_briefings(pg):
    """The briefing is written against the caller's grants and tool list.

    Sharing a row per tenant would show one role the evidence another role was
    allowed to see -- `visible_to()`'s rule, broken through a cache.
    """
    session, tenant, written = pg
    written.append(store(session, _run(tenant, user_id="user-a"), _events(), today=TODAY))
    written.append(store(session, _run(tenant, user_id="user-b"), _events(), today=TODAY))

    assert get_cached(session, tenant.id, "user-a", TODAY).id != get_cached(
        session, tenant.id, "user-b", TODAY
    ).id


@postgres_only
def test_yesterdays_briefing_is_not_todays(pg):
    session, tenant, written = pg
    written.append(store(session, _run(tenant), _events(), today=TODAY - timedelta(days=1)))
    assert get_cached(session, tenant.id, "user-a", TODAY) is None


# ═════════════════════════════════════════════════════════════════════════════
# 2. Invalidation (§8 ruling 4)
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_invalidate_sets_stale_and_does_not_delete(pg):
    session, tenant, written = pg
    row = store(session, _run(tenant), _events(), today=TODAY)
    written.append(row)

    assert invalidate(session, tenant.id, "user-a", today=TODAY) is True
    session.refresh(row)
    assert row.stale is True
    # The row survives: it is still the cost record and the caps sample (§3.6).
    assert get_cached(session, tenant.id, "user-a", TODAY) is not None
    assert row.cost_usd > 0 and row.tool_calls


@postgres_only
def test_invalidate_is_idempotent_and_reports_whether_it_did_anything(pg):
    session, tenant, written = pg
    row = store(session, _run(tenant), _events(), today=TODAY)
    written.append(row)

    assert invalidate(session, tenant.id, "user-a", today=TODAY) is True
    assert invalidate(session, tenant.id, "user-a", today=TODAY) is False
    # Nothing to invalidate is the ordinary case, not an error.
    assert invalidate(session, tenant.id, "nobody", today=TODAY) is False


@postgres_only
def test_invalidating_one_user_does_not_touch_another(pg):
    session, tenant, written = pg
    written.append(store(session, _run(tenant, user_id="user-a"), _events(), today=TODAY))
    b = store(session, _run(tenant, user_id="user-b"), _events(), today=TODAY)
    written.append(b)

    invalidate(session, tenant.id, "user-a", today=TODAY)
    session.refresh(b)
    assert b.stale is False


@postgres_only
def test_storing_again_clears_stale(pg):
    """The regeneration path writes over the row that caused it."""
    session, tenant, written = pg
    row = store(session, _run(tenant), _events(), today=TODAY)
    written.append(row)
    invalidate(session, tenant.id, "user-a", today=TODAY)

    again = store(session, _run(tenant), _events(), today=TODAY)
    assert again.stale is False


# ═════════════════════════════════════════════════════════════════════════════
# 3. Replay
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_a_replay_reproduces_the_frames_that_were_streamed(pg):
    session, tenant, written = pg
    row = store(session, _run(tenant), _events(question=True), today=TODAY)
    written.append(row)

    frames = list(replay_events(row))
    assert [f.type for f in frames] == ["paragraph", "question"]
    assert frames[0].data["citations"][0]["record_id"] == "audit-approve-1"
    assert frames[1].data["text"].endswith("?")
    # `done` is the route's, never the cache's: only the route knows `cached`.
    assert "done" not in {f.type for f in frames}


@postgres_only
def test_a_truncated_briefing_replays_its_truncation_first(pg):
    """Track 2's ordering decision holds on the cached path too: a reader learns
    the briefing is partial before reading it, not after."""
    session, tenant, written = pg
    row = store(
        session,
        _run(tenant, truncated="wall_clock"),
        _events(truncated="wall_clock"),
        today=TODAY,
    )
    written.append(row)

    frames = list(replay_events(row))
    assert frames[0].type == "truncated"
    assert frames[0].data["reason"] == "wall_clock"


@postgres_only
def test_a_replay_carries_nothing_a_guard_dropped(pg):
    """The cache cannot be a way round `validate_briefing_paragraph()`.

    `store()` only ever sees the frames the route yielded, and the guards ran
    before that. Asserted by storing a run whose `dropped` count is non-zero and
    checking the stored paragraphs are only the ones that were streamed.
    """
    session, tenant, written = pg
    row = store(session, _run(tenant, dropped=4), _events(), today=TODAY)
    written.append(row)

    assert row.dropped == 4
    assert len(row.paragraphs) == 1
    assert len(list(replay_events(row))) == 1
