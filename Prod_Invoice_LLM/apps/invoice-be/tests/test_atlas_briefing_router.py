"""Feature 35 (ATLAS Intelligence) tasks 35.7–35.9 — the briefing over HTTP.

Spec: `docs/feature_35_atlas_intelligence.md` §3.1, §3.3, §3.5, §6 (rows 35.7,
35.8, 35.9).

Real Postgres (hard rule 2, BE Gap 697) and a **scripted mock model** — nothing
here calls Azure. The model is injected by replacing `routers.atlas.get_llm_for_role`
with a counting factory, which does two jobs at once: it keeps Terra out of the
test, and the count *is* the assertion for §6's "cold tenant ... mock call count
0; first call runs, count 1; second call replays, count still 1". A cache tested
by reading the cache would pass with the cache bypassed.

What is asserted, and why each one is here
------------------------------------------
1. **The cold tenant costs nothing.** §3.5: a welcome, no citations, and — the
   part that is easy to get wrong — **no model call and no stored row**. A
   stored welcome would make a cold tenant look briefed.
2. **An ungranted caller gets the same treatment**, before the history query.
   D3's rule, reaching the briefing the same way it reaches `GET /atlas/lines`.
3. **The frames are §3.3's frames.** Named SSE events (`event: paragraph`), not
   bare `data:` lines: FE Feature 24 dispatches on the name.
4. **Second open, same day, same person: no second run.** And a different user
   in the same tenant *does* run again, because the briefing is written against
   that caller's grants.
5. **Dismiss, act, memory add and the interview answer each make the next open
   re-run** (§3.1 step 8, task 35.8). Asserted through the real endpoints, on
   the `stale` column, not by calling `invalidate()` directly.
6. **A failure is contained.** An SSE response's headers are on the wire before
   the first frame, so an exception mid-stream is a truncated briefing rather
   than a 500. The route emits `error` then `done` and closes.
"""

from __future__ import annotations

import json
import random
import string
from dataclasses import replace
from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import routers.atlas as atlas_router
from dependencies import TenantContext, get_db_session, get_tenant_context
from main import app
from sqlmodel import select as sm_select

from models import (
    AtlasActionLog,
    AtlasBriefing,
    AtlasDismissal,
    AtlasMemoryRule,
    Invoice,
    Tenant,
)
from services.atlas_briefing_cache import get_cached
from services.atlas_memory import RuleSource
from services.atlas_tools import TOOL_REGISTRY
from tests.atlas_pg import open_session, postgres_only, unique_tag
from utils.llm import MockInvoiceLLM

TODAY = date.today()

#: A row a scripted paragraph can legitimately cite: one id, one rendered figure.
#: Same shape `tests/test_atlas_agent.py` uses, and for the same reason — a
#: paragraph can only be *correctly* cited if the test knows an id the run
#: emitted.
_RULE_ROW = {
    "record_kind": "rule",
    "record_id": "rule-briefing-1",
    "text": "This vendor bills monthly.",
    "rendered": "12,500.00",
}


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════

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
    tenant = Tenant(name=f"atlas-brief-{tag}", domain=f"atlas-brief-{tag}.test")
    pg_session.add(tenant)
    pg_session.commit()
    pg_session.refresh(tenant)
    written: list = []
    try:
        yield pg_session, tenant, written
    finally:
        pg_session.rollback()
        # Swept by table rather than by the `written` list, because these tests
        # drive the **real** endpoints: a dismiss writes an `atlas_dismissals`
        # row and an act writes an `atlas_action_logs` row that no test held a
        # reference to, and a tenant with children cannot be deleted.
        for model in (
            AtlasBriefing, AtlasDismissal, AtlasActionLog, AtlasMemoryRule, Invoice,
        ):
            for row in pg_session.exec(
                sm_select(model).where(model.tenant_id == tenant.id)
            ).all():
                pg_session.delete(row)
        pg_session.commit()
        pg_session.delete(tenant)
        pg_session.commit()


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


