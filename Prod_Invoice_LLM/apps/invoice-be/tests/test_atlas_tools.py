"""Feature 35 (ATLAS Intelligence) task 35.1 — the tool registry, on real Postgres.

Spec: `docs/feature_35_atlas_intelligence.md` §3.2, §6 (task 35.1's row).

Every test here is a **property over the registry**, not an expectation about
one fixture's output: the number of rows a tenant's data produces is Feature
34's business and is asserted in that feature's tests. What this file pins is
what task 35.1 owns and what the later tasks rely on:

* every row from every adapter carries `record_kind`, `record_id`, `tenant_id`
  and `as_of` — the citation contract, tested by iterating the registry rather
  than by listing ten expected shapes, so a tool added later is covered on the
  day it is added;
* `tools_for()` **omits** a tool the caller may not use from the schema list,
  rather than including one that refuses — §3.2's "absent, not refused";
* `ask_sage` runs at most once per `BriefingRun` (§8 ruling 3);
* nothing a tool returns is outside the caller's tenant.

Real Postgres per hard rule 2 (`tests/atlas_pg.py` carries the guard).
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlmodel import select

from models import Invoice, Tenant
from services.atlas_capabilities import AtlasCapability, GrantSet
from services.atlas_skills import SkillContext
from services.atlas_tools import (
    TOOL_REGISTRY,
    BriefingRun,
    ToolContext,
    run_tool,
    tool_schemas,
    tools_for,
)
from tests.atlas_pg import open_session, postgres_only, unique_tag

TODAY = date(2026, 9, 18)

ADMIN = GrantSet(can_audit=True, can_train=True, can_load=True, is_admin=True)
TRAINER = GrantSet(can_train=True)
AUDITOR = GrantSet(can_audit=True)

#: The four fields §3.2 requires on every row of every tool.
IDENTITY_FIELDS = ("record_kind", "record_id", "tenant_id", "as_of")

#: Arguments for the tools that take them, so the registry can be walked whole.
#: Filled in per test from rows the fixture actually wrote.
_NO_ARGS: dict = {}


@pytest.fixture(scope="module")
def pg_session():
    session = open_session()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def pg(pg_session):
    """A fresh tenant per test, every row it wrote deleted afterwards.

    Same shape as `tests/test_atlas_skills.py`: these tools read *everything* a
    tenant has, so a shared tenant would make one test's invoice another test's
    cash position.
    """
    tag = unique_tag()
    tenant = Tenant(name=f"atlas-tools-{tag}", domain=f"atlas-tools-{tag}.test")
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


def _ctx(session, tenant, grants: GrantSet = ADMIN, **overrides) -> ToolContext:
    skill = SkillContext(
        tenant_id=tenant.id, today=TODAY, now=datetime(2026, 9, 18, 9, 0, 0)
    )
    base = dict(db=session, skill=skill, grants=grants, user_id="user-" + uuid4().hex[:8])
    base.update(overrides)
    return ToolContext(**base)


def _run(tenant, ctx: ToolContext) -> BriefingRun:
    return BriefingRun(tenant_id=tenant.id, user_id=ctx.user_id)


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


def _seed(session, written, tenant) -> Invoice:
    """Enough history that several tools have something to say.

    Deliberately ordinary: two payables, one receivable, one vendor with a
    history. Nothing here is asserted on directly — it exists so the registry
    walk below runs against rows rather than against empty lists.
    """
    vendor = "Vendor " + uuid4().hex[:6]
    first = _invoice(
        session, written, tenant,
        vendor_name=vendor, invoice_number=uuid4().hex[:8],
        grand_total=50000.0, due_date=TODAY + timedelta(days=4),
    )
    _invoice(
        session, written, tenant,
        vendor_name=vendor, invoice_number=uuid4().hex[:8],
        grand_total=60000.0, due_date=TODAY + timedelta(days=9),
    )
    _invoice(
        session, written, tenant,
        vendor_name="Customer " + uuid4().hex[:6], invoice_number=uuid4().hex[:8],
        grand_total=90000.0, due_date=TODAY + timedelta(days=12),
        status="SENT", flow_direction="OUTBOUND",
    )
    return first


# ═════════════════════════════════════════════════════════════════════════════
# 1. The citation contract — a property over the whole registry
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_every_adapter_row_carries_the_four_identity_fields(pg):
    """§3.2: record ids are what citations point at, so every row must have one.

    Walked over the registry rather than written out per tool: a tool added
    later is covered the day it is added, which a per-tool test would not do.
    """
    session, tenant, written = pg
    invoice = _seed(session, written, tenant)
    ctx = _ctx(session, tenant)
    run = _run(tenant, ctx)

    args_for = {
        "vendor_baseline": {"vendor": invoice.vendor_name, "currency": "INR"},
        "doubts": {"invoice_id": str(invoice.id)},
        # `reconcile` needs an attached statement document; with none, the
        # adapter returns no rows, which satisfies this property vacuously and
        # is asserted properly in the refusal test below.
        "reconcile": {"document_id": str(uuid4())},
        "action_log": {"limit": 5},
    }

    seen_any = False
    for name in TOOL_REGISTRY:
        if name == "ask_sage":
            continue  # covered in its own test; it runs a real chat turn
        result = run_tool(name, args_for.get(name, _NO_ARGS), ctx, run)
        assert result.refused is None, (name, result.refused)
        for row in result.rows:
            seen_any = True
            for key in IDENTITY_FIELDS:
                assert key in row, f"{name} row is missing {key}: {row}"
            assert row["tenant_id"] == str(tenant.id)
            assert row["as_of"] == TODAY.isoformat()
            assert row["record_kind"]
    assert seen_any, "no tool produced a row — the property would pass vacuously"


@postgres_only
def test_the_quiet_tools_also_carry_the_identity_fields(pg):
    """The same property, on the tools an ordinary tenant leaves empty.

    Written separately because the walk above passes vacuously for a tool with
    no rows, and `forecast`, `reconcile`, `action_log` and `memory_rules` are
    exactly the four an invoice-only fixture produces nothing from. Here each is
    given something to find: a bank balance too small for the payables, a vendor
    statement, an action and a rule.
    """
    from models import AtlasActionLog, AtlasMemoryRule, BankStatementLine, Document

    session, tenant, written = pg
    invoice = _seed(session, written, tenant)

    # A balance far below what is payable, so the walk finds a short day.
    balance = BankStatementLine(
        tenant_id=tenant.id,
        attachment_id=uuid4(),
        line_date=TODAY - timedelta(days=1),
        balance=1000.0,
    )
    # A vendor statement naming one of our invoices at a different amount.
    statement = Document(
        tenant_id=tenant.id,
        file_path=f"tests/{uuid4().hex}.pdf",
        doc_type="STATEMENT_OF_ACCOUNT",
        party_name=invoice.vendor_name,
        currency="INR",
        items=[{"description": f"Invoice {invoice.invoice_number}", "amount": 55000.0}],
    )
    rule = AtlasMemoryRule(
        tenant_id=tenant.id,
        text="This vendor bills monthly.",
        source="told",
        created_by="tester",
    )
    action = AtlasActionLog(
        tenant_id=tenant.id,
        user_id="tester",
        recommendation_id="audit-approve-" + str(invoice.id),
        action_kind="resolve_invoice",
        target_id=str(invoice.id),
        succeeded=True,
        summary="Resolved from the work screen.",
    )
    for row in (balance, statement, rule, action):
        session.add(row)
        written.append(row)
    session.commit()

    ctx = _ctx(session, tenant)
    run = _run(tenant, ctx)
    args_for = {
        "reconcile": {"document_id": str(statement.id), "vendor": invoice.vendor_name},
        "action_log": {"limit": 5},
    }
    for name in ("forecast", "reconcile", "action_log", "memory_rules"):
        result = run_tool(name, args_for.get(name, _NO_ARGS), ctx, run)
        assert result.refused is None, (name, result.refused)
        assert result.rows, f"{name} produced no rows, so its property is untested"
        for row in result.rows:
            for key in IDENTITY_FIELDS:
                assert key in row, f"{name} row is missing {key}: {row}"
            assert row["tenant_id"] == str(tenant.id)
            assert row["as_of"] == TODAY.isoformat()
            assert row["record_id"], f"{name} rows must be citable"


@postgres_only
def test_rows_are_json_serialisable(pg):
    """They are sent to a model as JSON; a Decimal or a UUID would fail there."""
    session, tenant, written = pg
    _seed(session, written, tenant)
    ctx = _ctx(session, tenant)
    run = _run(tenant, ctx)
    for name in ("list_lines", "cash_position", "forecast", "memory_rules", "orientation"):
        result = run_tool(name, _NO_ARGS, ctx, run)
        json.dumps(result.rows)  # raises if anything is not JSON-safe


@postgres_only
def test_emitted_ids_are_every_non_empty_record_id(pg):
    """The set task 35.4 consumes is exactly what the rows carried."""
    session, tenant, written = pg
    _seed(session, written, tenant)
    ctx = _ctx(session, tenant)
    run = _run(tenant, ctx)

    expected: set[str] = set()
    for name in ("list_lines", "cash_position", "memory_rules"):
        result = run_tool(name, _NO_ARGS, ctx, run)
        expected |= {r["record_id"] for r in result.rows if r["record_id"]}
    assert run.emitted_ids == expected


@postgres_only
def test_orientation_rows_carry_no_id_so_they_cannot_be_cited(pg):
    """§3.2: orientation is comprehension, not evidence.

    The rule is enforced by the *absence of an id*, not by a prompt sentence: a
    paragraph citing only orientation names something that was never emitted, so
    task 35.5's guard drops it.
    """
    session, tenant, written = pg
    _seed(session, written, tenant)
    ctx = _ctx(session, tenant)
    run = _run(tenant, ctx)
    result = run_tool("orientation", _NO_ARGS, ctx, run)
    assert result.rows, "an Admin holds capabilities, so orientation has parts"
    assert all(row["record_id"] == "" for row in result.rows)
    assert run.emitted_ids == set()


@postgres_only
def test_a_tool_never_returns_another_tenants_rows(pg, pg_session):
    """Tenant scoping is `SkillContext`'s, and it is tested, not assumed."""
    session, tenant, written = pg
    _seed(session, written, tenant)

    other_tag = unique_tag()
    other = Tenant(name=f"atlas-tools-{other_tag}", domain=f"atlas-tools-{other_tag}.test")
    session.add(other)
    session.commit()
    session.refresh(other)
    try:
        ctx = _ctx(session, other)
        run = _run(other, ctx)
        rows = run_tool("list_lines", _NO_ARGS, ctx, run).rows
        assert all(row["tenant_id"] == str(other.id) for row in rows)
        # The seeded tenant's invoices are not this tenant's work.
        assert not any(str(inv.id) in row.get("entity_id", "") for row in rows for inv in written)
    finally:
        session.delete(other)
        session.commit()


