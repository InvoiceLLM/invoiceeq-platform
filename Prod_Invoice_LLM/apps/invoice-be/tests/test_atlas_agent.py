"""Feature 35 (ATLAS Intelligence) task 35.4 — the briefing loop, on real Postgres.

Spec: `docs/feature_35_atlas_intelligence.md` §3.1, §3.3, §6 (task 35.4's row).

What is under test is the loop's *control* behaviour, not a fixture's prose:
where it stops, what it records, and what it refuses to pass on. Every
assertion is therefore a property of the loop (it ran six rounds; it dispatched
twelve calls; the set it built equals the set the tools emitted) rather than an
expectation about any tenant's data, which is Feature 34's business.

The model is `MockInvoiceLLM` with a script (task 35.2), so no test here calls
Azure. The database is real Postgres (hard rule 2, BE Gap 697): the tools these
rounds dispatch read it, and a loop tested against stubbed tools would prove
nothing about the thing that actually runs.

Two tests swap one registry adapter for a stub (`dataclasses.replace` on the
`ToolSpec`, the seam task 35.1's docstring names). That is deliberate and
narrow: a wall clock cannot be tripped by a fast tool, and a paragraph cannot be
*correctly* cited unless the test knows an id the run emitted. Everything else
runs the real adapters.
"""

from __future__ import annotations

import json
import random
import string
import time
from dataclasses import replace
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest

from models import Invoice, Tenant
import agents.atlas_agent as atlas_agent
from agents.atlas_agent import run_briefing
from agents.atlas_prompts import WELCOME_BY_ROLE, briefing_user_prompt, welcome_for
from services.atlas_capabilities import GrantSet
from services.atlas_skills import SkillContext
from services.atlas_tools import (
    TOOL_REGISTRY,
    BriefingRun,
    ToolContext,
    run_tool,
)
from tests.atlas_pg import open_session, postgres_only, unique_tag
from utils.llm import MockInvoiceLLM

TODAY = date(2026, 9, 18)

ADMIN = GrantSet(can_audit=True, can_train=True, can_load=True, is_admin=True)
TRAINER = GrantSet(can_train=True)

_NO_ARGS: dict = {}


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures — the same shape as tests/test_atlas_tools.py
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
    tenant = Tenant(name=f"atlas-agent-{tag}", domain=f"atlas-agent-{tag}.test")
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


def _ctx(session, tenant, grants: GrantSet = ADMIN) -> ToolContext:
    return ToolContext(
        db=session,
        skill=SkillContext(
            tenant_id=tenant.id, today=TODAY, now=datetime(2026, 9, 18, 9, 0, 0)
        ),
        grants=grants,
        user_id="user-" + uuid4().hex[:8],
    )


def _letters(n: int = 6) -> str:
    """A unique suffix with **no digits in it**.

    Not cosmetic: a vendor named `Vendor c35553` puts an undeclared numeric token
    into a line's headline and `validate_recommendation()` rejects the line — the
    fixture would be testing the line-level guard instead of this loop.
    """
    return "".join(random.choice(string.ascii_lowercase) for _ in range(n))


def _seed(session, written, tenant) -> Invoice:
    """Two payables and a receivable — enough that the real tools return rows."""
    vendor = "Vendor " + _letters()
    first = Invoice(
        tenant_id=tenant.id, file_path=f"tests/{uuid4().hex}.pdf",
        status="AUDIT_REQUIRED", flow_direction="INBOUND", currency="INR",
        vendor_name=vendor, invoice_number=uuid4().hex[:8],
        grand_total=50000.0, due_date=TODAY + timedelta(days=4),
    )
    second = Invoice(
        tenant_id=tenant.id, file_path=f"tests/{uuid4().hex}.pdf",
        status="AUDIT_REQUIRED", flow_direction="INBOUND", currency="INR",
        vendor_name=vendor, invoice_number=uuid4().hex[:8],
        grand_total=60000.0, due_date=TODAY + timedelta(days=9),
    )
    for row in (first, second):
        session.add(row)
        written.append(row)
    session.commit()
    session.refresh(first)
    return first


class _Recorder:
    """A model whose bound object the test can inspect.

    `run_briefing()` binds the model itself, so a test that only passed a
    `MockInvoiceLLM` could never see how many rounds were invoked. This records
    the bound mock on the way through and changes nothing else.
    """

    def __init__(self, script):
        self.mock = MockInvoiceLLM(tool_script=list(script))
        self.bound = None

    def bind_tools(self, tools, **kwargs):
        self.bound = self.mock.bind_tools(tools, **kwargs)
        return self.bound


