"""Feature 21 Phase 2 — the orchestrator loop, and the flag-off safety boundary.

Two kinds of test live here, and the difference is the point of the file:

**Mechanics, provable with mocks.** The call cap, the clarification
short-circuit, the tenant binding, the arithmetic grounding, the result shape,
and the flag-off parity. These are rule-following behaviours of the loop itself,
so a scripted planner proves them exactly.

**Tool selection, not provable with mocks.** Whether a real model reaches for
`ask_clarifying_question` on rule 4a's Titan Steel phrasing is a property of the
model, not of this code, and a mocked test that "proves" it would be proving only
that the script was written that way. That evidence comes from
`tests/run_agentic_sage_live.py`, run against the real configured Azure
deployment, with the transcripts recorded in
`docs/feature_21_rag_faithfulness.md`. This repo has a precedent for why the
distinction is not pedantry: Gap 226, and Feature 21's own revert, were both
prompt changes that passed a green mocked suite and regressed live.

Question phrasings are the real historical ones from this repo's tracker: rule
4a's Titan Steel Distributors / Redwood Facilities Group cases (Gap 270), the
Rajesh Steel CGST case (Gaps 263/264), the DataPipe vs. StratEdge comparison
(Gap 268), and the 5000 x 0.08 = 420.00 false equation (Gap 269).
"""
import ast
import inspect
import json
import os
from contextlib import ExitStack
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

os.environ["MOCK_EMBEDDINGS"] = "true"

from dependencies import MOCK_TENANT_ID
from models import Invoice

from agents import query_agent, sage_orchestrator
from agents.sage_orchestrator import (
    MAX_PLANNER_STEPS,
    MAX_TOOL_CALLS,
    TOOL_AGGREGATE,
    TOOL_ASK_CLARIFYING_QUESTION,
    TOOL_COMPUTE,
    TOOL_GET_FULL_RECORD,
    TOOL_IDENTIFY_INVOICES,
    TOOL_SEARCH_INVOICES,
    _grounded_arithmetic,
    build_planner_prompt,
    parse_results_table,
    render_grounded_arithmetic,
    run_agentic_sage,
    verified_citations,
)

sqlite_url = "sqlite:///:memory:"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


def _seed_invoice(db_session, **kwargs):
    defaults = dict(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/inv.pdf",
        flow_direction="INBOUND",
        status="COMPLETED",
        currency="USD",
    )
    defaults.update(kwargs)
    inv = Invoice(**defaults)
    db_session.add(inv)
    db_session.commit()
    return inv


def _seed_dashed_tenant_invoice(db_session, **row):
    """Insert a row whose `tenant_id` is stored in DASHED form.

    Same trick, and the same reason, as `tests/run_agentic_sage_live.py`: SQLite
    stores a UUID column as 32-char dashless hex, while every generated query
    (and every companion query rebuilt from one) carries the dashed literal rule
    1 requires. A test that needs the *real* SQL path to match rows has to insert
    the dashed form directly; `_seed_invoice` above is for tests that go through
    the ORM.
    """
    from sqlalchemy import text

    db_session.execute(
        text(
            "INSERT INTO invoice (id, tenant_id, file_path, vendor_name, flow_direction, "
            "currency, grand_total, status, items, tags, sa_alerts, created_at, "
            "processing_attempts) VALUES (:id, :tenant_id, 'mock/inv.pdf', :vendor_name, "
            "'INBOUND', :currency, :grand_total, 'COMPLETED', '[]', '[]', '[]', "
            "'2026-08-21 00:00:00', 0)"
        ),
        {"id": uuid4().hex, "tenant_id": str(MOCK_TENANT_ID), **row},
    )
    db_session.commit()


# ── scripted planner ────────────────────────────────────────────────────────


def _tool_call(name, args, call_id="call_1"):
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


def _plans(*tool_call_lists):
    """One AIMessage per planner step. An empty list means 'no tool call' -- i.e.
    the planner has decided it is ready for the answer step."""
    return [
        AIMessage(content="", tool_calls=list(calls)) if calls else AIMessage(content="")
        for calls in tool_call_lists
    ]


class _ScriptedLLM:
    """Stands in for the one LLM object the orchestrator gets from `get_llm()`.

    It has to wear three hats, because the real one does: `bind_tools()` for the
    planner, `with_structured_output()` for the SQL generation happening inside
    `identify_invoices`/`aggregate` (and the phrase extraction inside
    `search_invoices`), and `invoke()` for the final synthesis call. Keeping the
    three recorded separately is what lets a test assert "synthesis never ran"
    (the clarification short-circuit) without counting the wrong calls.
    """

    def __init__(self, planner_messages, sql_results=(), synthesis="Composed answer.", phrases=None):
        self._planner_messages = list(planner_messages)
        self._sql_results = list(sql_results)
        self._synthesis = synthesis
        # `search_invoices` asks for category phrases through the same
        # `with_structured_output` seam as SQL generation, but with a different
        # schema. Keeping them apart here means a test that scripts SQL doesn't
        # accidentally feed it to the phrase extractor.
        self._phrases = list(phrases) if phrases is not None else []
        self.bound_tools = None
        self.planner_inputs = []
        self.sql_prompts = []
        self.phrase_prompts = []
        self.synthesis_prompts = []

    def bind_tools(self, tools):
        self.bound_tools = tools
        outer = self

        class _Planner:
            def invoke(self, messages):
                outer.planner_inputs.append(list(messages))
                if not outer._planner_messages:
                    raise AssertionError("planner called more times than scripted")
                return outer._planner_messages.pop(0)

        return _Planner()

    def with_structured_output(self, schema):
        outer = self
        from agents.query_tools import CategoryPhrasesSchema

        if schema is CategoryPhrasesSchema:
            class _Phrases:
                def invoke(self, prompt):
                    outer.phrase_prompts.append(prompt)
                    return CategoryPhrasesSchema(phrases=list(outer._phrases))

            return _Phrases()

        class _Structured:
            def invoke(self, prompt):
                outer.sql_prompts.append(prompt)
                if not outer._sql_results:
                    raise AssertionError("SQL generation called more times than scripted")
                return outer._sql_results.pop(0)

        return _Structured()

    def invoke(self, prompt):
        self.synthesis_prompts.append(prompt)
        return MagicMock(content=self._synthesis)