class _Factory:
    """Stands in for `get_llm_for_role`, and counts how often it was asked.

    One call to this factory is one briefing run: the route builds the model
    immediately before `run_briefing()` and nowhere else, so the count is the
    number of times the tenant paid for a briefing.
    """

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0
        self.roles: list[str] = []

    def __call__(self, role, *args, **kwargs):
        self.calls += 1
        self.roles.append(role)
        return MockInvoiceLLM(tool_script=list(self.script))


def _install_model(monkeypatch, script) -> _Factory:
    factory = _Factory(script)
    monkeypatch.setattr(atlas_router, "get_llm_for_role", factory)
    return factory


def _client(session, tenant, *, user_id=None, role="Admin", **grants) -> TestClient:
    context = TenantContext(
        tenant_id=tenant.id,
        user_id=user_id or f"user_{uuid4().hex[:8]}",
        role=role,
        billing_plan="active",
        can_audit=grants.pop("can_audit", False),
        can_train=grants.pop("can_train", False),
        can_load=grants.pop("can_load", False),
    )
    app.dependency_overrides[get_db_session] = lambda: session
    app.dependency_overrides[get_tenant_context] = lambda: context
    return TestClient(app)


def _letters(n: int = 6) -> str:
    return "".join(random.choice(string.ascii_lowercase) for _ in range(n))


def _seed(session, written, tenant) -> Invoice:
    """Enough history that `tenant_has_history()` is true and the tools find rows."""
    inv = Invoice(
        tenant_id=tenant.id,
        file_path=f"tests/{uuid4().hex}.pdf",
        status="AUDIT_REQUIRED",
        flow_direction="INBOUND",
        currency="INR",
        vendor_name="Vendor " + _letters(),
        invoice_number=uuid4().hex[:8],
        grand_total=50000.0,
        due_date=TODAY + timedelta(days=4),
    )
    session.add(inv)
    session.commit()
    session.refresh(inv)
    written.append(inv)
    return inv


def _stub_rows(tenant, rows):
    def adapter(ctx, args):
        return [
            dict(row, tenant_id=str(tenant.id), as_of=ctx.skill.today.isoformat())
            for row in rows
        ]

    return adapter


def _swap(monkeypatch, tenant, name, rows):
    monkeypatch.setitem(
        TOOL_REGISTRY, name, replace(TOOL_REGISTRY[name], adapter=_stub_rows(tenant, rows))
    )


def _answer(paragraphs, question=None) -> str:
    payload: dict = {"paragraphs": paragraphs}
    if question is not None:
        payload["question"] = question
    return json.dumps(payload)


def _cite(record_id=_RULE_ROW["record_id"], tool="memory_rules", kind="rule") -> dict:
    return {"tool": tool, "record_kind": kind, "record_id": record_id}


#: The ordinary script: call one tool, then write one cited paragraph. The
#: paragraph states 12,500.00, which `_RULE_ROW` rendered, so it survives the
#: number guard rather than being dropped.
_GOOD_SCRIPT = [
    [{"name": "memory_rules", "args": {}}],
    _answer(
        [
            {
                "text": "One standing rule is in force and its figure is 12,500.00.",
                "citations": [_cite()],
            }
        ]
    ),
]


def _frames(response) -> list[tuple[str, dict]]:
    """The SSE body, parsed into `(event, data)` pairs.

    Parsed rather than string-matched: §3.3 defines named events and the FE
    dispatches on the name, so a test that only checked the body contained some
    text would pass on a stream with no `event:` lines at all.
    """
    out: list[tuple[str, dict]] = []
    for block in response.text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        kind = ""
        data = "{}"
        for line in block.splitlines():
            if line.startswith("event: "):
                kind = line[len("event: "):].strip()
            elif line.startswith("data: "):
                data = line[len("data: "):]
        out.append((kind, json.loads(data)))
    return out


def _types(response) -> list[str]:
    return [kind for kind, _ in _frames(response)]


def _last(response, kind):
    return [data for k, data in _frames(response) if k == kind][-1]