# ═════════════════════════════════════════════════════════════════════════════
# 2. Visibility — absent, not refused
# ═════════════════════════════════════════════════════════════════════════════

def test_a_trainer_is_never_shown_the_admin_or_audit_tools():
    """§3.2 / the `visible_to()` precedent: filtered before the schemas are sent.

    Asserted on the **schema list**, not on a refusal: a tool that appeared and
    then refused would tell the model the capability exists, and a model told
    what it cannot have spends a round asking for it.
    """
    names = {s["function"]["name"] for s in tool_schemas(TRAINER)}
    assert "cash_position" not in names
    assert "forecast" not in names
    assert "reconcile" not in names
    assert "doubts" not in names
    assert "vendor_baseline" not in names
    # And it keeps the ones a Trainer legitimately has.
    assert {"list_lines", "memory_rules", "orientation", "action_log", "ask_sage"} <= names


def test_an_auditor_sees_the_audit_tools_but_not_the_admin_ones():
    names = {spec.name for spec in tools_for(AUDITOR)}
    assert {"doubts", "reconcile", "vendor_baseline"} <= names
    assert "cash_position" not in names and "forecast" not in names


def test_an_admin_is_the_superset():
    assert {spec.name for spec in tools_for(ADMIN)} == set(TOOL_REGISTRY)