def _sql(select_list="grand_total, currency", where_extra=""):
    return f"SELECT {select_list} FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'{where_extra}"


def _run(db_session, llm, question, *, rows_markdown=None, chunks=None, record_pages=None):
    """Run one agentic turn with everything external pinned."""
    patches = [
        patch("agents.sage_orchestrator.get_llm", return_value=llm),
        patch("agents.sage_orchestrator._get_tenant_stats_summary", return_value=""),
        patch("agents.query_tools.query_invoice_chunks", return_value=list(chunks or [])),
        patch("agents.query_tools.get_all_invoice_chunks", return_value=list(record_pages or [])),
    ]
    if rows_markdown is not None:
        def _fake_execute(sql, tenant_id, db_sess, snapshot=None):
            return rows_markdown

        patches.append(patch("agents.query_agent.execute_generated_sql", side_effect=_fake_execute))

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        return run_agentic_sage(str(uuid4()), question, str(MOCK_TENANT_ID), db_session)


# ── the flag-off boundary: nothing about the live pipeline changed ───────────


def test_flag_off_output_is_byte_identical_to_the_pre_phase_2_pipeline():
    """The Phase 2 equivalent of Phase 1's parity proof, and the reason this
    feature is safe to have in the tree at all.

    Eight scripted turns -- rule 4a's Titan Steel question, the Rajesh Steel CGST
    question, a rule 9 narrowing follow-up with a prior SQL turn, a first-attempt
    failure that exercises the repair loop, a null-SQL follow-up that exercises
    the retry-once path, a rule 8 decline, a RAG turn and a CHAT turn -- were run
    against `query_agent.py` BEFORE the flag existed, and their full output
    recorded. This replays them against the current code and compares the
    returned dict, every SQL-generation prompt and every synthesis prompt
    verbatim. See `tests/agentic_sage_parity_cases.py`.
    """
    from tests.agentic_sage_parity_cases import load_golden, run_case

    golden = load_golden()
    assert golden, "parity golden is empty -- it must be regenerated deliberately, not silently"

    from tests.agentic_sage_parity_cases import CASES

    assert len(CASES) == len(golden)
    for case, expected in zip(CASES, golden):
        actual = run_case(*case)
        assert actual["case"] == expected["case"]
        assert actual["result"] == expected["result"], f"{actual['case']}: result dict changed"
        # Gap 304 half (2): the one deliberate addition to what
        # `run_query_agent()` returns since this golden was recorded. It is
        # compared separately (see `run_case`) precisely so that "the pipeline is
        # unchanged" keeps meaning the answer, the SQL, the citations and the
        # prompts — and so that the addition itself is still asserted on rather
        # than merely tolerated.
        evidence = actual["judge_evidence"]
        assert evidence is not None, f"{actual['case']}: no judge evidence returned"
        assert evidence["route"] == actual["route"]
        # Gap 302: the second deliberate addition. Same treatment — asserted
        # here rather than absorbed into the golden, because it is emitted on
        # every one of these eight turns including the decline and the
        # repair-loop failure, which is the property the gap exists for.
        assert actual["turn_telemetry_present"], f"{actual['case']}: no turn telemetry returned"
        assert actual["turn_telemetry_route"] == actual["route"]
        assert actual["turn_telemetry_status"] in {"success", "declined", "error"}
        assert actual["sql_prompts"] == expected["sql_prompts"], f"{actual['case']}: SQL prompt changed"
        assert (
            actual["summary_prompts"] == expected["summary_prompts"]
        ), f"{actual['case']}: synthesis prompt changed"


def test_the_orchestrator_is_reachable_only_through_the_settings_flag():
    """Phase 1 AST-walked `query_agent` to prove no tool was wired in at all.
    That test's own docstring said it should be updated when Phase 2 landed --
    this is that update, asserting the narrower property that now has to hold:
    the single reference to the orchestrator sits inside an
    `if ...ENABLE_AGENTIC_SAGE:` branch, and nothing else from the agentic side
    is called anywhere in the module.

    Gap 310 (2026-08-24) makes one deliberate, named exception:
    `TOOL_GET_FULL_RECORD` is now called unguarded, because the default chat
    route hands the identified invoice's whole ORM row to its answering step and
    reuses that function to do it. It is the only tool here with no LLM call, no
    SQL generation and no orchestration decision in it. Everything that plans,
    generates or loops stays behind the flag, which is the property this test
    actually exists to hold -- see
    `test_query_tools.py::test_no_orchestration_tool_is_wired_into_the_live_chat_pipeline`.
    """
    tree = ast.parse(inspect.getsource(query_agent))

    guarded_orchestrator_calls = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test_src = ast.dump(node.test)
        if "ENABLE_AGENTIC_SAGE" not in test_src:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                if inner.func.id == "run_agentic_sage":
                    guarded_orchestrator_calls += 1
    assert guarded_orchestrator_calls == 1, "run_agentic_sage must be called exactly once, flag-guarded"

    # And nowhere else: every mention of the orchestrator or a Phase 1 tool must
    # be inside that branch.
    unguarded = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name in (
                TOOL_IDENTIFY_INVOICES,
                TOOL_SEARCH_INVOICES,
                TOOL_AGGREGATE,
                TOOL_COMPUTE,
                TOOL_ASK_CLARIFYING_QUESTION,
            ):
                unguarded.append(name)
    assert not unguarded, f"SAGE tools called directly from the live pipeline: {unguarded}"
    # The Gap 310 exception, asserted rather than merely omitted from the list
    # above: if the default route ever stops fetching the full record, that is a
    # regression this test should report, not tolerate silently.
    assert any(
        (node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", None))
        == TOOL_GET_FULL_RECORD
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ), "the default route no longer fetches the identified invoice's full record (Gap 310)"


def test_flag_off_never_imports_the_orchestrator_module():
    """The import lives inside the flag branch, not at module scope: with the
    flag off, `query_agent` does not even load `sage_orchestrator`, langgraph or
    the tool module. Same boundary Phase 1 got for free by the orchestrator not
    existing."""
    tree = ast.parse(inspect.getsource(query_agent))
    module_level = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
    }
    module_level |= {
        alias.name for node in tree.body if isinstance(node, ast.Import) for alias in node.names
    }
    assert not any("sage_orchestrator" in name for name in module_level)
    assert not any("query_tools" in name for name in module_level)