def _events(session, ctx, script, run=None, **kwargs):
    """Run one briefing to exhaustion and return its events and its run."""
    run = run or BriefingRun(tenant_id=ctx.skill.tenant_id, user_id=ctx.user_id)
    recorder = _Recorder(script)
    events = list(
        run_briefing(session, ctx, today=TODAY, llm=recorder, run=run, **kwargs)
    )
    return events, run, recorder


def _of_type(events, kind):
    return [e for e in events if e.type == kind]


def _answer(paragraphs, question=None):
    """The JSON object §3.3 asks the model for, as one script step."""
    payload: dict = {"paragraphs": paragraphs}
    if question is not None:
        payload["question"] = question
    return json.dumps(payload)


def _cite(record_id, tool="memory_rules", kind="rule") -> dict:
    return {"tool": tool, "record_kind": kind, "record_id": record_id}


def _stub_rows(tenant, rows):
    """A registry adapter that returns exactly these rows, with the identity block."""

    def adapter(ctx, args):
        return [
            dict(
                row,
                tenant_id=str(tenant.id),
                as_of=ctx.skill.today.isoformat(),
            )
            for row in rows
        ]

    return adapter


def _swap(monkeypatch, tenant, name, rows):
    spec = replace(TOOL_REGISTRY[name], adapter=_stub_rows(tenant, rows))
    monkeypatch.setitem(TOOL_REGISTRY, name, spec)


#: A row a paragraph can legitimately cite: one id, one rendered figure.
_RULE_ROW = {
    "record_kind": "rule",
    "record_id": "rule-9f2c",
    "text": "This vendor bills monthly.",
    "rendered": "12,500.00",
}


# ═════════════════════════════════════════════════════════════════════════════
# 1. The three caps
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_the_loop_stops_at_six_rounds_and_says_which_cap_it_hit(pg):
    """§3.1 step 4: a model that never stops calling tools is stopped.

    The script asks for a tool call every round, forever. The loop must invoke
    exactly `MAX_ROUNDS` times and emit `truncated{rounds}` — not run to the end
    of the script, and not hang.
    """
    session, tenant, written = pg
    _seed(session, written, tenant)
    ctx = _ctx(session, tenant)

    script = [[{"name": "orientation", "args": {}}] for _ in range(20)]
    events, run, recorder = _events(session, ctx, script)

    assert recorder.bound.invocations == atlas_agent.MAX_ROUNDS
    assert [e.data["reason"] for e in _of_type(events, "truncated")] == ["rounds"]
    assert run.truncated == "rounds"
    assert _of_type(events, "done"), "a truncated briefing still closes its stream"


@postgres_only
def test_the_thirteenth_tool_call_is_the_one_that_stops_the_loop(pg):
    """`MAX_INVOCATIONS = 12` means twelve run, the thirteenth is refused.

    Asserted on `run.tool_calls`, which is the dispatch log itself, so an
    off-by-one shows up as a count rather than as a message the test believed.
    """
    session, tenant, written = pg
    _seed(session, written, tenant)
    ctx = _ctx(session, tenant)

    # Five calls a round: the cap falls inside round three, mid-round, which is
    # the case a per-round check would miss.
    round_of_five = [{"name": "orientation", "args": {}} for _ in range(5)]
    events, run, _ = _events(session, ctx, [round_of_five] * 5)

    assert len(run.tool_calls) == atlas_agent.MAX_INVOCATIONS
    assert [e.data["reason"] for e in _of_type(events, "truncated")] == ["invocations"]


@postgres_only
def test_a_slow_tool_trips_the_wall_clock(pg, monkeypatch):
    """§3.1 step 4's third cap, and the reason it is checked after each dispatch.

    One tool sleeps past the budget inside a single round. A wall clock tested
    only at the top of the loop would let that round finish and the next one
    start; this asserts the loop stops on the tool that spent the time.

    Run as a Trainer with a budget of half a second, both because of BE Gap 716:
    a Trainer pre-fetches one tool rather than four, and the budget is measured
    from before the pre-fetch, so a tighter one would be a test of how fast this
    machine reads three invoices rather than of the cap.
    """
    session, tenant, written = pg
    _seed(session, written, tenant)
    ctx = _ctx(session, tenant, grants=TRAINER)

    def slow(ctx_, args):
        time.sleep(0.6)
        return []

    monkeypatch.setattr(atlas_agent, "MAX_SECONDS", 0.5)
    monkeypatch.setitem(
        TOOL_REGISTRY, "orientation", replace(TOOL_REGISTRY["orientation"], adapter=slow)
    )

    script = [[{"name": "orientation", "args": {}}], [{"name": "orientation", "args": {}}]]
    events, run, recorder = _events(session, ctx, script)

    assert [e.data["reason"] for e in _of_type(events, "truncated")] == ["wall_clock"]
    assert recorder.bound.invocations == 1, "the second round must never start"
    # The pre-fetched `list_lines`, then the one slow call that spent the budget.
    assert [call["tool"] for call in run.tool_calls] == ["list_lines", "orientation"]