# ═════════════════════════════════════════════════════════════════════════════
# 1. The cold paths — no model, no row (§3.5)
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_a_cold_tenant_gets_a_welcome_and_no_model_is_called(pg, monkeypatch):
    session, tenant, written = pg
    factory = _install_model(monkeypatch, _GOOD_SCRIPT)
    client = _client(session, tenant, role="Admin", can_audit=True)

    res = client.get("/api/v1/atlas/briefing")

    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    assert _types(res) == ["welcome", "done"]
    assert factory.calls == 0, "a welcome costs nothing"
    assert _last(res, "done")["cached"] is False


@postgres_only
def test_the_welcome_is_the_one_for_the_callers_role(pg, monkeypatch):
    """§3.5: four roles, four welcomes. The Admin's is not the Trainer's."""
    session, tenant, written = pg
    _install_model(monkeypatch, _GOOD_SCRIPT)

    admin = _client(session, tenant, role="Admin", can_audit=True).get(
        "/api/v1/atlas/briefing"
    )
    trainer = _client(session, tenant, role="Trainer", can_train=True).get(
        "/api/v1/atlas/briefing"
    )

    assert _last(admin, "welcome")["role"] == "admin"
    assert _last(trainer, "welcome")["role"] == "trainer"
    assert _last(admin, "welcome")["text"] != _last(trainer, "welcome")["text"]
    # No citations on either: a welcome makes no claim about this tenant.
    assert "citations" not in _last(admin, "welcome")


@postgres_only
def test_an_ungranted_caller_gets_a_welcome_not_a_briefing(pg, monkeypatch):
    """D3, reaching the briefing the way it reaches `GET /atlas/lines`."""
    session, tenant, written = pg
    _seed(session, written, tenant)
    factory = _install_model(monkeypatch, _GOOD_SCRIPT)
    client = _client(session, tenant, role="Viewer")

    res = client.get("/api/v1/atlas/briefing")

    assert _types(res) == ["welcome", "done"]
    assert _last(res, "welcome")["role"] == "user"
    assert factory.calls == 0


@postgres_only
def test_a_welcome_is_never_stored(pg, monkeypatch):
    """A stored welcome would make a cold tenant look briefed."""
    session, tenant, written = pg
    _install_model(monkeypatch, _GOOD_SCRIPT)
    client = _client(session, tenant, role="Admin", can_audit=True)

    client.get("/api/v1/atlas/briefing")

    assert session.exec(
        sm_select(AtlasBriefing).where(AtlasBriefing.tenant_id == tenant.id)
    ).all() == []


# ═════════════════════════════════════════════════════════════════════════════
# 2. A real run, and the cache (§3.1 steps 2, 3, 7)
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_a_warm_tenant_runs_once_and_the_run_is_stored(pg, monkeypatch):
    session, tenant, written = pg
    _seed(session, written, tenant)
    _swap(monkeypatch, tenant, "memory_rules", [_RULE_ROW])
    factory = _install_model(monkeypatch, _GOOD_SCRIPT)
    client = _client(session, tenant, user_id="user-a", role="Admin", can_audit=True)

    res = client.get("/api/v1/atlas/briefing")

    assert factory.calls == 1
    assert factory.roles == ["atlas"], "§3.4: every ATLAS Intelligence call is Terra's role"
    assert _types(res)[-1] == "done"
    assert "paragraph" in _types(res)
    assert _last(res, "done")["cached"] is False

    row = get_cached(session, tenant.id, "user-a", TODAY)
    assert row is not None
    written.append(row)
    assert row.stale is False
    assert len(row.paragraphs) == 1
    assert row.paragraphs[0]["citations"][0]["record_id"] == _RULE_ROW["record_id"]
    assert row.tool_calls, "the dispatch log is what §8 ruling 2's caps get measured from"


@postgres_only
def test_a_second_open_the_same_day_replays_without_a_second_run(pg, monkeypatch):
    session, tenant, written = pg
    _seed(session, written, tenant)
    _swap(monkeypatch, tenant, "memory_rules", [_RULE_ROW])
    factory = _install_model(monkeypatch, _GOOD_SCRIPT)
    client = _client(session, tenant, user_id="user-a", role="Admin", can_audit=True)

    first = client.get("/api/v1/atlas/briefing")
    second = client.get("/api/v1/atlas/briefing")
    written.append(get_cached(session, tenant.id, "user-a", TODAY))

    assert factory.calls == 1, "the second open must not pay for a second briefing"
    assert _last(second, "done")["cached"] is True
    # The replay is the same briefing, not a similar one.
    assert [d for k, d in _frames(second) if k == "paragraph"] == [
        d for k, d in _frames(first) if k == "paragraph"
    ]