def test_an_ungranted_caller_still_gets_no_capability_tool():
    names = {spec.name for spec in tools_for(GrantSet())}
    assert "cash_position" not in names and "doubts" not in names


def test_every_schema_is_the_openai_function_shape():
    for schema in tool_schemas(ADMIN):
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"] and fn["description"]
        assert fn["parameters"]["type"] == "object"
        assert isinstance(fn["parameters"]["properties"], dict)
        for required in fn["parameters"]["required"]:
            assert required in fn["parameters"]["properties"]


@postgres_only
def test_an_invisible_tool_is_refused_even_if_its_name_is_invented(pg):
    """The filter is re-checked at dispatch, so a hallucinated name goes nowhere."""
    session, tenant, written = pg
    ctx = _ctx(session, tenant, grants=TRAINER)
    run = _run(tenant, ctx)
    result = run_tool("cash_position", _NO_ARGS, ctx, run)
    assert result.refused
    assert [row["record_kind"] for row in result.rows] == ["refusal"]
    assert run.emitted_ids == set()

    unknown = run_tool("pay_the_invoice", _NO_ARGS, ctx, run)
    assert unknown.refused


@postgres_only
def test_a_missing_required_argument_is_a_refusal_not_a_crash(pg):
    session, tenant, written = pg
    ctx = _ctx(session, tenant)
    run = _run(tenant, ctx)
    result = run_tool("doubts", {}, ctx, run)
    assert result.refused and "invoice_id" in result.refused