# ═════════════════════════════════════════════════════════════════════════════
# 2. What the run records
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_the_emitted_set_is_the_union_of_the_rows_the_tools_returned(pg):
    """§6 task 35.4: the citable set is exactly what ran, nothing else.

    Compared against a second, independent dispatch of the same tools on the
    same data rather than against a literal — the property is "the loop records
    what `run_tool()` emitted", and a hand-written id list would test the fixture.

    The list includes an Admin's pre-fetched tools (BE Gap 716): those rows go
    through `run_tool()` like any other, so they are part of what the loop
    recorded, and leaving them out would make this assertion say the opposite of
    what it means.
    """
    session, tenant, written = pg
    _seed(session, written, tenant)
    ctx = _ctx(session, tenant)

    script = [
        [{"name": "list_lines", "args": {}}, {"name": "memory_rules", "args": {}}],
        _answer([]),
    ]
    _, run, _ = _events(session, ctx, script)

    direct = BriefingRun(tenant_id=ctx.skill.tenant_id, user_id=ctx.user_id)
    expected: set[str] = set()
    for name in ("list_lines", "invoices", "cash_position", "forecast", "memory_rules"):
        rows = run_tool(name, _NO_ARGS, ctx, direct).rows
        expected |= {r["record_id"] for r in rows if r["record_id"]}

    assert expected, "the fixture produced no citable rows — the test would be vacuous"
    assert run.emitted_ids == expected
    assert run.rendered_tokens == direct.rendered_tokens


@postgres_only
def test_the_run_records_the_model_the_tokens_and_the_cost(pg):
    """§3.6: the real cost figure is on record from the first run.

    The mock reports zero tokens, so what is pinned here is that the accounting
    happened and is consistent — a model name, and a cost derived from the
    counts rather than left unset.
    """
    from utils.model_registry import cost_usd, resolve_model

    session, tenant, written = pg
    _seed(session, written, tenant)
    ctx = _ctx(session, tenant)

    _, run, _ = _events(session, ctx, [_answer([])])

    assert run.model == resolve_model("atlas").deployment
    assert run.cost_usd == cost_usd(run.model, run.tokens_in, run.tokens_out)
    assert run.tokens_in >= 0 and run.tokens_out >= 0


@postgres_only
def test_a_trainer_is_never_given_the_admin_tool_schemas(pg):
    """§3.2 at the loop's edge: the filter is applied where the model is bound."""
    session, tenant, written = pg
    _seed(session, written, tenant)
    ctx = _ctx(session, tenant, grants=TRAINER)

    _, _, recorder = _events(session, ctx, [_answer([])])
    names = {s["function"]["name"] for s in recorder.bound.tools}
    assert "cash_position" not in names and "forecast" not in names
    assert "list_lines" in names


# ═════════════════════════════════════════════════════════════════════════════
# 3. The guards, as the loop applies them (35.5 ⨯ 35.4)
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_a_cited_paragraph_reaches_the_wire(pg, monkeypatch):
    """The positive case, without which every drop test below passes vacuously."""
    session, tenant, written = pg
    _swap(monkeypatch, tenant, "memory_rules", [_RULE_ROW])
    ctx = _ctx(session, tenant)

    script = [
        [{"name": "memory_rules", "args": {}}],
        _answer(
            [{"text": "One rule is worth 12,500.00 today.", "citations": [_cite("rule-9f2c")]}]
        ),
    ]
    events, run, _ = _events(session, ctx, script)

    assert [e.data["text"] for e in _of_type(events, "paragraph")] == [
        "One rule is worth 12,500.00 today."
    ]
    assert run.dropped == 0
    assert _of_type(events, "done")[0].data["dropped_paragraphs"] == 0