@postgres_only
def test_a_different_user_in_the_same_tenant_gets_their_own_run(pg, monkeypatch):
    """The briefing is written against the caller's grants and tool list."""
    session, tenant, written = pg
    _seed(session, written, tenant)
    _swap(monkeypatch, tenant, "memory_rules", [_RULE_ROW])
    factory = _install_model(monkeypatch, _GOOD_SCRIPT)

    _client(session, tenant, user_id="user-a", role="Admin", can_audit=True).get(
        "/api/v1/atlas/briefing"
    )
    _client(session, tenant, user_id="user-b", role="Auditor", can_audit=True).get(
        "/api/v1/atlas/briefing"
    )
    for uid in ("user-a", "user-b"):
        written.append(get_cached(session, tenant.id, uid, TODAY))

    assert factory.calls == 2


@postgres_only
def test_the_frames_are_named_events_in_the_spec_shape(pg, monkeypatch):
    """§3.3. FE Feature 24 dispatches on the event name, not on the payload."""
    session, tenant, written = pg
    _seed(session, written, tenant)
    _swap(monkeypatch, tenant, "memory_rules", [_RULE_ROW])
    _install_model(monkeypatch, _GOOD_SCRIPT)
    client = _client(session, tenant, user_id="user-a", role="Admin", can_audit=True)

    res = client.get("/api/v1/atlas/briefing")
    written.append(get_cached(session, tenant.id, "user-a", TODAY))

    assert "event: paragraph\ndata: {" in res.text
    body = _last(res, "done")
    assert set(body) == {"cached", "model", "dropped_paragraphs"}
    paragraph = [d for k, d in _frames(res) if k == "paragraph"][0]
    assert paragraph["citations"] and paragraph["text"]


@postgres_only
def test_an_uncited_paragraph_never_reaches_the_wire_and_is_counted(pg, monkeypatch):
    """The 35.5 guard, asserted at the HTTP boundary rather than in the loop."""
    session, tenant, written = pg
    _seed(session, written, tenant)
    _swap(monkeypatch, tenant, "memory_rules", [_RULE_ROW])
    script = [
        [{"name": "memory_rules", "args": {}}],
        _answer(
            [
                {"text": "Everything looks fine to me.", "citations": []},
                {"text": "One rule is in force at 12,500.00.", "citations": [_cite()]},
            ]
        ),
    ]
    _install_model(monkeypatch, script)
    client = _client(session, tenant, user_id="user-a", role="Admin", can_audit=True)

    res = client.get("/api/v1/atlas/briefing")
    row = get_cached(session, tenant.id, "user-a", TODAY)
    written.append(row)

    texts = [d["text"] for k, d in _frames(res) if k == "paragraph"]
    assert texts == ["One rule is in force at 12,500.00."]
    assert _last(res, "done")["dropped_paragraphs"] == 1
    # And the cache cannot resurrect it on the next open.
    assert len(row.paragraphs) == 1


# ═════════════════════════════════════════════════════════════════════════════
# 3. Invalidation through the real endpoints (task 35.8)
# ═════════════════════════════════════════════════════════════════════════════

def _brief_once(session, tenant, monkeypatch, written, user_id="user-a"):
    _swap(monkeypatch, tenant, "memory_rules", [_RULE_ROW])
    factory = _install_model(monkeypatch, _GOOD_SCRIPT)
    client = _client(session, tenant, user_id=user_id, role="Admin", can_audit=True)
    client.get("/api/v1/atlas/briefing")
    row = get_cached(session, tenant.id, user_id, TODAY)
    written.append(row)
    return client, factory, row