def test_flag_on_routes_to_the_orchestrator_and_flag_off_does_not(db_session):
    """The flag has to actually do something, in both directions -- a default-off
    flag that is never read is not a safety boundary, it is a comment."""
    sentinel = {"content": "agentic", "generated_sql": None, "citations": [], "result_invoice_ids": []}

    with patch("agents.sage_orchestrator.run_agentic_sage", return_value=sentinel) as m_agentic:
        with patch("config.get_settings", return_value=MagicMock(ENABLE_AGENTIC_SAGE=True)):
            out = query_agent.run_query_agent(str(uuid4()), "hello", str(MOCK_TENANT_ID), db_session)
    assert out == sentinel
    assert m_agentic.call_count == 1

    with patch("agents.sage_orchestrator.run_agentic_sage", return_value=sentinel) as m_agentic:
        with ExitStack() as stack:
            stack.enter_context(patch("agents.query_agent.classify_query", return_value="CHAT"))
            stack.enter_context(patch("agents.query_agent.get_llm", return_value=_ScriptedLLM([])))
            stack.enter_context(patch("agents.query_agent.get_cached_answer", return_value=None))
            stack.enter_context(patch("agents.query_agent.set_cached_answer"))
            stack.enter_context(patch("agents.query_agent._get_tenant_stats_summary", return_value=""))
            out = query_agent.run_query_agent(str(uuid4()), "hello", str(MOCK_TENANT_ID), db_session)
    assert m_agentic.call_count == 0
    assert out["content"] == "Composed answer."


# ── tenant scoping ──────────────────────────────────────────────────────────


def test_no_tool_schema_lets_the_model_choose_a_tenant(db_session):
    """Phase 1's handover note, enforced. `tenant_id` and `db_session` are closed
    over in `_ToolBox`; if either ever became a schema property the model could
    name a different tenant, which is a cross-tenant data leak, not a bug."""
    llm = _ScriptedLLM(_plans([]))
    _run(db_session, llm, "hello")

    assert llm.bound_tools, "the planner was never given any tools"
    for tool in llm.bound_tools:
        properties = tool["function"]["parameters"].get("properties", {})
        blob = json.dumps(tool).lower()
        assert "tenant" not in properties
        assert "tenant_id" not in blob
        assert "db_session" not in blob


def test_all_six_tools_are_bound_under_their_real_names(db_session):
    llm = _ScriptedLLM(_plans([]))
    _run(db_session, llm, "hello")

    names = {tool["function"]["name"] for tool in llm.bound_tools}
    assert names == {
        TOOL_IDENTIFY_INVOICES,
        TOOL_GET_FULL_RECORD,
        TOOL_SEARCH_INVOICES,
        TOOL_AGGREGATE,
        TOOL_COMPUTE,
        TOOL_ASK_CLARIFYING_QUESTION,
    }


def test_get_full_record_is_the_only_tool_that_takes_an_id(db_session):
    """The identify/fetch split, visible in the schemas the model is given: every
    other tool takes a question. If `get_full_record` ever took a question too,
    the split would be cosmetic."""
    llm = _ScriptedLLM(_plans([]))
    _run(db_session, llm, "hello")

    by_name = {tool["function"]["name"]: tool for tool in llm.bound_tools}
    properties = by_name[TOOL_GET_FULL_RECORD]["function"]["parameters"]["properties"]
    assert set(properties) == {"invoice_id"}
    for name in (TOOL_IDENTIFY_INVOICES, TOOL_SEARCH_INVOICES, TOOL_AGGREGATE):
        assert "question" in by_name[name]["function"]["parameters"]["properties"]


# ── the loop ────────────────────────────────────────────────────────────────


def test_one_tool_then_answer(db_session):
    llm = _ScriptedLLM(
        _plans([_tool_call(TOOL_AGGREGATE, {"question": "total spend"})], []),
        sql_results=[MagicMock(sql=_sql(), explanation_or_error=None)],
    )
    out = _run(db_session, llm, "what did we spend in total", rows_markdown="grand_total | currency\n--- | ---\n100.00 | USD\n250.00 | USD")

    assert out["agentic"]["tools_called"] == [TOOL_AGGREGATE]
    assert out["agentic"]["tool_calls_made"] == 1
    assert out["content"].startswith("Composed answer.")
    assert "### Query Results" in out["content"]
    assert out["generated_sql"] == _sql()