@postgres_only
def test_an_uncited_paragraph_never_reaches_the_wire(pg, monkeypatch):
    session, tenant, written = pg
    _swap(monkeypatch, tenant, "memory_rules", [_RULE_ROW])
    ctx = _ctx(session, tenant)

    script = [
        [{"name": "memory_rules", "args": {}}],
        _answer([{"text": "Things look calm today.", "citations": []}]),
    ]
    events, run, _ = _events(session, ctx, script)

    assert _of_type(events, "paragraph") == []
    assert run.dropped == 1
    assert _of_type(events, "done")[0].data["dropped_paragraphs"] == 1


@postgres_only
def test_a_paragraph_citing_an_id_no_tool_emitted_is_dropped(pg, monkeypatch):
    """The hallucinated citation: right shape, never emitted this run."""
    session, tenant, written = pg
    _swap(monkeypatch, tenant, "memory_rules", [_RULE_ROW])
    ctx = _ctx(session, tenant)

    script = [
        [{"name": "memory_rules", "args": {}}],
        _answer([{"text": "A rule applies here.", "citations": [_cite("rule-0000")]}]),
    ]
    events, run, _ = _events(session, ctx, script)

    assert _of_type(events, "paragraph") == []
    assert run.dropped == 1


@postgres_only
def test_a_number_no_tool_rendered_is_dropped(pg, monkeypatch):
    """Hard rule 3 at the wire: the model may phrase a figure, never compute one."""
    session, tenant, written = pg
    _swap(monkeypatch, tenant, "memory_rules", [_RULE_ROW])
    ctx = _ctx(session, tenant)

    script = [
        [{"name": "memory_rules", "args": {}}],
        _answer(
            [{"text": "That comes to 25,000.00 in all.", "citations": [_cite("rule-9f2c")]}]
        ),
    ]
    events, run, _ = _events(session, ctx, script)

    assert _of_type(events, "paragraph") == []
    assert run.dropped == 1


@postgres_only
def test_a_paragraph_resting_only_on_orientation_is_dropped(pg):
    """§3.2: orientation is comprehension, not evidence — through the real tool."""
    session, tenant, written = pg
    _seed(session, written, tenant)
    ctx = _ctx(session, tenant)

    script = [
        [{"name": "orientation", "args": {}}],
        _answer(
            [
                {
                    "text": "ATLAS watches this workspace for you.",
                    "citations": [_cite("", tool="orientation", kind="orientation")],
                }
            ]
        ),
    ]
    events, run, _ = _events(session, ctx, script)

    assert _of_type(events, "paragraph") == []
    assert run.dropped == 1


@postgres_only
def test_only_the_first_question_survives(pg, monkeypatch):
    """§3.1 step 6: one question maximum; the extras are dropped and counted."""
    session, tenant, written = pg
    _swap(monkeypatch, tenant, "memory_rules", [_RULE_ROW])
    ctx = _ctx(session, tenant)

    question = {
        "text": "Does this vendor still bill monthly?",
        "citations": [_cite("rule-9f2c")],
        "answer_kind": "free_text",
    }
    second = dict(question, text="And should we keep chasing them?")
    script = [
        [{"name": "memory_rules", "args": {}}],
        _answer([], question=[question, second]),
    ]
    events, run, _ = _events(session, ctx, script)

    asked = _of_type(events, "question")
    assert [e.data["text"] for e in asked] == ["Does this vendor still bill monthly?"]
    assert asked[0].data["answer_kind"] == "free_text"
    assert run.dropped == 1


@postgres_only
def test_an_uncited_question_is_dropped_like_a_paragraph(pg, monkeypatch):
    session, tenant, written = pg
    _swap(monkeypatch, tenant, "memory_rules", [_RULE_ROW])
    ctx = _ctx(session, tenant)

    script = [
        [{"name": "memory_rules", "args": {}}],
        _answer([], question={"text": "How do you like to work?", "citations": []}),
    ]
    events, run, _ = _events(session, ctx, script)

    assert _of_type(events, "question") == []
    assert run.dropped == 1


# ═════════════════════════════════════════════════════════════════════════════
# 4. Falsification — the guard is load-bearing, not decorative
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_with_the_guard_patched_out_the_bad_paragraph_leaks(pg, monkeypatch):
    """Feature 34 §18.8's precedent, applied to task 35.5.

    Replace the guard with a no-op and the paragraph the previous tests prove is
    dropped reaches the wire instead. That is what makes those tests evidence
    about the guard rather than evidence that the mock said nothing: if this
    test ever goes green *and* the drop tests stay green, they are not testing
    the same code path.
    """
    session, tenant, written = pg
    _swap(monkeypatch, tenant, "memory_rules", [_RULE_ROW])
    ctx = _ctx(session, tenant)

    monkeypatch.setattr(
        atlas_agent, "validate_briefing_paragraph", lambda item, ids, figures: item
    )

    script = [
        [{"name": "memory_rules", "args": {}}],
        _answer([{"text": "That comes to 25,000.00 in all.", "citations": []}]),
    ]
    events, run, _ = _events(session, ctx, script)

    leaked = _of_type(events, "paragraph")
    assert [e.data["text"] for e in leaked] == ["That comes to 25,000.00 in all."]
    assert leaked[0].data["citations"] == []
    assert run.dropped == 0