@postgres_only
def test_dismissing_a_line_makes_the_next_open_re_run(pg, monkeypatch):
    session, tenant, written = pg
    inv = _seed(session, written, tenant)
    client, factory, row = _brief_once(session, tenant, monkeypatch, written)

    res = client.post(f"/api/v1/atlas/lines/audit-approve-{inv.id}/dismiss")
    assert res.status_code == 200
    session.refresh(row)
    assert row.stale is True

    client.get("/api/v1/atlas/briefing")
    assert factory.calls == 2


@postgres_only
def test_acting_on_a_line_makes_the_next_open_re_run(pg, monkeypatch):
    session, tenant, written = pg
    inv = _seed(session, written, tenant)
    client, factory, row = _brief_once(session, tenant, monkeypatch, written)

    res = client.post(
        f"/api/v1/atlas/lines/audit-approve-{inv.id}/act",
        json={"kind": "resolve_invoice", "target_id": str(inv.id), "params": {"status": "PAID"}},
    )
    assert res.status_code == 200, res.text
    session.refresh(row)
    assert row.stale is True

    client.get("/api/v1/atlas/briefing")
    assert factory.calls == 2


@postgres_only
def test_adding_a_memory_rule_makes_the_next_open_re_run(pg, monkeypatch):
    """Memory rules go into the briefing's prompt, so a new one dates it."""
    session, tenant, written = pg
    _seed(session, written, tenant)
    client, factory, row = _brief_once(session, tenant, monkeypatch, written)

    res = client.post("/api/v1/atlas/memory", json={"text": "Never chase Kumar in March."})
    assert res.status_code == 201
    written.append(session.get(AtlasMemoryRule, uuid_of(res)))
    session.refresh(row)
    assert row.stale is True

    client.get("/api/v1/atlas/briefing")
    assert factory.calls == 2


def uuid_of(response):
    from uuid import UUID as _UUID

    return _UUID(response.json()["id"])


# ═════════════════════════════════════════════════════════════════════════════
# 4. The interview answer (task 35.9)
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_answering_the_question_writes_an_interview_rule_and_dates_the_briefing(
    pg, monkeypatch
):
    session, tenant, written = pg
    _seed(session, written, tenant)
    client, factory, row = _brief_once(session, tenant, monkeypatch, written)

    res = client.post(
        "/api/v1/atlas/briefing/answer",
        json={
            "question_text": "Does this vendor always bill monthly?",
            "answer": "Yes, on the last working day.",
        },
    )

    assert res.status_code == 201, res.text
    body = res.json()
    assert body["source"] == RuleSource.INTERVIEW == "interview"
    # Neither half is paraphrased: the question and the answer are both in it.
    assert "always bill monthly" in body["text"]
    assert "last working day" in body["text"]
    written.append(session.get(AtlasMemoryRule, uuid_of(res)))

    session.refresh(row)
    assert row.stale is True
    client.get("/api/v1/atlas/briefing")
    assert factory.calls == 2


@postgres_only
def test_an_interview_rule_is_readable_on_the_memory_endpoint(pg, monkeypatch):
    """§7.2: a lesson that cannot be found cannot be corrected. An interview
    answer is a lesson like any other and shows up beside the ones people gave."""
    session, tenant, written = pg
    _install_model(monkeypatch, _GOOD_SCRIPT)
    client = _client(session, tenant, user_id="user-a", role="Admin", can_audit=True)

    created = client.post(
        "/api/v1/atlas/briefing/answer",
        json={"question_text": "Is freight ever billed separately?", "answer": "No."},
    )
    written.append(session.get(AtlasMemoryRule, uuid_of(created)))

    rules = client.get("/api/v1/atlas/memory").json()["rules"]
    assert [r["source"] for r in rules] == ["interview"]


@postgres_only
def test_an_empty_answer_is_refused(pg, monkeypatch):
    session, tenant, written = pg
    _install_model(monkeypatch, _GOOD_SCRIPT)
    client = _client(session, tenant, role="Admin", can_audit=True)

    res = client.post(
        "/api/v1/atlas/briefing/answer",
        json={"question_text": "Anything?", "answer": ""},
    )
    assert res.status_code == 422