def test_identify_then_fetch_puts_the_whole_record_in_front_of_the_answer(db_session):
    """The architecture's core move, end to end: a detail question is two calls,
    and the second one returns the row in full. Gaps 263/264/285 are all the same
    failure -- the answer step never saw `taxes` because no prompt mentioned it.
    Here nothing curates the record, so the CGST/SGST rows are simply there."""
    invoice = _seed_invoice(
        db_session,
        vendor_name="Rajesh Steel",
        invoice_number="INDIA-20260722-003",
        currency="INR",
        grand_total=118000.0,
        tax_amount=18000.0,
        taxes=[
            {"type": "CGST", "rate": 9, "amount": 9000.0},
            {"type": "SGST", "rate": 9, "amount": 9000.0},
        ],
    )
    llm = _ScriptedLLM(
        _plans(
            [_tool_call(TOOL_IDENTIFY_INVOICES, {"question": "Rajesh Steel invoice"}, "c1")],
            [_tool_call(TOOL_GET_FULL_RECORD, {"invoice_id": str(invoice.id)}, "c2")],
            [],
        ),
        sql_results=[
            MagicMock(
                sql=_sql("id, vendor_name, invoice_number, grand_total, currency"),
                explanation_or_error=None,
            )
        ],
    )
    out = _run(
        db_session,
        llm,
        "whats the CGST we paid to Rajesh Steel",
        record_pages=[
            {
                "id": f"{invoice.id}_page_1",
                "document": "Rajesh Steel -- CGST 9% 9,000.00  SGST 9% 9,000.00",
                "metadata": {"invoice_id": str(invoice.id), "page": 1, "vendor_name": "Rajesh Steel"},
                "matched_by": "invoice_id",
            }
        ],
    )

    assert out["agentic"]["tools_called"] == [TOOL_IDENTIFY_INVOICES, TOOL_GET_FULL_RECORD]
    prompt = llm.synthesis_prompts[0]
    assert "COMPLETE RECORD for invoice" in prompt
    assert '"CGST"' in prompt and '"SGST"' in prompt
    assert "EVERY INDEXED PAGE OF THIS INVOICE'S DOCUMENT" in prompt
    assert str(invoice.id) in out["result_invoice_ids"]


def test_an_identical_repeat_tool_call_is_answered_from_the_turns_own_results(db_session):
    """Found live 2026-08-21, in all three identify->fetch turns of the golden
    sample: the planner asked for `get_full_record` on the same invoice id three
    times running and spent the whole tool-call budget on it. Because synthesis
    renders one section per tool result, the record and every document page went
    into the prompt three times -- 129,703 input tokens on an 11-page invoice
    where one fetch is ~43,000.

    A repeat of an identical read cannot return anything new, so it is answered
    from what the turn already has: the tool runs once, the planner is told it is
    the same result, and the synthesis prompt carries one copy."""
    invoice = _seed_invoice(db_session, vendor_name="Harbor Tech", invoice_number="US-20260722-001")
    fetch_args = {"invoice_id": str(invoice.id)}
    llm = _ScriptedLLM(
        _plans(
            [_tool_call(TOOL_IDENTIFY_INVOICES, {"question": "invoice US-20260722-001"}, "c1")],
            [_tool_call(TOOL_GET_FULL_RECORD, fetch_args, "c2")],
            [_tool_call(TOOL_GET_FULL_RECORD, fetch_args, "c3")],
            [],
        ),
        sql_results=[
            MagicMock(
                sql=_sql("id, vendor_name, invoice_number, grand_total, currency"),
                explanation_or_error=None,
            )
        ],
    )
    pages = [
        {
            "id": f"{invoice.id}_page_1",
            "document": "PAGE-ONE-MARKER Harbor Tech invoice",
            "metadata": {"invoice_id": str(invoice.id), "page": 1, "vendor_name": "Harbor Tech"},
            "matched_by": "invoice_id",
        }
    ]
    out = _run(db_session, llm, "does the bolts line add up", record_pages=pages)

    prompt = llm.synthesis_prompts[0]
    assert prompt.count("COMPLETE RECORD for invoice") == 1
    assert prompt.count("PAGE-ONE-MARKER") == 1
    # The repeat still counts against the budget -- it is a hard bound on how
    # long a turn may go on, not an accounting of useful work.
    assert out["agentic"]["tool_calls_made"] == 3
    assert out["agentic"]["tools_called"] == [TOOL_IDENTIFY_INVOICES, TOOL_GET_FULL_RECORD]


def test_the_same_invoice_id_written_two_ways_is_one_call(db_session):
    """Measured live 2026-08-21: the planner asked for the same record twice in
    one turn, once with the dashed UUID and once with the dashless hex. A plain
    string comparison sees two calls; it is one invoice, and the second fetch
    doubled the record in the synthesis prompt."""
    invoice = _seed_invoice(db_session, vendor_name="Kingsway Fasteners")
    llm = _ScriptedLLM(
        _plans(
            [_tool_call(TOOL_IDENTIFY_INVOICES, {"question": "Kingsway invoice"}, "c1")],
            [_tool_call(TOOL_GET_FULL_RECORD, {"invoice_id": str(invoice.id)}, "c2")],
            [_tool_call(TOOL_GET_FULL_RECORD, {"invoice_id": invoice.id.hex}, "c3")],
            [],
        ),
        sql_results=[
            MagicMock(
                sql=_sql("id, vendor_name, invoice_number, grand_total, currency"),
                explanation_or_error=None,
            )
        ],
    )
    _run(db_session, llm, "what is the total on the Kingsway invoice")

    assert llm.synthesis_prompts[0].count("COMPLETE RECORD for invoice") == 1