# ═════════════════════════════════════════════════════════════════════════════
# 5. Output the loop cannot read
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_unparseable_output_is_an_error_event_and_no_prose(pg):
    """Never a fallback that invents sentences: zero paragraphs and an `error`."""
    session, tenant, written = pg
    _seed(session, written, tenant)
    ctx = _ctx(session, tenant)

    events, run, _ = _events(session, ctx, ["Good morning! Here is your briefing."])

    assert _of_type(events, "paragraph") == []
    assert len(_of_type(events, "error")) == 1
    assert _of_type(events, "done")


@postgres_only
def test_a_fenced_json_answer_is_still_read(pg, monkeypatch):
    """A markdown fence is a formatting habit, not a content failure."""
    session, tenant, written = pg
    _swap(monkeypatch, tenant, "memory_rules", [_RULE_ROW])
    ctx = _ctx(session, tenant)

    body = _answer([{"text": "One rule applies.", "citations": [_cite("rule-9f2c")]}])
    script = [[{"name": "memory_rules", "args": {}}], "```json\n" + body + "\n```"]
    events, run, _ = _events(session, ctx, script)

    assert [e.data["text"] for e in _of_type(events, "paragraph")] == ["One rule applies."]
    assert _of_type(events, "error") == []


# ═════════════════════════════════════════════════════════════════════════════
# 6. The prompts module — text, and the role it is built for
# ═════════════════════════════════════════════════════════════════════════════

def test_the_user_prompt_states_the_date_the_role_and_the_rules():
    prompt = briefing_user_prompt("auditor", GrantSet(can_audit=True), ["A rule."], TODAY)
    assert TODAY.isoformat() in prompt
    assert "auditor" in prompt
    assert "A rule." in prompt


def test_the_user_prompt_never_names_a_grant_the_caller_lacks():
    """The prompt describes the person it was built for, not the role above them."""
    prompt = briefing_user_prompt("trainer", TRAINER, [], TODAY)
    assert "runs this workspace" not in prompt
    assert "audits invoices" not in prompt


def test_every_role_has_a_welcome_and_an_unknown_one_still_gets_text():
    """§3.5: a cold tenant is never shown an empty screen or a KeyError."""
    assert set(WELCOME_BY_ROLE) == {"admin", "auditor", "trainer", "loader"}
    assert all(len(text.split()) > 20 for text in WELCOME_BY_ROLE.values())
    assert welcome_for("Admin") == WELCOME_BY_ROLE["admin"]
    assert welcome_for("nobody-mapped-this")


# ═════════════════════════════════════════════════════════════════════════════
# 5. BE Gap 716 — the role's opening rows are fetched, not hoped for
# ═════════════════════════════════════════════════════════════════════════════

AUDITOR = GrantSet(can_audit=True)


def _prefetched(run) -> list[str]:
    return [call["tool"] for call in run.tool_calls]


@postgres_only
def test_an_admin_run_fetches_four_tools_before_the_model_speaks(pg):
    """BE Gap 716: the four Admin needs cannot be answered from one tool's rows.

    Asserted on `run.tool_calls`, which is the dispatch log the briefing row
    stores — so the pre-fetch is auditable exactly as a model-chosen call is,
    and its position in that list is what "before the model speaks" means.
    """
    session, tenant, written = pg
    _seed(session, written, tenant)
    ctx = _ctx(session, tenant)

    # The model asks for one tool of its own, so the ordering assertion below
    # is about position and not about the pre-fetch being the only thing there.
    script = [[{"name": "memory_rules", "args": {}}], _answer([])]
    _, run, _ = _events(session, ctx, script)

    assert _prefetched(run) == [
        "list_lines", "invoices", "cash_position", "forecast", "memory_rules",
    ]