@postgres_only
def test_a_failing_service_becomes_a_refusal_row(pg, monkeypatch):
    """One tool failing must not end the briefing."""
    session, tenant, written = pg
    ctx = _ctx(session, tenant)
    run = _run(tenant, ctx)

    def _boom(ctx_, args):
        raise RuntimeError("the service fell over")

    monkeypatch.setitem(
        TOOL_REGISTRY, "memory_rules", replace(TOOL_REGISTRY["memory_rules"], adapter=_boom)
    )
    result = run_tool("memory_rules", _NO_ARGS, ctx, run)
    assert result.refused and "fell over" in result.refused
    assert result.rows[0]["record_kind"] == "refusal"


# ═════════════════════════════════════════════════════════════════════════════
# 3. ask_sage — once per briefing (§8 ruling 3)
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_ask_sage_runs_once_and_the_second_call_is_refused(pg, monkeypatch):
    """The cap lives in `run_tool()`, so it cannot be walked past by any caller.

    The adapter is stubbed rather than running a real SAGE turn: what is under
    test is the budget, and a real chat turn would make this a test of the chat
    stack that happens to also exercise the cap.
    """
    session, tenant, written = pg
    ctx = _ctx(session, tenant)
    run = _run(tenant, ctx)

    calls: list[dict] = []

    def _stub(ctx_, args):
        calls.append(dict(args))
        return [
            {
                "record_kind": "sage_answer",
                "record_id": "sage-" + uuid4().hex[:8],
                "tenant_id": str(ctx_.skill.tenant_id),
                "as_of": ctx_.skill.today.isoformat(),
                "answer": "an answer",
            }
        ]

    monkeypatch.setitem(
        TOOL_REGISTRY, "ask_sage", replace(TOOL_REGISTRY["ask_sage"], adapter=_stub)
    )

    first = run_tool("ask_sage", {"question": "which vendor is new?"}, ctx, run)
    assert first.refused is None
    assert run.sage_calls == 1

    second = run_tool("ask_sage", {"question": "and the next one?"}, ctx, run)
    assert second.refused, "a second ask_sage must be refused, not answered"
    assert [row["record_kind"] for row in second.rows] == ["refusal"]
    assert len(calls) == 1, "the adapter must not have run a second time"
    assert run.sage_calls == 1


@postgres_only
def test_ask_sage_returns_the_turn_it_ran(pg, monkeypatch):
    """The real adapter's row shape, with the chat turn itself stubbed out."""
    session, tenant, written = pg
    from models import ChatSession
    from routers import chat as chat_router
    from services import atlas_tools

    class _Message:
        id = uuid4()
        content = "Two vendors are new this month."
        generated_sql = "SELECT 1"
        result_invoice_ids = [uuid4()]

    seen: dict = {}

    def _fake_turn(**kwargs):
        seen.update(kwargs)
        return _Message()

    monkeypatch.setattr(chat_router, "run_sync_chat_turn", _fake_turn)

    ctx = _ctx(session, tenant)
    run = _run(tenant, ctx)
    rows = atlas_tools.tool_ask_sage(ctx, {"question": "anything new?"})
    try:
        assert len(rows) == 1
        row = rows[0]
        for key in IDENTITY_FIELDS:
            assert key in row
        assert row["record_kind"] == "sage_answer"
        assert row["answer"] == _Message.content
        assert row["generated_sql"] == "SELECT 1"
        assert seen["tenant_id"] == tenant.id
    finally:
        # The adapter opens one chat session for the briefing; it is a real row.
        for created in session.exec(
            select(ChatSession).where(ChatSession.tenant_id == tenant.id)
        ).all():
            session.delete(created)
        session.commit()