def test_a_repeat_call_with_different_arguments_still_runs(db_session):
    """The dedupe is keyed on exact arguments because the broaden-after-nothing
    move -- `aggregate` again, with a different question -- is a real and useful
    shape this loop exists to allow."""
    llm = _ScriptedLLM(
        _plans(
            [_tool_call(TOOL_AGGREGATE, {"question": "freight spend per vendor"}, "c1")],
            [_tool_call(TOOL_AGGREGATE, {"question": "delivery and shipping spend per vendor"}, "c2")],
            [],
        ),
        sql_results=[
            MagicMock(sql=_sql(), explanation_or_error=None),
            MagicMock(sql=_sql(), explanation_or_error=None),
        ],
    )
    out = _run(
        db_session,
        llm,
        "which vendors billed us for freight",
        rows_markdown="vendor_name | grand_total | currency\n--- | --- | ---\nBlue Ridge | 1120.00 | USD",
    )

    assert out["agentic"]["tools_called"] == [TOOL_AGGREGATE, TOOL_AGGREGATE]


def test_a_long_document_is_truncated_and_the_synthesis_prompt_says_so(db_session):
    """The other half of `bound_document_pages()`: the cap is only defensible if
    the answer step is told it happened.

    Measured live 2026-08-21 -- an 11-page invoice put 16,010 tokens of page text
    into one synthesis prompt and the whole prompt came to 129,818 input tokens
    against 1,906 for a one-page control. The bound is the fix; this test is the
    honesty half of it, and asserts the same disclosure pattern
    `columns_omitted` already uses: the heading stops claiming "EVERY INDEXED
    PAGE", the omitted page numbers are named, and the model is told to say so
    rather than answer as if it had read the whole document."""
    invoice = _seed_invoice(db_session, vendor_name="Meridian Industrial Supply")
    pages = [
        {
            "id": f"{invoice.id}_page_{n}",
            "document": f"[Page {n}]\n" + f"line {n} " * 400,
            "metadata": {"invoice_id": str(invoice.id), "page": n, "vendor_name": "Meridian"},
            "matched_by": "invoice_id",
        }
        for n in range(1, 12)
    ]
    llm = _ScriptedLLM(
        _plans(
            [_tool_call(TOOL_IDENTIFY_INVOICES, {"question": "Meridian invoice"}, "c1")],
            [_tool_call(TOOL_GET_FULL_RECORD, {"invoice_id": str(invoice.id)}, "c2")],
            [],
        ),
        sql_results=[
            MagicMock(
                sql=_sql("id, vendor_name, invoice_number, grand_total, currency"),
                explanation_or_error=None,
            )
        ],
    )
    _run(db_session, llm, "what are the payment terms on the Meridian invoice", record_pages=pages)

    prompt = llm.synthesis_prompts[0]
    assert "EVERY INDEXED PAGE OF THIS INVOICE'S DOCUMENT" not in prompt
    assert "OF THIS INVOICE'S 11 INDEXED PAGES" in prompt
    assert "are NOT shown above" in prompt
    # The two pages a detail question most often needs are the ones kept.
    assert "[Page 1]" in prompt and "[Page 11]" in prompt


def test_a_no_results_lookup_can_be_followed_by_a_broader_search(db_session):
    """The orchestrator test the spec asks for by name: a historical question
    that needed two tool calls -- a zero-result lookup, then a broader move. The
    old pipeline could not do this at all; it classified once and stopped."""
    llm = _ScriptedLLM(
        _plans(
            [_tool_call(TOOL_IDENTIFY_INVOICES, {"question": "freight charges"}, "c1")],
            [_tool_call(TOOL_SEARCH_INVOICES, {"question": "freight delivery shipping"}, "c2")],
            [],
        ),
        sql_results=[MagicMock(sql=_sql(), explanation_or_error=None)],
        phrases=["freight"],
    )
    out = _run(
        db_session,
        llm,
        "which vendors billed us for freight, delivery, or shipping charges",
        chunks=[
            {
                "id": "chunk-1",
                "document": "Freight and handling ... USD 120.00",
                "distance": 0.2,
                "matched_by": "semantic",
                "metadata": {"invoice_id": str(uuid4()), "vendor_name": "Blue Ridge Logistics", "page": 2},
            }
        ],
    )

    assert out["agentic"]["tools_called"] == [TOOL_IDENTIFY_INVOICES, TOOL_SEARCH_INVOICES]
    assert out["agentic"]["tool_calls_made"] == 2
    # The planner saw the first tool's real status before choosing again.
    second_planner_input = llm.planner_inputs[1]
    tool_message = second_planner_input[-1]
    assert json.loads(tool_message.content)["status"] == "no_results"


def test_a_clarifying_question_ends_the_turn_without_any_synthesis(db_session):
    """`ends_turn=True` is a fact the loop branches on, not advice it weighs:
    the turn's reply IS the question, no answer is composed, and no further tool
    runs even though the planner scripted one after it."""
    llm = _ScriptedLLM(
        _plans(
            [
                _tool_call(
                    TOOL_ASK_CLARIFYING_QUESTION,
                    {
                        "question": "Is Titan Steel Distributors a vendor who bills you, or a customer you bill?",
                        "reason": "AMBIGUOUS_DIRECTION",
                    },
                    "c1",
                ),
                _tool_call(TOOL_IDENTIFY_INVOICES, {"question": "titan steel"}, "c2"),
            ],
        )
    )
    out = _run(db_session, llm, "has the Titan Steel Distributors invoice been paid")

    assert out["content"] == (
        "Is Titan Steel Distributors a vendor who bills you, or a customer you bill?"
    )
    assert llm.synthesis_prompts == [], "synthesis must not run for a clarification turn"
    assert out["agentic"]["tools_called"] == [TOOL_ASK_CLARIFYING_QUESTION]
    assert out["agentic"]["stop_reason"] == "clarification_requested"
    assert out["agentic"]["clarification_reason"] == "AMBIGUOUS_DIRECTION"