@postgres_only
def test_the_prefetched_ids_are_citable_before_the_model_asks_for_anything(pg):
    """The rows go through `run_tool()`, so they land on the run like any other.

    Compared against an independent dispatch of the same four tools on the same
    data rather than against a literal id list: the property is "the pre-fetch
    emitted what those tools emit", which a hand-written list would not test.
    """
    session, tenant, written = pg
    _seed(session, written, tenant)
    ctx = _ctx(session, tenant)

    _, run, _ = _events(session, ctx, [_answer([])])

    direct = BriefingRun(tenant_id=ctx.skill.tenant_id, user_id=ctx.user_id)
    expected: set[str] = set()
    for name in ("list_lines", "invoices", "cash_position", "forecast"):
        rows = run_tool(name, _NO_ARGS, ctx, direct).rows
        expected |= {r["record_id"] for r in rows if r["record_id"]}

    assert expected, "the fixture produced no citable rows — the test would be vacuous"
    assert expected <= run.emitted_ids
    assert direct.rendered_tokens <= run.rendered_tokens


@postgres_only
def test_the_prefetched_rows_are_put_in_front_of_the_model(pg):
    """They are context, not bookkeeping: the first prompt carries them.

    Read off the bound mock's recorded first `invoke()` — the messages the model
    actually received — rather than trusting that the loop built them.
    """
    session, tenant, written = pg
    invoice = _seed(session, written, tenant)
    ctx = _ctx(session, tenant)

    _, _, recorder = _events(session, ctx, [_answer([])])

    first_round = "\n".join(str(m) for m in recorder.bound.calls[0])
    assert "invoices" in first_round
    assert str(invoice.id) in first_round


@postgres_only
def test_each_role_starts_with_what_that_role_can_act_on(pg):
    """Auditor two, Trainer one — and the Trainer's is not refused."""
    session, tenant, written = pg
    _seed(session, written, tenant)

    _, auditor_run, _ = _events(
        session, _ctx(session, tenant, grants=AUDITOR), [_answer([])]
    )
    assert _prefetched(auditor_run) == ["list_lines", "invoices"]

    _, trainer_run, _ = _events(
        session, _ctx(session, tenant, grants=TRAINER), [_answer([])]
    )
    assert _prefetched(trainer_run) == ["list_lines"]
    assert trainer_run.tool_calls[0]["refused"] is None


@postgres_only
def test_the_prefetch_is_counted_against_the_invocation_cap(pg):
    """Four free calls on top of twelve would be a budget nobody wrote down.

    The script asks for five tool calls a round forever; with four already
    spent, exactly eight more may run.
    """
    session, tenant, written = pg
    _seed(session, written, tenant)
    ctx = _ctx(session, tenant)

    round_of_five = [{"name": "orientation", "args": {}} for _ in range(5)]
    events, run, _ = _events(session, ctx, [round_of_five] * 5)

    assert len(run.tool_calls) == atlas_agent.MAX_INVOCATIONS
    assert _prefetched(run)[:4] == ["list_lines", "invoices", "cash_position", "forecast"]
    assert [e.data["reason"] for e in _of_type(events, "truncated")] == ["invocations"]


# ═════════════════════════════════════════════════════════════════════════════
# 6. BE Gaps 717/718 — the two guarantees that do not depend on the model
#
# Every test below runs the **real** adapters over real Postgres and gives the
# model a script that deliberately ignores the flagged invoice. That is the
# whole point: the live 2026-09-20 run proved a well-prompted model can simply
# choose not to mention one, so what is asserted here is that the briefing says
# it anyway.
# ═════════════════════════════════════════════════════════════════════════════

_DUP_MESSAGE = (
    "Possible duplicate: Rajesh Steel Corporation invoice RAJ-ALPHA has the same date "
    "and total (437,190.00) but a different number (RAJ-BETA). Check whether this is a "
    "re-issue."
)


def _alert(message: str, subject_id) -> list[dict]:
    """One `sa_alerts` entry in the pipeline's own shape (BE Gap 704)."""
    return [
        {
            "id": str(subject_id),
            "type": "near_duplicate",
            "message": f"{message} (ID: {subject_id})",
            "severity": "warning",
        }
    ]