# ═════════════════════════════════════════════════════════════════════════════
# 4. The run log
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_every_dispatch_is_logged_on_the_run(pg):
    """§4's `tool_calls` column: tool, args, ms, rows — including refusals."""
    session, tenant, written = pg
    _seed(session, written, tenant)
    ctx = _ctx(session, tenant, grants=TRAINER)
    run = _run(tenant, ctx)

    run_tool("list_lines", _NO_ARGS, ctx, run)
    run_tool("cash_position", _NO_ARGS, ctx, run)  # invisible to a Trainer

    assert [call["tool"] for call in run.tool_calls] == ["list_lines", "cash_position"]
    assert all(set(call) == {"tool", "args", "ms", "rows", "refused"} for call in run.tool_calls)
    assert run.tool_calls[0]["refused"] is None
    assert run.tool_calls[1]["refused"]


# ═════════════════════════════════════════════════════════════════════════════
# 5. Task 35.3 — the `atlas` model role
# ═════════════════════════════════════════════════════════════════════════════

def test_atlas_role_resolves_to_its_own_deployment_when_set(monkeypatch):
    from config import get_settings
    from utils import model_registry as reg

    s = get_settings()
    monkeypatch.setattr(s, "LLM_PROVIDER", "azure")
    monkeypatch.setattr(s, "AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-5-mini")
    monkeypatch.setattr(s, "AZURE_OPENAI_ATLAS_DEPLOYMENT_NAME", "gpt-5.6-terra")
    spec = reg.resolve_model("atlas")
    assert spec.deployment == "gpt-5.6-terra"
    # §3.4's model, priced from the catalog rather than from a second table.
    assert (spec.price_in, spec.price_out) == (2.00, 12.00)
    assert reg.registry_snapshot()["atlas"]["deployment"] == "gpt-5.6-terra"


def test_atlas_role_falls_back_to_the_primary_when_blank(monkeypatch):
    from config import get_settings
    from utils import model_registry as reg

    s = get_settings()
    monkeypatch.setattr(s, "LLM_PROVIDER", "azure")
    monkeypatch.setattr(s, "AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-5-mini")
    monkeypatch.setattr(s, "AZURE_OPENAI_ATLAS_DEPLOYMENT_NAME", "")
    assert reg.resolve_model("atlas").deployment == "gpt-5-mini"


def test_get_llm_for_role_accepts_atlas(monkeypatch):
    from config import get_settings
    from utils.llm import MockInvoiceLLM, get_llm_for_role

    s = get_settings()
    monkeypatch.setattr(s, "LLM_PROVIDER", "mock")
    assert isinstance(get_llm_for_role("atlas"), MockInvoiceLLM)


def test_the_atlas_setting_defaults_to_empty():
    """§2: default empty, set per environment by task 35.0."""
    from config import Settings

    assert Settings.model_fields["AZURE_OPENAI_ATLAS_DEPLOYMENT_NAME"].default == ""


# ═════════════════════════════════════════════════════════════════════════════
# 6. BE Gap 716 — what the pipeline recorded on the invoice reaches the model
# ═════════════════════════════════════════════════════════════════════════════

def _alert(kind: str, message: str, subject_id) -> list[dict]:
    """One `sa_alerts` entry in the shape the pipeline writes it (BE Gap 704).

    A dict with the id parenthetical inside the message, because that is what a
    real row carries and the whole point of this section is that what a person
    reads survives the journey to the model unchanged.
    """
    return [
        {
            "id": str(subject_id),
            "type": kind,
            "message": f"{message} (ID: {subject_id})",
            "severity": "warning",
        }
    ]


def _prose_of(invoice) -> list[str]:
    """What `_alert_prose()` makes of this invoice's alerts — the expected value.

    Derived from the stored row rather than written out as a literal, so the
    assertion is "the tool copied the alert" and not "the tool produced this
    string", and a change to the envelope shape moves both sides together.
    """
    from services.atlas_skills import _alert_prose

    return [prose for a in (invoice.sa_alerts or []) if (prose := _alert_prose(a))]