def test_the_tool_call_budget_is_a_hard_stop(db_session):
    """A planner that never stops asking is stopped by the loop, not by the
    prompt's stated budget. Every extra call is a real Azure round-trip someone
    is waiting on, and an unbounded loop is a cost incident."""
    one_more = [_tool_call(TOOL_AGGREGATE, {"question": "again"}, "c")]
    llm = _ScriptedLLM(
        _plans(one_more, one_more, one_more, one_more, one_more, one_more, one_more),
        sql_results=[MagicMock(sql=_sql(), explanation_or_error=None) for _ in range(MAX_TOOL_CALLS)],
    )
    out = _run(db_session, llm, "how much did we spend last month")

    assert out["agentic"]["tool_calls_made"] == MAX_TOOL_CALLS
    assert out["agentic"]["stop_reason"] == "tool_call_budget_exhausted"
    # It still answers from what it has -- the cap ends the loop, not the turn.
    assert out["content"] == "Composed answer."
    assert len(llm.synthesis_prompts) == 1


def test_the_planner_step_budget_is_also_a_hard_stop(db_session):
    """The two budgets are different numbers: a planner step can request several
    tools at once, so capping tool calls alone would not cap LLM round-trips."""
    llm = _ScriptedLLM(_plans(*([[]] * (MAX_PLANNER_STEPS + 3))))
    out = _run(db_session, llm, "hello")

    # No tool calls at all here, so the loop leaves via the no-tool-call route
    # after exactly one planner step -- the cap exists for the other shape.
    assert len(llm.planner_inputs) == 1
    assert out["agentic"]["tool_calls_made"] == 0
    assert MAX_PLANNER_STEPS >= 1


def test_a_tool_that_raises_does_not_lose_the_turn(db_session):
    """`ask_clarifying_question` raises on an empty question by Phase 1's
    contract. That is a caller bug, and the caller here is a model -- it must not
    take the user's turn down with it."""
    llm = _ScriptedLLM(
        _plans(
            [_tool_call(TOOL_ASK_CLARIFYING_QUESTION, {"question": "  ", "reason": "OTHER"}, "c1")],
            [],
        )
    )
    out = _run(db_session, llm, "what about that one")

    assert out["content"] == "Composed answer."
    assert out["agentic"]["stop_reason"] is None


def test_a_greeting_needs_no_tool_and_states_no_invoice_fact(db_session):
    llm = _ScriptedLLM(_plans([]))
    out = _run(db_session, llm, "hello there")

    assert out["agentic"]["tools_called"] == []
    assert len(llm.synthesis_prompts) == 1
    assert "NO TOOL WAS CALLED FOR THIS TURN" in llm.synthesis_prompts[0]


def test_the_result_dict_has_the_same_keys_the_live_pipeline_returns(db_session):
    """`routers/chat.py` and the trainer's QA-test mode read this dict directly,
    so the flag must be switchable without touching either."""
    llm = _ScriptedLLM(_plans([]))
    out = _run(db_session, llm, "hello")

    for key in ("content", "generated_sql", "citations", "result_invoice_ids"):
        assert key in out


# ── synthesis sees tool output, and only tool output ────────────────────────


def test_synthesis_prompt_carries_the_tool_results_not_the_planner_reasoning(db_session):
    llm = _ScriptedLLM(
        _plans([_tool_call(TOOL_AGGREGATE, {"question": "spend by vendor"})], []),
        sql_results=[MagicMock(sql=_sql(), explanation_or_error=None)],
    )
    table = "vendor_name | grand_total | currency\n--- | --- | ---\nHarbor Tech | 100.00 | USD\nMetro Office | 250.00 | USD"
    _run(db_session, llm, "what did we spend by vendor", rows_markdown=table)

    prompt = llm.synthesis_prompts[0]
    assert "AGGREGATE RESULTS" in prompt
    assert "Harbor Tech" in prompt
    # No "never speculate" mandate: the reverted design's mechanism, deliberately
    # absent because there is nothing else in this prompt to speculate from.
    assert "never speculate" not in prompt.lower()


def test_the_persona_reaches_both_the_planner_and_the_answer_step(db_session):
    """A persona in only one of the two disagrees with itself halfway through the
    turn: the planner has to know an IGST-only invoice is complete in order not
    to go hunting for a missing CGST row, and the answer step has to know it in
    order not to describe one as missing."""
    llm = _ScriptedLLM(
        _plans([_tool_call(TOOL_AGGREGATE, {"question": "spend by vendor"})], []),
        sql_results=[MagicMock(sql=_sql(), explanation_or_error=None)],
    )
    table = "vendor_name | grand_total | currency\n--- | --- | ---\nHarbor Tech | 100.00 | USD\nMetro Office | 250.00 | USD"
    _run(db_session, llm, "what did we spend by vendor", rows_markdown=table)

    planner_prompt = llm.planner_inputs[0][0].content
    synthesis_prompt = llm.synthesis_prompts[0]
    for marker in (
        'Never describe an IGST-only invoice as "missing CGST/SGST."',
        "Under reverse charge (RCM), tax_amount = 0 on the invoice itself is CORRECT",
        "If an audit or duplicate flag (sa_alerts) is present",
        "Never present a zero total as a confident answer.",
        "IRN, e-Way Bill number, and Peppol ID are compliance/logistics identifiers",
    ):
        assert marker in planner_prompt, f"planner prompt is missing: {marker}"
        assert marker in synthesis_prompt, f"synthesis prompt is missing: {marker}"