def _seed_flagged(session, written, tenant, *, status="AUDIT_REQUIRED", message=_DUP_MESSAGE):
    """The VPI shape: an original, and a flagged repeat of it."""
    original = Invoice(
        tenant_id=tenant.id, file_path=f"tests/{uuid4().hex}.pdf",
        status="COMPLETED", flow_direction="INBOUND", currency="INR",
        vendor_name="Rajesh Steel Corporation", invoice_number="RAJ-ALPHA",
        grand_total=437190.0, due_date=TODAY + timedelta(days=3),
    )
    session.add(original)
    written.append(original)
    session.commit()
    session.refresh(original)

    repeat = Invoice(
        tenant_id=tenant.id, file_path=f"tests/{uuid4().hex}.pdf",
        status=status, flow_direction="INBOUND", currency="INR",
        vendor_name="Rajesh Steel Corporation", invoice_number="RAJ-BETA",
        grand_total=437190.0, due_date=TODAY + timedelta(days=3),
        sa_alerts=_alert(message, original.id),
    )
    session.add(repeat)
    written.append(repeat)
    session.commit()
    session.refresh(repeat)
    return original, repeat


#: The model writes nothing at all and asks nothing. Every guarantee below has
#: to hold against exactly this: an answer that is not wrong, merely silent.
_SILENT_ANSWER = json.dumps({"paragraphs": [], "question": None})


def _mentions(events, needle: str) -> list:
    return [e for e in _of_type(events, "paragraph") if needle in e.data["text"]]


def _line_id_for(ctx, invoice) -> str:
    """The recommendation id the real tools emit for this invoice, this run."""
    probe = BriefingRun(tenant_id=ctx.skill.tenant_id, user_id=ctx.user_id)
    rows = run_tool("list_lines", _NO_ARGS, ctx, probe).rows
    return next(r["record_id"] for r in rows if r.get("entity_id") == str(invoice.id))


@postgres_only
def test_a_flagged_invoice_the_model_ignored_is_reported_anyway(pg):
    """BE Gap 717: the invariant holds regardless of what the model chose.

    The model returns zero paragraphs. One paragraph still reaches the wire, it
    carries the invoice's own alert sentence, and it cites a row the run
    emitted — so it passed the same guards a model paragraph passes.
    """
    session, tenant, written = pg
    _original, repeat = _seed_flagged(session, written, tenant)
    ctx = _ctx(session, tenant)

    events, run, _ = _events(session, ctx, [_SILENT_ANSWER])
    appended = _of_type(events, "paragraph")

    assert len(appended) == 1, "one flagged invoice, one appended paragraph"
    text = appended[0].data["text"]
    assert "RAJ-BETA" in text
    # Verbatim, not paraphrased: the pipeline's sentence, minus the id
    # parenthetical `_alert_prose()` strips.
    assert "Possible duplicate" in text
    assert "but a different number (RAJ-BETA)" in text
    cited = {c["record_id"] for c in appended[0].data["citations"]}
    assert cited, "an appended paragraph is cited like any other"
    assert cited <= run.emitted_ids


@postgres_only
def test_the_same_invoice_is_not_reported_twice(pg):
    """An Admin sees the invoice as a line *and* as an `invoices` row.

    A paragraph citing either form is the invoice having been reported, so
    nothing is appended for it — the fix must not double-report RAJ-BETA.
    """
    session, tenant, written = pg
    _original, repeat = _seed_flagged(session, written, tenant)
    ctx = _ctx(session, tenant)
    line_id = _line_id_for(ctx, repeat)

    answer = _answer(
        [
            {
                "text": "Rajesh Steel Corporation RAJ-BETA is waiting on a decision.",
                "citations": [_cite(line_id, tool="list_lines", kind="recommendation")],
            }
        ]
    )
    events, _run, _ = _events(session, ctx, [answer])
    assert len(_of_type(events, "paragraph")) == 1
    assert len(_mentions(events, "RAJ-BETA")) == 1


@postgres_only
def test_a_settled_invoices_old_alert_is_not_reported_as_open(pg):
    """BE Gap 717's other half: PAID is not a queue.

    The identical alert text on a PAID invoice is history. Nothing is appended,
    so the briefing is silent about it rather than wrong about it.
    """
    session, tenant, written = pg
    _seed_flagged(session, written, tenant, status="PAID")
    ctx = _ctx(session, tenant)

    events, _run, _ = _events(session, ctx, [_SILENT_ANSWER])
    assert _mentions(events, "Possible duplicate") == []
    assert _of_type(events, "paragraph") == []


@postgres_only
def test_a_dismissed_flagged_invoice_is_not_reported(pg):
    """D49 outranks the guarantee: a line put away stays away.

    The dismissal names the recommendation id, and the `invoices` row for the
    same invoice must not smuggle it back in through the other door.
    """
    from models import AtlasDismissal

    session, tenant, written = pg
    _original, repeat = _seed_flagged(session, written, tenant)
    ctx = _ctx(session, tenant)
    line_id = _line_id_for(ctx, repeat)

    dismissal = AtlasDismissal(
        tenant_id=tenant.id, user_id=ctx.user_id, recommendation_id=line_id
    )
    session.add(dismissal)
    written.append(dismissal)
    session.commit()

    events, _run, _ = _events(session, ctx, [_SILENT_ANSWER])
    assert _mentions(events, "RAJ-BETA") == []