@postgres_only
def test_a_line_row_carries_the_invoices_alert_verbatim(pg):
    """BE Gap 716: the duplicate the pipeline found reaches the model as a fact.

    The live VPI run wrote about RAJ-2009 without the word *duplicate* because
    the row it was given had a ranked headline and nothing else. `doubt` and
    `alerts` are the invoice's own sentence, unchanged.
    """
    session, tenant, written = pg
    original = _invoice(
        session, written, tenant,
        vendor_name="Rajesh Steel", invoice_number="RAJ-ALPHA",
        grand_total=437190.0, due_date=TODAY + timedelta(days=3),
        status="COMPLETED",
    )
    repeat = _invoice(
        session, written, tenant,
        vendor_name="Rajesh Steel", invoice_number="RAJ-BETA",
        grand_total=437190.0, due_date=TODAY + timedelta(days=3),
        sa_alerts=_alert(
            "possible_duplicate", "Possible duplicate of invoice #2009", original.id
        ),
    )
    session.commit()

    ctx = _ctx(session, tenant)
    run = _run(tenant, ctx)
    rows = run_tool("list_lines", _NO_ARGS, ctx, run).rows
    mine = [r for r in rows if r.get("entity_id") == str(repeat.id)]
    assert mine, "the invoice awaiting a decision produced no line"

    expected = _prose_of(repeat)
    assert expected, "the fixture's alert produced no prose — the test would be vacuous"
    for row in mine:
        assert row["alerts"] == expected
        assert row["doubt"] == expected[0]
        # The word the live briefing never said, present character for character.
        assert "duplicate" in row["doubt"]
        # And the id plumbing is not: BE Gap 704's rule survives the trip.
        assert str(original.id) not in row["doubt"]


@postgres_only
def test_a_line_about_something_that_is_not_an_invoice_carries_no_alerts(pg):
    """The boundary: `alerts` is the invoice's, so a non-invoice line has none."""
    session, tenant, written = pg
    _seed(session, written, tenant)
    ctx = _ctx(session, tenant)
    run = _run(tenant, ctx)
    rows = run_tool("list_lines", _NO_ARGS, ctx, run).rows
    for row in rows:
        if row.get("record_kind") == "recommendation" and row.get("entity_kind") != "invoice":
            assert row["alerts"] == []


@postgres_only
def test_invoices_returns_the_outbound_invoice_that_no_line_reaches(pg):
    """BE Gap 716: VPI-OUT-2014's shape — outbound, NEEDS_REVIEW, tax_mismatch.

    Two assertions, and the first is what makes the second worth having: no
    `list_lines` row carries this invoice's id (the skills are inbound-only), so
    before this tool the model could not have cited it at all.
    """
    session, tenant, written = pg
    outbound = _invoice(
        session, written, tenant,
        customer_name="Kaveri Auto Components", invoice_number="OUT-ALPHA",
        grand_total=483850.0, due_date=TODAY + timedelta(days=2),
        invoice_date=TODAY - timedelta(days=27),
        status="NEEDS_REVIEW", flow_direction="OUTBOUND",
        sa_alerts=_alert(
            "tax_mismatch",
            "Subtotal plus tax does not equal the printed total",
            uuid4(),
        ),
    )
    session.commit()

    ctx = _ctx(session, tenant)
    run = _run(tenant, ctx)

    lines = run_tool("list_lines", _NO_ARGS, ctx, run).rows
    assert not [r for r in lines if r.get("entity_id") == str(outbound.id)]
    assert str(outbound.id) not in run.emitted_ids

    rows = run_tool("invoices", _NO_ARGS, ctx, run).rows
    mine = [r for r in rows if r["record_id"] == str(outbound.id)]
    assert len(mine) == 1, "one row per invoice"
    row = mine[0]
    assert row["record_kind"] == "invoice"
    assert row["flow"] == "OUTBOUND"
    assert row["status"] == "NEEDS_REVIEW"
    assert row["party"] == outbound.customer_name
    assert row["invoice_number"] == outbound.invoice_number
    assert row["due_date"] == outbound.due_date.isoformat()
    assert row["alerts"] == _prose_of(outbound)
    assert "does not equal" in row["alerts"][0]
    # Citable, which is the whole difference from `forecast`'s id fields.
    assert str(outbound.id) in run.emitted_ids