@postgres_only
def test_the_one_question_streams_and_is_cached_with_the_briefing(pg, monkeypatch):
    """§3.1 step 6 / §6's 35.9 row: one question, cited, on the wire and in the row.

    The second question in the same answer is dropped and counted -- from the
    user's side an extra question that never arrives is the same event as a
    dropped paragraph, which is why both land on `dropped_paragraphs`.
    """
    session, tenant, written = pg
    _seed(session, written, tenant)
    _swap(monkeypatch, tenant, "memory_rules", [_RULE_ROW])
    script = [
        [{"name": "memory_rules", "args": {}}],
        _answer(
            [{"text": "One rule is in force at 12,500.00.", "citations": [_cite()]}],
            question=[
                {"text": "Does this vendor always bill monthly?", "citations": [_cite()]},
                {"text": "And do they ever bill freight separately?", "citations": [_cite()]},
            ],
        ),
    ]
    _install_model(monkeypatch, script)
    client = _client(session, tenant, user_id="user-a", role="Admin", can_audit=True)

    res = client.get("/api/v1/atlas/briefing")
    row = get_cached(session, tenant.id, "user-a", TODAY)
    written.append(row)

    questions = [d for k, d in _frames(res) if k == "question"]
    assert len(questions) == 1
    assert questions[0]["text"].startswith("Does this vendor")
    assert questions[0]["citations"][0]["record_id"] == _RULE_ROW["record_id"]
    assert _last(res, "done")["dropped_paragraphs"] == 1

    # And the replay asks the same question rather than a new one.
    assert row.question["text"] == questions[0]["text"]
    replayed = client.get("/api/v1/atlas/briefing")
    assert _last(replayed, "done")["cached"] is True
    assert [d["text"] for k, d in _frames(replayed) if k == "question"] == [
        questions[0]["text"]
    ]


# ═════════════════════════════════════════════════════════════════════════════
# 5. Failure is contained to the briefing panel
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_a_model_that_raises_yields_error_then_done(pg, monkeypatch):
    """The headers are on the wire before the first frame, so a raise after that
    point is a truncated stream and not a 500. §3.3 has an `error` event for
    exactly this, and the stream must still close with `done`."""
    session, tenant, written = pg
    _seed(session, written, tenant)

    class _Exploding:
        def __call__(self, role, *args, **kwargs):
            return self

        def bind_tools(self, tools, **kwargs):
            raise RuntimeError("Terra is unreachable")

    monkeypatch.setattr(atlas_router, "get_llm_for_role", _Exploding())
    client = _client(session, tenant, user_id="user-a", role="Admin", can_audit=True)

    res = client.get("/api/v1/atlas/briefing")

    assert res.status_code == 200
    assert _types(res) == ["error", "done"]
    assert "Terra is unreachable" in _last(res, "error")["message"]
    # Nothing is stored for a run that produced nothing.
    assert get_cached(session, tenant.id, "user-a", TODAY) is None


@postgres_only
def test_a_tool_that_raises_does_not_end_the_briefing(pg, monkeypatch):
    """A raising adapter is a refusal row (§9.3 deviation 6), not an exception.

    The loop keeps going, the surviving paragraph still reaches the wire, and
    nothing about the refusal is citable.
    """
    session, tenant, written = pg
    _seed(session, written, tenant)

    def exploding(ctx, args):
        raise RuntimeError("the vendor baseline service fell over")

    monkeypatch.setitem(
        TOOL_REGISTRY,
        "memory_rules",
        replace(TOOL_REGISTRY["memory_rules"], adapter=exploding),
    )
    # A second, working tool so the run still has evidence to cite. Not
    # `orientation`: orientation is background, and a paragraph resting only on
    # it is dropped by design (§3.2).
    _swap(monkeypatch, tenant, "action_log", [_RULE_ROW])
    script = [
        [{"name": "memory_rules", "args": {}}, {"name": "action_log", "args": {}}],
        _answer(
            [
                {
                    "text": "One rule is in force at 12,500.00.",
                    "citations": [_cite(tool="action_log", kind="rule")],
                }
            ]
        ),
    ]
    _install_model(monkeypatch, script)
    client = _client(session, tenant, user_id="user-a", role="Admin", can_audit=True)

    res = client.get("/api/v1/atlas/briefing")
    written.append(get_cached(session, tenant.id, "user-a", TODAY))

    assert _types(res)[-1] == "done"
    assert "paragraph" in _types(res)
    assert "error" not in _types(res)