@postgres_only
def test_with_the_append_stubbed_out_the_flagged_invoice_vanishes(pg, monkeypatch):
    """Falsification (Feature 34 §18.8's precedent).

    Patch the deterministic append to a no-op and the briefing goes back to
    saying nothing about RAJ-BETA — which is exactly the live defect. The
    guarantee is therefore load-bearing, not decorative.
    """
    session, tenant, written = pg
    _seed_flagged(session, written, tenant)
    ctx = _ctx(session, tenant)

    monkeypatch.setattr(atlas_agent, "_uncited_open_alerts", lambda *a, **k: [])
    events, _run, _ = _events(session, ctx, [_SILENT_ANSWER])
    assert _mentions(events, "RAJ-BETA") == []


# ── BE Gap 718 — the interview fires on evidence, not on inspiration ─────────

@postgres_only
def test_an_unresolved_duplicate_pair_becomes_the_question(pg):
    """BE Gap 718: six live runs asked nothing with RAJ-2009 open. This asks.

    Built from the alert's own sentence: both numbers come out of the text the
    pipeline wrote, so the question names the pair the system flagged rather
    than a pair the model noticed.
    """
    session, tenant, written = pg
    _seed_flagged(session, written, tenant)
    ctx = _ctx(session, tenant)

    events, run, _ = _events(session, ctx, [_SILENT_ANSWER])
    questions = _of_type(events, "question")

    assert len(questions) == 1
    data = questions[0].data
    assert "RAJ-BETA" in data["text"] and "RAJ-ALPHA" in data["text"]
    assert data["answer_kind"] == "free_text"
    assert {c["record_id"] for c in data["citations"]} <= run.emitted_ids


@postgres_only
def test_no_question_when_a_rule_already_covers_the_pair(pg):
    """§7's memory is what stops ATLAS asking the same thing every morning."""
    session, tenant, written = pg
    _seed_flagged(session, written, tenant)
    ctx = _ctx(session, tenant)

    events, _run, _ = _events(
        session, ctx, [_SILENT_ANSWER],
        rules=["Rajesh Steel re-issues invoices; RAJ-BETA is a genuine second order."],
    )
    assert _of_type(events, "question") == []


@postgres_only
def test_never_two_questions_when_the_model_already_asked_one(pg):
    """§3.1 step 6's cap survives the new path: the model's question wins."""
    session, tenant, written = pg
    _original, repeat = _seed_flagged(session, written, tenant)
    ctx = _ctx(session, tenant)
    line_id = _line_id_for(ctx, repeat)

    answer = _answer(
        [
            {
                "text": "Rajesh Steel Corporation RAJ-BETA is waiting on a decision.",
                "citations": [_cite(line_id, tool="list_lines", kind="recommendation")],
            }
        ],
        question={
            "text": "Does Rajesh Steel Corporation re-issue invoices?",
            "citations": [_cite(line_id, tool="list_lines", kind="recommendation")],
            "answer_kind": "free_text",
        },
    )
    events, _run, _ = _events(session, ctx, [answer])
    questions = _of_type(events, "question")
    assert len(questions) == 1
    assert questions[0].data["text"] == "Does Rajesh Steel Corporation re-issue invoices?"


@postgres_only
def test_a_trainer_gets_the_guarantee_from_the_only_tool_they_have(pg):
    """The guarantee is not Admin-only.

    A Trainer is never shown the `invoices` tool (BE Gap 716), so anything
    appended for them comes from a `list_lines` row's own `alerts`. Asserted as
    an equivalence rather than a bare "something appeared", so the test is not
    silently vacuous on a fixture that gives a Trainer no line at all.
    """
    session, tenant, written = pg
    _seed_flagged(session, written, tenant)
    ctx = _ctx(session, tenant, grants=TRAINER)

    events, _run, _ = _events(session, ctx, [_SILENT_ANSWER])
    rows = run_tool(
        "list_lines", _NO_ARGS, ctx, BriefingRun(tenant_id=tenant.id, user_id=ctx.user_id)
    ).rows
    assert bool(_mentions(events, "RAJ-BETA")) == bool([r for r in rows if r.get("alert_open")])