@postgres_only
def test_invoices_renders_the_amount_and_never_invents_a_zero(pg):
    """Rendered by `atlas_figures`, and absent rather than zero when unknown."""
    from services.atlas_figures import render_amount

    session, tenant, written = pg
    priced = _invoice(
        session, written, tenant,
        vendor_name="Ganesh Bearings", invoice_number="GBP-ALPHA",
        grand_total=68676.0, currency="INR",
    )
    unpriced = _invoice(
        session, written, tenant,
        vendor_name="Ganesh Bearings", invoice_number="GBP-BETA",
        grand_total=None, status="PROCESSING",
    )
    session.commit()

    ctx = _ctx(session, tenant)
    run = _run(tenant, ctx)
    by_id = {r["record_id"]: r for r in run_tool("invoices", _NO_ARGS, ctx, run).rows}

    assert by_id[str(priced.id)]["amount"] == render_amount(68676.0, "INR")
    assert by_id[str(unpriced.id)]["amount"] is None


@postgres_only
def test_invoices_lists_only_the_fields_below_the_confidence_threshold(pg):
    """The Trainer's threshold, read from `atlas_skills`, not restated here."""
    from services.atlas_skills import _LOW_CONFIDENCE

    session, tenant, written = pg
    invoice = _invoice(
        session, written, tenant,
        vendor_name="Om Stationery", invoice_number="OM-ALPHA", grand_total=28792.0,
        field_confidence={
            "PaymentTerm": _LOW_CONFIDENCE - 0.3,
            "VendorName": _LOW_CONFIDENCE + 0.2,
            "InvoiceDate": _LOW_CONFIDENCE,
        },
    )
    session.commit()

    ctx = _ctx(session, tenant)
    run = _run(tenant, ctx)
    rows = {r["record_id"]: r for r in run_tool("invoices", _NO_ARGS, ctx, run).rows}
    # The threshold is exclusive: a field *at* it is not low-confidence.
    assert rows[str(invoice.id)]["low_confidence_fields"] == ["PaymentTerm"]


@postgres_only
def test_invoices_is_absent_from_a_trainers_schema_list_and_refused_at_dispatch(pg):
    """§3.2's absent-not-refused, applied to the new tool.

    The whole ledger is the audit surface; a Trainer corrects fields on the
    documents in front of them and is never told this tool exists.
    """
    session, tenant, written = pg
    _seed(session, written, tenant)

    assert "invoices" not in {s["function"]["name"] for s in tool_schemas(TRAINER)}
    assert "invoices" in {spec.name for spec in tools_for(AUDITOR)}
    assert "invoices" in {spec.name for spec in tools_for(ADMIN)}
    assert "invoices" not in {spec.name for spec in tools_for(GrantSet())}

    ctx = _ctx(session, tenant, grants=TRAINER)
    run = _run(tenant, ctx)
    result = run_tool("invoices", _NO_ARGS, ctx, run)
    assert result.refused
    assert run.emitted_ids == set()


@postgres_only
def test_invoices_never_returns_another_tenants_ledger(pg, pg_session):
    """The tool reads the invoice table directly, so its scoping is tested."""
    session, tenant, written = pg
    _seed(session, written, tenant)

    other_tag = unique_tag()
    other = Tenant(name=f"atlas-tools-{other_tag}", domain=f"atlas-tools-{other_tag}.test")
    session.add(other)
    session.commit()
    session.refresh(other)
    try:
        ctx = _ctx(session, other)
        rows = run_tool("invoices", _NO_ARGS, ctx, _run(other, ctx)).rows
        assert rows == [], "a fresh tenant holds no invoices"
    finally:
        session.delete(other)
        session.commit()