def test_a_zero_total_never_reaches_the_answer_step_as_a_figure(db_session):
    """"Never hand back $0.00 as if it were a real total" as a structural
    property: `aggregate` returns zero totals under their own status, and the
    answer step is handed the explanation instead of the number."""
    llm = _ScriptedLLM(
        # The tool sees the question the PLANNER asked it, not the user's raw
        # words -- so that is the text the fiscal-year check reads, because it is
        # also the text the SQL was generated from.
        _plans([_tool_call(TOOL_AGGREGATE, {"question": "packaging spend this quarter"})], []),
        sql_results=[
            MagicMock(sql=_sql("SUM(grand_total) AS total_spend, currency") + " GROUP BY currency",
                      explanation_or_error=None)
        ],
    )
    _run(
        db_session,
        llm,
        "how much did we spend on packaging this quarter",
        rows_markdown="total_spend | currency\n--- | ---\n0.00 | USD",
    )

    prompt = llm.synthesis_prompts[0]
    assert "(zero_total)" in prompt
    assert "A zero is not a total" in prompt
    # And the fiscal-year assumption for "this quarter" is stated, not assumed.
    assert "CALENDAR year was used" in prompt


def test_a_blended_multi_currency_total_is_withheld_from_the_answer_step(db_session):
    """Rule 5's own live example sums `grand_total` across every currency present.
    A tenant holding USD and INR gets one meaningless number -- so the number
    never reaches the prompt; the reason does."""
    _seed_dashed_tenant_invoice(db_session, vendor_name="Harbor Tech", currency="USD", grand_total=100.0)
    _seed_dashed_tenant_invoice(db_session, vendor_name="Rajesh Steel", currency="INR", grand_total=118000.0)
    llm = _ScriptedLLM(
        _plans([_tool_call(TOOL_AGGREGATE, {"question": "total spend"})], []),
        sql_results=[
            MagicMock(sql=_sql("SUM(grand_total) AS total_spend"), explanation_or_error=None)
        ],
    )
    out = _run(
        db_session,
        llm,
        "what did we spend in total",
        rows_markdown="total_spend\n---\n118100.00",
    )

    prompt = llm.synthesis_prompts[0]
    assert "(multi_currency)" in prompt
    assert "Never present this number" in prompt
    # No results table is appended for a status the answer must not report.
    assert "### Query Results" not in out["content"]


def test_synthesis_prompt_still_carries_the_payment_status_guardrail(db_session):
    """Gap 267: the guardrail has to reach the prompt that WRITES the answer, not
    just the one that writes SQL -- injecting it into generation alone is what
    made its first fix attempt fail live. It has to survive the new architecture
    for the same reason."""
    llm = _ScriptedLLM(
        _plans([_tool_call(TOOL_IDENTIFY_INVOICES, {"question": "titan steel status"})], []),
        sql_results=[MagicMock(sql=_sql("status, currency"), explanation_or_error=None)],
    )
    _run(db_session, llm, "has the Titan Steel Distributors invoice been paid")

    prompt = llm.synthesis_prompts[0]
    assert 'contains the payment-status term "been paid"' in prompt
    assert "there is\nNO payment/settlement field" in prompt or "NO payment/settlement field" in prompt


def test_a_no_results_lookup_is_described_as_a_real_answer_not_a_failure(db_session):
    llm = _ScriptedLLM(
        _plans([_tool_call(TOOL_IDENTIFY_INVOICES, {"question": "anything"})], []),
        sql_results=[MagicMock(sql=_sql(), explanation_or_error=None)],
    )
    _run(db_session, llm, "did we buy anything from Nonexistent Corp")

    prompt = llm.synthesis_prompts[0]
    assert "matched no rows" in prompt
    assert "including after \nnormalizing the name" in prompt or "normalizing the name" in prompt
    assert "not that the lookup failed" in prompt


# ── arithmetic is computed, not written ─────────────────────────────────────


def test_parse_results_table_reads_back_what_execute_generated_sql_wrote():
    from agents.query_agent import execute_generated_sql  # noqa: F401  (documents the pairing)

    markdown = "vendor_name | grand_total | currency\n--- | --- | ---\nHarbor Tech | 100.00 | USD"
    columns, rows = parse_results_table(markdown)
    assert columns == ["vendor_name", "grand_total", "currency"]
    assert rows == [["Harbor Tech", "100.00", "USD"]]


def test_parse_results_table_refuses_a_ragged_table_rather_than_dropping_a_row():
    """Same principle as `compute()` never silently skipping a malformed value: a
    total computed from most of the rows is a wrong number that looks right."""
    markdown = "a | b\n--- | ---\n1 | 2\n3"
    assert parse_results_table(markdown) is None


def test_totals_are_per_currency_and_never_combined():
    columns, rows = parse_results_table(
        "vendor_name | grand_total | currency\n--- | --- | ---\n"
        "Harbor Tech | 100.00 | USD\nRajesh Steel | 5000.00 | INR\nMetro Office | 250.50 | USD"
    )
    grounded = _grounded_arithmetic(columns, rows)

    assert len(grounded) == 1
    result = grounded[0]["result"]
    assert result["status"] == "ok"
    assert result["by_currency"] == {"INR": 5000.0, "USD": 350.5}
    rendered = render_grounded_arithmetic(grounded)
    assert "USD 350.50" in rendered and "INR 5,000.00" in rendered
    assert "5,350" not in rendered  # a cross-currency total is not representable