# ═════════════════════════════════════════════════════════════════════════════
# 6. The role ladder the route and the agent must agree on
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
@pytest.mark.parametrize(
    "grants_kwargs,expected",
    [
        ({"is_admin": True, "can_audit": True, "can_train": True, "can_load": True}, "admin"),
        ({"can_audit": True}, "auditor"),
        ({"can_train": True}, "trainer"),
        ({"can_load": True}, "loader"),
        ({}, "user"),
    ],
)
def test_the_route_and_the_agent_name_the_same_role(grants_kwargs, expected):
    """`routers.atlas._briefing_role()` duplicates `agents.atlas_agent._role_from()`
    deliberately (the welcome path must not need the agent module). This is the
    test that keeps the duplicate honest."""
    from agents.atlas_agent import _role_from
    from services.atlas_capabilities import GrantSet

    grants = GrantSet(**grants_kwargs)
    assert atlas_router._briefing_role(grants) == expected
    assert _role_from(grants) == expected


# ═════════════════════════════════════════════════════════════════════════════
# 7. BE Gap 719 — a grant change dates the briefing too
#
# Driven through the **real** Admin endpoint rather than by calling
# `invalidate()`, for the reason section 3 above gives: what is under test is
# that the write site calls it, and a test that called it itself would pass with
# the call deleted from the router.
#
# The `users` rows are cleaned up by the test rather than by the fixture, which
# sweeps only the five ATLAS tables: a `users` row left behind holds a foreign
# key on the tenant and the fixture's own teardown would fail on it.
# ═════════════════════════════════════════════════════════════════════════════

def _user(session, tenant, clerk_user_id: str, **fields):
    from models import User

    row = User(
        tenant_id=tenant.id,
        email=f"{clerk_user_id}-{uuid4().hex[:8]}@example.test",
        clerk_user_id=clerk_user_id,
        role=fields.pop("role", "Trainer"),
        **fields,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _drop_users(session, tenant):
    from models import User

    for row in session.exec(sm_select(User).where(User.tenant_id == tenant.id)).all():
        session.delete(row)
    session.commit()


@postgres_only
def test_changing_a_users_permissions_makes_their_next_open_re_run(pg, monkeypatch):
    """BE Gap 719: the briefing was written against the grants they held then.

    The tool schema, the pre-fetch and the role word all come from the
    `GrantSet`, so a Trainer who has just been given `can_audit` would otherwise
    read a Trainer-shaped briefing for the rest of the day.
    """
    session, tenant, written = pg
    _seed(session, written, tenant)
    client, factory, row = _brief_once(session, tenant, monkeypatch, written, user_id="user-a")
    assert row.stale is False

    target = _user(session, tenant, "user-a")
    try:
        res = client.put(
            f"/api/v1/admin/users/{target.id}/permissions",
            json={
                "can_train": True,
                "can_audit": True,
                "can_load": False,
                "can_send_invoices": False,
            },
        )
        assert res.status_code == 200, res.text

        session.refresh(row)
        assert row.stale is True

        client.get("/api/v1/atlas/briefing")
        assert factory.calls == 2
    finally:
        _drop_users(session, tenant)


@postgres_only
def test_removing_a_user_dates_the_briefing_they_were_reading(pg, monkeypatch):
    """The second write site in the same router: a removed user holds nothing.

    Briefed as `user-b`, removed by `user-a` — the endpoint refuses to remove
    the caller's own account, so the two identities are necessarily different.
    """
    session, tenant, written = pg
    _seed(session, written, tenant)
    _client_b, _factory, row = _brief_once(
        session, tenant, monkeypatch, written, user_id="user-b"
    )

    target = _user(session, tenant, "user-b", can_audit=True)
    try:
        admin = _client(session, tenant, user_id="user-a", role="Admin", can_audit=True)
        res = admin.delete(f"/api/v1/admin/users/{target.id}")
        assert res.status_code == 200, res.text

        session.refresh(row)
        assert row.stale is True
    finally:
        _drop_users(session, tenant)