# ═════════════════════════════════════════════════════════════════════════════
# 7. BE Gap 717 — an alert is open only while somebody still owes a decision
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_an_invoice_row_says_whether_its_alert_is_still_open(pg):
    """BE Gap 717: the same sentence, two very different facts.

    Both invoices below carry the identical alert text. One is AUDIT_REQUIRED —
    somebody still has to decide — and one is PAID, where the sentence is
    history. The text is carried on both (provenance is never hidden); only
    `alert_open` separates them, and it is `alert_is_open()`'s answer about the
    status, not a second list of statuses living in the tool.
    """
    session, tenant, written = pg
    original = _invoice(
        session, written, tenant,
        vendor_name="Rajesh Steel", invoice_number="RAJ-ALPHA",
        grand_total=437190.0, due_date=TODAY + timedelta(days=3),
        status="COMPLETED",
    )
    message = "Possible duplicate of invoice #2009"
    open_one = _invoice(
        session, written, tenant,
        vendor_name="Rajesh Steel", invoice_number="RAJ-BETA",
        grand_total=437190.0, due_date=TODAY + timedelta(days=3),
        status="AUDIT_REQUIRED",
        sa_alerts=_alert("possible_duplicate", message, original.id),
    )
    settled = _invoice(
        session, written, tenant,
        vendor_name="Rajesh Steel", invoice_number="RAJ-GAMMA",
        grand_total=437190.0, due_date=TODAY + timedelta(days=3),
        status="PAID",
        sa_alerts=_alert("possible_duplicate", message, original.id),
    )
    session.commit()

    ctx = _ctx(session, tenant)
    rows = {r["record_id"]: r for r in run_tool("invoices", _NO_ARGS, ctx, _run(tenant, ctx)).rows}

    assert rows[str(open_one.id)]["alert_open"] is True
    assert rows[str(settled.id)]["alert_open"] is False
    # The text survives on both — this gap hid the *claim*, never the record.
    assert rows[str(settled.id)]["alerts"] == _prose_of(settled)
    assert rows[str(open_one.id)]["alerts"] == _prose_of(open_one)
    # An invoice with no alert at all is not "open".
    assert rows[str(original.id)]["alert_open"] is False


@postgres_only
def test_an_outbound_invoice_awaiting_review_still_counts_as_open(pg):
    """VPI-OUT-2014's shape: NEEDS_REVIEW is a queue too.

    `_AWAITING_AUDIT` alone would have made the tenant's only arithmetic defect
    a closed alert, which is why `_ALERT_OPEN_STATUSES` is built from it plus
    the outbound review statuses rather than being it.
    """
    session, tenant, written = pg
    outbound = _invoice(
        session, written, tenant,
        customer_name="Kaveri Auto Components", invoice_number="OUT-ALPHA",
        flow_direction="OUTBOUND", status="NEEDS_REVIEW",
        grand_total=483850.0, due_date=TODAY + timedelta(days=2),
        sa_alerts=_alert("tax_mismatch", "Subtotal plus tax does not match the total", uuid4()),
    )
    session.commit()

    ctx = _ctx(session, tenant)
    rows = {r["record_id"]: r for r in run_tool("invoices", _NO_ARGS, ctx, _run(tenant, ctx)).rows}
    assert rows[str(outbound.id)]["alert_open"] is True


@postgres_only
def test_a_line_row_carries_the_same_open_flag_as_its_invoice(pg):
    """The `list_lines` half of the same rule.

    A line is emitted for an invoice awaiting a decision, so its row's
    `alert_open` is the invoice's; a line about something that is not an invoice
    carries `False` rather than nothing.
    """
    session, tenant, written = pg
    original = _invoice(
        session, written, tenant,
        vendor_name="Rajesh Steel", invoice_number="RAJ-ALPHA",
        grand_total=437190.0, due_date=TODAY + timedelta(days=3),
        status="COMPLETED",
    )
    repeat = _invoice(
        session, written, tenant,
        vendor_name="Rajesh Steel", invoice_number="RAJ-BETA",
        grand_total=437190.0, due_date=TODAY + timedelta(days=3),
        sa_alerts=_alert("possible_duplicate", "Possible duplicate of invoice #2009", original.id),
    )
    session.commit()

    ctx = _ctx(session, tenant)
    rows = run_tool("list_lines", _NO_ARGS, ctx, _run(tenant, ctx)).rows
    mine = [r for r in rows if r.get("entity_id") == str(repeat.id)]
    assert mine, "the invoice awaiting a decision produced no line"
    assert all(r["alert_open"] is True for r in mine)

    not_invoices = [r for r in rows if r.get("entity_kind") not in (None, "invoice")]
    assert all(r.get("alert_open") is False for r in not_invoices)