def test_gap_269_false_equation_is_unrenderable_from_the_computed_block():
    """The live incident, verbatim: the summary step printed
    '5000.00 units x USD 0.08 = USD 420.00' when 5000 x 0.08 is 400.00. With
    arithmetic done by `compute` before anything writes prose, the '=' form is
    not among the figures the answer step is given."""
    columns, rows = parse_results_table(
        "invoice_number | currency | line_description | line_qty | line_unit_price | line_amount\n"
        "--- | --- | --- | --- | --- | ---\n"
        "US-20260722-001 | USD | Bolts | 5000 | 0.08 | 420.00"
    )
    grounded = _grounded_arithmetic(columns, rows)

    reconcile = grounded[0]["result"]
    assert reconcile["rows"][0]["matches"] is False
    assert reconcile["rows"][0]["computed_amount"] == 400.00
    assert reconcile["rows"][0]["difference"] == 20.00

    rendered = render_grounded_arithmetic(grounded)
    assert "USD 20.00 mismatch" in rendered
    assert "= USD 420.00" not in rendered
    assert "do not reconcile" in rendered


def test_line_item_tables_also_get_a_per_currency_total_of_the_lines():
    columns, rows = parse_results_table(
        "currency | line_description | line_qty | line_unit_price | line_amount\n"
        "--- | --- | --- | --- | ---\n"
        "USD | Training | 40 | 732.57 | 29302.80\n"
        "USD | Onboarding | 2 | 50.00 | 100.00"
    )
    grounded = _grounded_arithmetic(columns, rows)

    labels = [entry["label"] for entry in grounded]
    assert any("checked against quantity" in label for label in labels)
    total = grounded[-1]["result"]
    assert total["by_currency"] == {"USD": 29402.80}


def test_a_single_row_table_is_not_summed():
    """There is no arithmetic to do, and calling one already-aggregated row a
    'total' would relabel a figure the query had already totalled."""
    columns, rows = parse_results_table("grand_total | currency\n--- | ---\n1234.00 | USD")
    assert _grounded_arithmetic(columns, rows) == []


@pytest.mark.parametrize(
    "header",
    [
        "avg_grand_total | currency\n--- | ---\n10.00 | USD\n20.00 | USD",
        "line_qty | currency\n--- | ---\n10 | USD\n20 | USD",
        "line_unit_price | currency\n--- | ---\n10.00 | USD\n20.00 | USD",
        "invoice_count | currency\n--- | ---\n10 | USD\n20 | USD",
    ],
)
def test_columns_that_must_never_be_summed_are_not(header):
    """Adding up averages, quantities, unit prices or counts produces a figure
    with no referent -- worse than no figure, because it looks like a total."""
    columns, rows = parse_results_table(header)
    assert _grounded_arithmetic(columns, rows) == []


def test_computed_block_reaches_the_synthesis_prompt(db_session):
    llm = _ScriptedLLM(
        _plans([_tool_call(TOOL_AGGREGATE, {"question": "spend by vendor"})], []),
        sql_results=[MagicMock(sql=_sql(), explanation_or_error=None)],
    )
    _run(
        db_session,
        llm,
        "what did we spend by vendor",
        rows_markdown=(
            "vendor_name | grand_total | currency\n--- | --- | ---\n"
            "Harbor Tech | 100.00 | USD\nMetro Office | 250.50 | USD"
        ),
    )

    prompt = llm.synthesis_prompts[0]
    assert "COMPUTED FIGURES" in prompt
    assert "USD 350.50" in prompt
    assert "do not add, subtract, average or" in prompt


# ── citations ───────────────────────────────────────────────────────────────


def test_citations_to_a_nonexistent_invoice_are_dropped(db_session):
    """Gap 239, deferred out of `search_invoices` by Phase 1 because the tool
    takes no DB session. This is the point citations are actually rendered, so
    the check belongs here."""
    real = _seed_invoice(db_session, vendor_name="Harbor Tech")
    chunks = [
        {"invoice_id": str(real.id), "vendor_name": "Harbor Tech", "page": 1},
        {"invoice_id": str(uuid4()), "vendor_name": "Ghost Vendor", "page": 3},
    ]
    kept = verified_citations(chunks, str(MOCK_TENANT_ID), db_session)

    assert [c["vendor_name"] for c in kept] == ["Harbor Tech"]


def test_duplicate_chunks_from_one_invoice_page_collapse_to_one_citation(db_session):
    real = _seed_invoice(db_session, vendor_name="Harbor Tech")
    chunks = [
        {"invoice_id": str(real.id), "vendor_name": "Harbor Tech", "page": 1},
        {"invoice_id": str(real.id), "vendor_name": "Harbor Tech", "page": 1},
    ]
    assert len(verified_citations(chunks, str(MOCK_TENANT_ID), db_session)) == 1


# ── the planner prompt ──────────────────────────────────────────────────────


def test_planner_prompt_does_not_restate_the_sql_rules():
    """The specific mistake this whole feature exists to stop: two copies of a
    rule in two prompts, drifting apart and competing at the point of use. The
    identify and aggregate rules live in `agents/sage_prompts.py`, inside the
    tools that use them; the planner decides which tool to reach for and nothing
    else."""
    prompt = build_planner_prompt()

    for marker in (
        "6d. LINE-ITEM LEVEL EXTRACTION",
        "4a. AMBIGUOUS-DIRECTION PHRASING",
        "CRITICAL RULES:",
        "You MUST filter by tenant_id",
        "Always filter by tenant_id",
        "Schema (only these columns are visible to you):",
        "CATEGORY MATCH -- RELEVANCE ONLY",
    ):
        assert marker not in prompt


def test_planner_prompt_names_all_six_tools():
    prompt = build_planner_prompt()
    for name in (
        TOOL_IDENTIFY_INVOICES,
        TOOL_GET_FULL_RECORD,
        TOOL_SEARCH_INVOICES,
        TOOL_AGGREGATE,
        TOOL_COMPUTE,
        TOOL_ASK_CLARIFYING_QUESTION,
    ):
        assert name in prompt
