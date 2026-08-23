"""Feature 23 Phase 3 — run the golden sample through a chat path, score it, persist it.

This is the job Phase 3 describes ("run the existing test banks on a schedule,
persist pass/fail to `agent_eval_run`"), written so it can be run three ways:
a local measurement run (what it was first used for), a nightly ACA scheduled
job against a real tenant, or a one-off comparison of two paths.

WHAT IS REAL AND WHAT IS NOT in the default (`--fixture seeded-sqlite`) mode,
stated plainly, same as `tests/run_agentic_sage_live.py` does:

  * REAL: the configured Azure OpenAI deployment (no mock at the LLM boundary),
    the real `run_query_agent()` / `run_agentic_sage()` entry points, the real
    SQL generation prompt and repair loop, real SQL execution, the real
    per-turn LLM-call count (counted from Phase 1's own telemetry events, not
    estimated) and real wall-clock latency.
  * NOT real: the database is a seeded in-memory SQLite holding nine invoices
    (seven incident-history rows plus the two document-length fixtures below),
    not a live Postgres tenant, because no local Postgres/Chroma/Redis is
    running. Document chunks are a fixed set (no Chroma). The Redis answer cache
    is stubbed out — not to flatter the numbers, but because with no Redis
    listening every `get_cached_answer()` call pays a TCP connect timeout that
    has nothing to do with either path's real cost, and it would land entirely
    on the default path (the agentic path deliberately never touches the cache),
    i.e. it would bias the comparison. The tenant-stats snapshot is computed
    from the seeded rows.

What the 2026-08-21 round added, and why (the numbers it produced supersede the
earlier ones and live in `docs/feature_21_architecture.md` B4):

  * **Per-call-site token attribution** (`tokens_by_agent`). A turn total cannot
    answer "what does `get_full_record` cost?", because `get_full_record` makes
    no LLM call at all — its cost lands entirely on the `sage.synthesis` prompt
    that renders its record and its document pages.
  * **Per-tool-call measurement** (`tool_calls`): wall time, result size, and for
    a full-record fetch the chunk count/characters/tokens. `chroma_client.
    get_all_invoice_chunks()` bounds nothing, so this is where that shows up.
  * **A document-length A/B** (`large_invoice_full_detail` /
    `small_invoice_full_detail`, backed by `tests/large_invoice_fixture.py`):
    the same question over an 11-page and a 1-page invoice, so the difference
    between the two turns is attributable to document length and nothing else.
  * **Tool results collected as the faithfulness evidence on the agentic path.**
    The new tool set reads the ORM row and Chroma directly, so none of its
    evidence passes through the two wrapped functions the default path uses.
    Without this every correct full-record answer would have scored a hard 0.00
    faithfulness — a harness defect that would have looked like a model result.

Known judge limitation, worth stating because this round hit it: `services/
agent_eval.py` truncates the context it shows the judge at `MAX_CONTEXT_CHARS`
(12,000). A full record of a large invoice is ~100,000 characters, so on those
cases the judge grades against the first 12,000 only and marks correct claims
drawn from later pages unsupported. Faithfulness on `large_invoice_full_detail`
is therefore not comparable to faithfulness on the small cases.

Run:
    python scripts/run_agent_eval.py --paths default,sage
    python scripts/run_agent_eval.py --paths default --cases greeting_no_tool
    python scripts/run_agent_eval.py --paths default --persist-url postgresql://...
    python scripts/run_agent_eval.py --paths default --provider azure --model gpt-4o
    python scripts/run_agent_eval.py --paths default --provider ollama --model llama3.2:latest

`--paths sage` sets `ENABLE_AGENTIC_SAGE` **on the in-process settings object
only**, for the duration of the run, and restores it afterwards. It does not
write `.env`, and it does not touch any Container App or tenant configuration:
this is measurement, not a rollout.

`--provider`/`--model` (Phase 4, 2026-08-23) is the same kind of thing for the
model itself — the substitution axis the "Model comparison" section of
`docs/feature_23_ai_control_tower.md` describes. Three properties it holds to,
because a comparison that breaks any of them is not a comparison:

  1. **Test-time only.** Nothing is written to `.env`, `os.environ` or the
     `Settings` object; `LLM_PROVIDER`/`AZURE_OPENAI_DEPLOYMENT_NAME`/
     `OLLAMA_MODEL` are read but never assigned. The override is `get_llm`
     patched to `utils.llm.build_llm(...)` in the three chat-path modules, for
     the duration of the case loop, and unwound by the context manager. The
     running application's default provider cannot be reached from here.
  2. **The judge stays fixed.** `judge_llm` is built from `get_llm()` *before*
     the override is entered, so every candidate is graded by the same grader
     against the same cases — swap the judge too and the deltas mean nothing.
     `services/agent_eval.py` re-imports `get_llm` from `utils.llm` directly
     (not through the patched module attributes), so the judge cannot be
     substituted by accident either.
  3. **A candidate run does not silently join the baseline trend.** An override
     run does not persist to `agent_eval_run` unless `--persist-candidate` is
     given, and when it does persist, every row's `notes` carries
     `model_under_test=<provider>:<model>`.

An override run refuses to fall back to `MockInvoiceLLM` (`allow_mock_fallback=
False`): a missing key or an unpulled Ollama tag has to fail loudly, because the
alternative is a results table reporting mock output under a candidate's name.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from contextlib import ExitStack, contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch
from uuid import UUID, uuid4

_BE_ROOT = Path(__file__).resolve().parent.parent
if str(_BE_ROOT) not in sys.path:
    sys.path.insert(0, str(_BE_ROOT))

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

import telemetry  # noqa: E402
from models import AgentEvalRun  # noqa: E402
from services.agent_eval import (  # noqa: E402
    collect_invoice_identifiers,
    identifiers_from_markdown,
    score_answer,
)
# Moved out of tests/ to benchmarks/ on 2026-08-23 -- `.dockerignore` excludes
# `**/tests/` from the deployed image, which is why the deleted
# `caj-agent-eval-dev` job could never actually run (ModuleNotFoundError). See
# benchmarks/__init__.py.
from benchmarks.agent_eval_golden_sample import (  # noqa: E402
    ALL_ROWS,
    CASES,
    TENANT_ID,
    GoldenCase,
    _CHUNKS,
    tenant_stats_summary,
)
from benchmarks.large_invoice_fixture import LARGE, SMALL  # noqa: E402
from benchmarks.sage_seed_fixtures import _seed  # noqa: E402
from utils.llm import SUPPORTED_LLM_PROVIDERS  # noqa: E402

logger = logging.getLogger("run_agent_eval")

OUTPUT_PATH = _BE_ROOT / "tests" / "agent_eval_output.json"

# The two path-level agent names. Deliberately in Phase 1's `chat.*` / `sage.*`
# namespace so cost telemetry and quality rows join on one vocabulary, but
# distinct from any single call site: these name a whole turn.
AGENT_DEFAULT_PATH = "chat.default_path"
AGENT_SAGE_PATH = "sage.agentic_path"

# Appended by code, not written by the model, and identical on both paths. Both
# are stripped before scoring: leaving the results table in would score the
# model's faithfulness against a block that *is* the evidence, which is a
# guaranteed 1.0 and tells you nothing.
_RESULTS_TABLE_MARKER = "\n\n### Query Results\n\n"
_CITATIONS_MARKER = "\n\n**Citations:**\n"


# ---------------------------------------------------------------------------
# Per-turn instrumentation
# ---------------------------------------------------------------------------


class _LlmCallCounter(logging.Handler):
    """Counts real model round-trips inside one turn, off Phase 1's own events.

    This is the number Feature 21's cost/latency question turns on, so it is
    counted rather than inferred from the code path: every instrumented call
    site emits exactly one `llm_agent_call` record, and each record carries the
    `llm_calls` the LangChain callback actually observed inside that block (a
    tracked block can contain more than one round-trip — `invoke_with_retry`'s
    backoff, for instance).

    `eval.*` events are excluded: the judge's own calls are billable and are
    deliberately visible in the cost rollup, but they are not part of the turn
    being measured.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.events: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        agent_name = getattr(record, "agent_name", None)
        if not agent_name or record.getMessage() != telemetry.LLM_CALL_EVENT_NAME:
            return
        if str(agent_name).startswith("eval."):
            return
        self.events.append(
            {
                "agent_name": agent_name,
                "model": getattr(record, "model", ""),
                "tokens_in": getattr(record, "tokens_in", 0),
                "tokens_out": getattr(record, "tokens_out", 0),
                "latency_ms": getattr(record, "latency_ms", 0.0),
                "status": getattr(record, "status", ""),
                # How many round-trips LangChain actually saw inside the block.
                "llm_calls": getattr(record, "llm_calls", 0),
            }
        )

    @property
    def call_count(self) -> int:
        """One per tracked block. A block whose callback saw more round-trips
        than one (a retry) counts them all."""
        return sum(max(1, int(e.get("llm_calls") or 0)) for e in self.events)

    @property
    def tokens_in(self) -> int:
        return sum(int(e.get("tokens_in") or 0) for e in self.events)

    @property
    def tokens_out(self) -> int:
        return sum(int(e.get("tokens_out") or 0) for e in self.events)

    def by_agent(self) -> dict:
        """Tokens and calls per instrumented call site, within this turn.

        Added 2026-08-21 for the new tool set. A turn total cannot answer the
        question this round was run to answer -- "what does `get_full_record`'s
        chunk dump cost?" -- because `get_full_record` makes no LLM call at all:
        its cost lands entirely on the `sage.synthesis` prompt that renders its
        record and every page of its document. Splitting the turn by agent name
        is what makes that visible.
        """
        rollup: dict[str, dict] = {}
        for event in self.events:
            name = str(event.get("agent_name"))
            entry = rollup.setdefault(
                name, {"calls": 0, "tokens_in": 0, "tokens_out": 0, "latency_ms": 0.0}
            )
            entry["calls"] += max(1, int(event.get("llm_calls") or 0))
            entry["tokens_in"] += int(event.get("tokens_in") or 0)
            entry["tokens_out"] += int(event.get("tokens_out") or 0)
            entry["latency_ms"] += float(event.get("latency_ms") or 0.0)
        for entry in rollup.values():
            entry["latency_ms"] = round(entry["latency_ms"], 1)
        return rollup


@contextmanager
def _counting_llm_calls():
    counter = _LlmCallCounter()
    loggers = [logging.getLogger(name) for name in telemetry._EVENT_LOGGER_NAMES]
    for lg in loggers:
        lg.addHandler(counter)
        lg.setLevel(logging.INFO)
    try:
        yield counter
    finally:
        for lg in loggers:
            lg.removeHandler(counter)


def count_tokens(text: str) -> int:
    """Real tokens, from the tokenizer the measured model uses.

    `o200k_base` is gpt-4o/gpt-5-family's encoding. Used only for *attributing*
    tokens to a piece of text that is not itself an LLM call (a tool's result
    block, a chunk dump). Every per-call figure this script reports comes from
    the provider's own `prompt_tokens`/`completion_tokens` via Feature 23's
    telemetry, never from this function — the two are kept separate on purpose so
    a billed number is never confused with a locally-estimated one.
    """
    if not text:
        return 0
    try:
        import tiktoken

        return len(tiktoken.get_encoding("o200k_base").encode(text))
    except Exception:  # pragma: no cover - tiktoken absent
        return len(text) // 4


class _ToolOutputRecorder:
    """Everything this turn's tools actually returned — the faithfulness evidence.

    Two collection routes, because the two paths funnel through different code:

      * default path — `execute_generated_sql` (structured results) and
        `query_invoice_chunks` (document text), wrapped rather than parsed out of
        the answer.
      * agentic path — every `_ToolBox.dispatch()` result, whole. This had to be
        added for the new tool set (2026-08-21): `get_full_record` reads the ORM
        row and `get_all_invoice_chunks()` directly, so **none** of its evidence
        passes through either wrapped function, and a faithfulness score computed
        without it would have been "claims asserted with no tool context at all",
        i.e. a hard 0.00 for every correct detail answer. That is a harness
        defect, not a model result, and it would have silently poisoned this
        round's quality numbers.

    The dispatch route also carries the per-call cost measurements: wall time,
    result size, and for `get_full_record` the chunk count/characters/tokens that
    are the whole reason this round exists.
    """

    def __init__(self) -> None:
        self.sql_results: list[str] = []
        self.chunks: list[dict] = []
        self.tool_calls: list[dict] = []
        self.tool_contexts: list[str] = []
        self.queries: list[str] = []
        self.fetched_ids: set[str] = set()

    def context(self) -> str:
        if self.tool_contexts:
            # The agentic path: the tools' own results are the evidence set.
            return "\n\n".join(self.tool_contexts)
        parts = []
        for markdown in self.sql_results:
            parts.append(f"DATABASE RESULTS:\n{markdown}")
        for chunk in self.chunks:
            document = chunk.get("document") or ""
            parts.append(f"DOCUMENT CHUNK:\n{document}")
        return "\n\n".join(parts)

    def executed_queries(self) -> str:
        """What was *asked for*, as opposed to what came back.

        Added 2026-08-21 for `services/agent_eval.py`'s judge failure mode 3. An
        empty results table says nothing about which vendor or period was
        searched, so a correct "no records for Nonexistent Holdings" answer was
        being scored 0.00 faithfulness against evidence that could not possibly
        support it. The query is the missing half of that evidence.
        """
        return "\n".join(self.queries)

    def fetched_invoice_numbers(self) -> set[str]:
        """Which invoices the context builder actually pulled, for `context_score`.

        Two extraction routes, because the two paths leave different traces: the
        agentic path's tool results are structures (walked by key name), and the
        default path's evidence is a rendered markdown table (read by column
        header). Both are deterministic — nothing here is pattern-matched out of
        prose, which would happily collect a PO number or a date.
        """
        return set(self.fetched_ids)


def _measure_tool_result(name: str, result_dict: dict) -> dict:
    """Size one tool result the way the synthesis prompt will actually carry it."""
    measured: dict[str, Any] = {}
    record = result_dict.get("record") or {}
    chunks = result_dict.get("chunks") or []
    if record:
        rendered = json.dumps(record, indent=2, default=str)
        measured["record_chars"] = len(rendered)
        measured["record_tokens"] = count_tokens(rendered)
    if chunks:
        document_text = "\n".join(
            f"--- PAGE {chunk.get('page')} ---\n{chunk.get('document')}" for chunk in chunks
        )
        measured["chunk_count"] = len(chunks)
        measured["chunk_chars"] = len(document_text)
        measured["chunk_tokens"] = count_tokens(document_text)
    markdown = result_dict.get("results_markdown") or ""
    if markdown:
        measured["results_markdown_chars"] = len(markdown)
        measured["results_markdown_tokens"] = count_tokens(markdown)
    whole = json.dumps(result_dict, default=str)
    measured["result_json_chars"] = len(whole)
    measured["result_json_tokens"] = count_tokens(whole)
    return measured


def _evidence_text(name: str, args: dict, result_dict: dict) -> str:
    """One tool result, rendered for the faithfulness judge.

    Deliberately close to what `_synthesize_node()` puts in front of the model:
    the judge has to grade the answer against the evidence the answer was written
    from, not against a summary of it.
    """
    status = result_dict.get("status")
    header = f"TOOL {name} (status={status})"
    parts = [header]
    if result_dict.get("candidates"):
        parts.append(json.dumps(result_dict["candidates"], indent=2, default=str))
    if result_dict.get("record"):
        parts.append(json.dumps(result_dict["record"], indent=2, default=str))
    for chunk in result_dict.get("chunks") or []:
        parts.append(f"--- PAGE {chunk.get('page')} ---\n{chunk.get('document')}")
    if result_dict.get("results_markdown"):
        parts.append(result_dict["results_markdown"])
    if result_dict.get("formatted"):
        parts.extend(str(line) for line in result_dict["formatted"])
    if result_dict.get("question"):  # a clarification IS the turn's output
        parts.append(str(result_dict["question"]))
    if result_dict.get("message"):
        parts.append(str(result_dict["message"]))
    return "\n".join(parts)


@contextmanager
def _harness_patches(
    recorder: _ToolOutputRecorder,
    stats: str,
    chunks: list[dict],
    invoice_chunks: Optional[dict] = None,
):
    """Pin everything that is not the thing being measured."""
    from agents import query_agent
    from agents.sage_orchestrator import _ToolBox

    real_execute = query_agent.execute_generated_sql
    real_dispatch = _ToolBox.dispatch

    def _recording_execute(sql, tenant_id, db_session, snapshot=None):
        result = real_execute(sql, tenant_id, db_session, snapshot=snapshot)
        recorder.sql_results.append(str(result))
        recorder.queries.append(f"SQL EXECUTED:\n{sql}")
        recorder.fetched_ids |= identifiers_from_markdown(str(result))
        return result

    def _recording_chunks(tenant_id, query, limit=5):
        recorder.chunks.extend(chunks)
        recorder.queries.append(f"DOCUMENT SEARCH: query={query!r}, limit={limit}")
        return list(chunks)

    def _fixture_invoice_chunks(invoice_id, tenant_id):
        """Stand in for `chroma_client.get_all_invoice_chunks()` — same shape, no
        Chroma. Deliberately NOT bounded here: the point of the run is to measure
        what the real function's unbounded return costs."""
        return list((invoice_chunks or {}).get(str(invoice_id).replace("-", ""), []))

    def _recording_dispatch(self, name, args):
        started = time.perf_counter()
        # Recorded before the call, so a tool that raises still leaves a record
        # of what was asked for -- see `_ToolOutputRecorder.executed_queries()`.
        recorder.queries.append(f"TOOL CALL: {name}({json.dumps(args, default=str)})")
        try:
            result = real_dispatch(self, name, args)
        except Exception as e:
            recorder.tool_calls.append(
                {
                    "tool": name,
                    "args": args,
                    "status": "raised",
                    "error": f"{type(e).__name__}: {e}",
                    "duration_ms": round((time.perf_counter() - started) * 1000.0, 1),
                }
            )
            raise
        duration_ms = (time.perf_counter() - started) * 1000.0
        result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
        entry = {
            "tool": name,
            "args": args,
            "status": result_dict.get("status"),
            "duration_ms": round(duration_ms, 1),
        }
        entry.update(_measure_tool_result(name, result_dict))
        recorder.tool_calls.append(entry)
        recorder.tool_contexts.append(_evidence_text(name, args, result_dict))
        recorder.fetched_ids |= collect_invoice_identifiers(result_dict)
        recorder.fetched_ids |= identifiers_from_markdown(
            str(result_dict.get("results_markdown") or "")
        )
        return result

    with ExitStack() as stack:
        for target in (
            patch("agents.query_agent.execute_generated_sql", _recording_execute),
            patch("agents.query_agent.query_invoice_chunks", _recording_chunks),
            patch("agents.query_tools.query_invoice_chunks", _recording_chunks),
            # New for the rewritten tool set: `get_full_record` fetches document
            # pages through this, not through `query_invoice_chunks`, so without
            # this patch every full-record fetch would reach a Chroma that is not
            # running and come back empty — the document half of the tool would go
            # unmeasured while looking like it had been measured.
            patch("agents.query_tools.get_all_invoice_chunks", _fixture_invoice_chunks),
            patch.object(_ToolBox, "dispatch", _recording_dispatch),
            # No Redis locally; see the module docstring for why this is stubbed
            # rather than left to time out.
            patch("agents.query_agent.get_cached_answer", return_value=None),
            patch("agents.query_agent.set_cached_answer"),
            # The ORM snapshot query returns an empty tenant against this
            # fixture (dashed-UUID rows, inserted that way on purpose), which
            # would hand the planner a "you have no invoices" grounding fact.
            patch("agents.query_agent._get_tenant_stats_summary", return_value=stats),
            patch("agents.query_tools._get_tenant_stats_summary", return_value=stats),
            patch("agents.sage_orchestrator._get_tenant_stats_summary", return_value=stats),
        ):
            stack.enter_context(target)
        yield


@contextmanager
def _agentic_sage_enabled(enabled: bool):
    """Flip `ENABLE_AGENTIC_SAGE` on the in-process settings object only.

    Mutating the cached `Settings` instance, not `os.environ` and not `.env`:
    the flag is read as `get_settings().ENABLE_AGENTIC_SAGE` at the top of
    `run_query_agent()`, so this exercises the real branch — the same thing that
    would happen in production if the flag moved — while remaining a
    process-local change that disappears when the script exits.
    """
    from config import get_settings

    settings = get_settings()
    previous = settings.ENABLE_AGENTIC_SAGE
    settings.ENABLE_AGENTIC_SAGE = enabled
    try:
        yield
    finally:
        settings.ENABLE_AGENTIC_SAGE = previous


# The three modules the two chat paths actually resolve `get_llm` through, read
# off the code rather than assumed: `agents/query_agent.py` (classification, SQL
# generation, every synthesis call on the default path), `agents/query_tools.py`
# (the rewritten tool set's own generation calls) and
# `agents/sage_orchestrator.py` (planner + synthesis). Each does
# `from utils.llm import get_llm`, so the module attribute is the binding that
# has to be replaced — patching `utils.llm.get_llm` would miss all three.
#
# Deliberately NOT in this list: `services/agent_eval.py` (the judge, which must
# stay on the baseline model), and every non-chat call site
# (`agents/extraction_agent.py`, `agents/trainer_agent.py`, `routers/*`) — this
# harness does not exercise them, and substituting a model in a module this run
# never calls would be a claim the output could not support.
CANDIDATE_LLM_PATCH_TARGETS = (
    "agents.query_agent.get_llm",
    "agents.query_tools.get_llm",
    "agents.sage_orchestrator.get_llm",
)


def default_output_path(model_under_test: Optional[str]) -> str:
    """Where a run writes when `--out` was not given.

    A baseline run keeps `tests/agent_eval_output.json` — the file the nightly
    job produces and the one Feature 21's B4 figures were read out of. A
    substitution run gets its own `..._<provider>_<model>.json`, because
    silently overwriting the baseline with a candidate's numbers would destroy
    the very thing the candidate is being compared against.
    """
    if not model_under_test:
        return str(OUTPUT_PATH)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", model_under_test).strip("_").lower()
    return str(OUTPUT_PATH.with_name(f"{OUTPUT_PATH.stem}_{slug}{OUTPUT_PATH.suffix}"))


def describe_model_under_test(provider: Optional[str], model: Optional[str]) -> Optional[str]:
    """`provider:model` for the run's output, or None when nothing is overridden.

    None is the signal used everywhere else in the script that this run measured
    the application's own configured model — it is never rendered as a string
    like "default", because a comparison table needs the baseline row to name
    the model it actually ran.
    """
    if not provider and not model:
        return None
    from config import get_settings

    settings = get_settings()
    resolved_provider = (provider or getattr(settings, "LLM_PROVIDER", "mock")).lower()
    if model:
        resolved_model = model
    elif resolved_provider == "ollama":
        resolved_model = settings.OLLAMA_MODEL
    elif resolved_provider == "azure":
        resolved_model = settings.AZURE_OPENAI_DEPLOYMENT_NAME
    else:
        resolved_model = resolved_provider
    return f"{resolved_provider}:{resolved_model}"


@contextmanager
def _candidate_model(
    provider: Optional[str], model: Optional[str], api_version: Optional[str] = None
):
    """Run the product's chat paths against one named provider/model, this run only.

    Same discipline as `_agentic_sage_enabled` above: a process-local
    substitution that disappears when the block exits. It replaces the
    `get_llm` *binding* in the chat-path modules with a factory closed over
    `build_llm(provider, model=...)`, so the real call sites keep calling
    `get_llm(max_tokens=...)` exactly as they do in production and receive a
    client for the candidate instead of the configured default. No setting is
    mutated, so nothing here can outlive the process or reach a deployed app.

    A no-op (yields None, patches nothing) when neither flag was passed, so the
    baseline run's code path is bit-for-bit what it was before this existed.
    """
    if not provider and not model:
        yield None
        return

    from config import get_settings
    from utils.llm import build_llm

    resolved_provider = (provider or getattr(get_settings(), "LLM_PROVIDER", "mock")).lower()
    label = describe_model_under_test(provider, model)

    def _override_get_llm(max_tokens: int | None = None):
        # `allow_mock_fallback=False`: see the module docstring. A candidate that
        # cannot be constructed must stop the run, not quietly become the mock.
        return build_llm(
            resolved_provider,
            model=model,
            max_tokens=max_tokens,
            api_version=api_version,
            allow_mock_fallback=False,
        )

    # Constructed once up front so a bad provider/model/key fails before any
    # case runs, rather than 20 turns into a paid run.
    _override_get_llm()

    with ExitStack() as stack:
        for target in CANDIDATE_LLM_PATCH_TARGETS:
            stack.enter_context(patch(target, _override_get_llm))
        yield label


def _split_appended_blocks(content: str) -> tuple[str, str]:
    """Separate the model's own prose from the blocks code appends after it."""
    prose = content or ""
    appended = []
    for marker in (_RESULTS_TABLE_MARKER, _CITATIONS_MARKER):
        if marker in prose:
            prose, tail = prose.split(marker, 1)
            appended.append(marker.strip() + "\n" + tail)
    return prose.strip(), "\n\n".join(appended)


# ---------------------------------------------------------------------------
# One turn
# ---------------------------------------------------------------------------


def run_turn(
    case: GoldenCase,
    path: str,
    session,
    stats: str,
    chunks: list[dict],
    invoice_chunks: Optional[dict] = None,
    model_under_test: Optional[str] = None,
) -> dict:
    """One real turn through one path, measured. Never raises — a failure is data.

    `model_under_test` is recorded, not applied — the substitution itself is the
    `_candidate_model()` block the caller is already inside. Carrying it on the
    turn means the output JSON says which model produced each answer instead of
    that being knowable only from the command line that was typed.
    """
    from agents.query_agent import run_query_agent

    recorder = _ToolOutputRecorder()
    session_id = str(uuid4())

    started = time.perf_counter()
    error: Optional[str] = None
    result: dict[str, Any] = {}
    with _counting_llm_calls() as counter:
        with _harness_patches(recorder, stats, chunks, invoice_chunks):
            with _agentic_sage_enabled(path == "sage"):
                try:
                    result = run_query_agent(session_id, case.question, TENANT_ID, session)
                except Exception as e:  # a harness failure is data too
                    error = f"{type(e).__name__}: {e}"
                    logger.exception("Turn raised for %s/%s", case.case_id, path)
    latency_ms = (time.perf_counter() - started) * 1000.0

    content = result.get("content") or ""
    prose, appended = _split_appended_blocks(content)
    return {
        "case_id": case.case_id,
        "path": path,
        "agent_name": AGENT_SAGE_PATH if path == "sage" else AGENT_DEFAULT_PATH,
        # None means "the application's own configured model", not "unknown".
        "model_under_test": model_under_test,
        "question": case.question,
        "answer": content,
        "answer_prose": prose,
        "appended_blocks": appended,
        "context": recorder.context(),
        # The other half of the faithfulness evidence: what was asked for, not
        # just what came back. See `_ToolOutputRecorder.executed_queries()`.
        "executed_queries": recorder.executed_queries(),
        # Deterministic input to `context_score` — see `fetched_invoice_numbers()`.
        "fetched_invoice_numbers": sorted(recorder.fetched_invoice_numbers()),
        "generated_sql": result.get("generated_sql"),
        "citations": result.get("citations") or [],
        "agentic": result.get("agentic"),
        "latency_ms": round(latency_ms, 1),
        "llm_call_count": counter.call_count,
        "llm_events": counter.events,
        "tokens_in": counter.tokens_in,
        "tokens_out": counter.tokens_out,
        # Added 2026-08-21: a turn total says nothing about which call site or
        # which tool result the tokens came from, and that attribution is the
        # question this round was run to answer.
        "tokens_by_agent": counter.by_agent(),
        "tool_calls": recorder.tool_calls,
        "error": error,
    }


def score_turn(turn: dict, case: GoldenCase, judge_llm, combined_judge: bool = False) -> dict:
    """Grade one measured turn. Judge calls are billable and are excluded from
    the turn's own `llm_call_count` by `_LlmCallCounter`.

    `combined_judge=True` (Feature 23 Track 2, 2026-08-23) takes the one-call
    five-metric path, which is the only one that produces
    helpfulness/tone/completeness. The two modes' faithfulness and relevance
    figures are recorded with `judge_mode` alongside them precisely because they
    are not assumed to be on the same scale — see `services/agent_eval.py`'s
    module docstring.
    """
    scores = score_answer(
        question=case.question,
        answer=turn["answer_prose"],
        context=turn["context"],
        expected_answer=case.expected_answer,
        llm=judge_llm,
        executed_queries=turn.get("executed_queries"),
        expected_invoice_ids=case.expected_invoice_numbers,
        fetched_invoice_ids=turn.get("fetched_invoice_numbers"),
        combined_judge=combined_judge,
    )
    turn.update(
        {
            "judge_mode": scores.judge_mode,
            "faithfulness_score": scores.faithfulness_score,
            "relevance_score": scores.relevance_score,
            "accuracy_score": scores.accuracy_score,
            "context_score": scores.context_score,
            "orchestration_score": scores.orchestration_score,
            "persona_score": scores.persona_score,
            # None in separate mode, which does not score them at all.
            "helpfulness_score": scores.helpfulness_score,
            "completeness_score": scores.completeness_score,
            "tone_score": scores.tone_score,
            "passed": scores.passed,
            "claims": scores.claims,
            "score_notes": scores.note_text(),
            "judge_llm_calls": scores.judge_llm_calls,
        }
    )
    return turn


def persist(turns: list[dict], case_by_id: dict[str, GoldenCase], persist_url: str) -> int:
    """Write one `agent_eval_run` row per turn, and mirror each as telemetry.

    The table is created from metadata if absent so a local/scratch target works;
    in a real environment it comes from alembic revision `b5d2c8a41f30`.
    """
    engine = create_engine(persist_url)
    SQLModel.metadata.create_all(engine, tables=[AgentEvalRun.__table__])
    written = 0
    with Session(engine) as session:
        for turn in turns:
            case = case_by_id[turn["case_id"]]
            notes = "; ".join(
                part
                for part in (
                    f"case={turn['case_id']}",
                    f"source={case.source}",
                    # Feature 23 Track 2: which judge produced these numbers.
                    # `AgentEvalRun` has no column for it (and none is added
                    # here -- see the run-artifact note in the feature doc), so
                    # a reader comparing two rows can still tell whether they
                    # are on the same scale.
                    f"judge_mode={turn.get('judge_mode', 'separate')}",
                    # Only present on a substitution run. A row without it was
                    # produced by the application's own configured model, which
                    # is what makes the baseline trend a baseline.
                    (
                        f"model_under_test={turn['model_under_test']}"
                        if turn.get("model_under_test")
                        else None
                    ),
                    f"sql={'yes' if turn.get('generated_sql') else 'no'}",
                    (
                        "tools=" + ",".join(turn["agentic"].get("tools_called") or [])
                        if turn.get("agentic")
                        else None
                    ),
                    (
                        "stop_reason=" + str(turn["agentic"].get("stop_reason"))
                        if turn.get("agentic") and turn["agentic"].get("stop_reason")
                        else None
                    ),
                    ("error=" + turn["error"]) if turn.get("error") else None,
                    turn.get("score_notes"),
                )
                if part
            )
            session.add(
                AgentEvalRun(
                    agent_name=turn["agent_name"],
                    run_at=datetime.utcnow(),
                    question=turn["question"],
                    expected_answer=case.expected_answer,
                    actual_answer=turn["answer"],
                    passed=bool(turn.get("passed")),
                    faithfulness_score=turn.get("faithfulness_score"),
                    relevance_score=turn.get("relevance_score"),
                    accuracy_score=turn.get("accuracy_score"),
                    context_score=turn.get("context_score"),
                    orchestration_score=turn.get("orchestration_score"),
                    persona_score=turn.get("persona_score"),
                    latency_ms=turn["latency_ms"],
                    llm_call_count=turn["llm_call_count"],
                    tenant_id=UUID(str(TENANT_ID)),
                    notes=notes[:4000],
                )
            )
            telemetry.track_eval_result(
                turn["agent_name"],
                turn["case_id"],
                bool(turn.get("passed")),
                faithfulness_score=turn.get("faithfulness_score"),
                relevance_score=turn.get("relevance_score"),
                accuracy_score=turn.get("accuracy_score"),
                context_score=turn.get("context_score"),
                orchestration_score=turn.get("orchestration_score"),
                persona_score=turn.get("persona_score"),
                latency_ms=turn["latency_ms"],
                llm_call_count=turn["llm_call_count"],
                tenant_id=str(TENANT_ID),
                tokens_in=turn.get("tokens_in"),
                tokens_out=turn.get("tokens_out"),
                # Feature 23 Track 2's three new soft metrics ride the event's
                # `**extra_attributes` rather than a schema change, so the
                # workbook can chart them without a migration. `track_eval_result`
                # drops None values, so a separate-judge run emits no field at
                # all here rather than a 0.0 that would read as a real failure.
                judge_mode=turn.get("judge_mode", "separate"),
                **{
                    key: value
                    for key, value in (
                        ("helpfulness_score", turn.get("helpfulness_score")),
                        ("completeness_score", turn.get("completeness_score")),
                        ("tone_score", turn.get("tone_score")),
                    )
                    if value is not None
                },
            )
            written += 1
        session.commit()
    engine.dispose()
    return written


def _build_invoice_chunk_map(seeded_ids: dict) -> dict:
    """`{invoice_id: [chunk, ...]}` for `get_all_invoice_chunks()`'s stand-in.

    The two document-length fixtures get their real rendered page text (one chunk
    per page, with `index_invoice_document()`'s header — see
    `tests/large_invoice_fixture.py`). The two incident-history invoices that
    have document text in `_CHUNKS` get theirs, bound to their real seeded id so
    a full-record fetch on them returns a page rather than nothing.
    """
    mapping: dict[str, list[dict]] = {}
    for spec in (LARGE, SMALL):
        invoice_id = seeded_ids.get(spec.invoice_number)
        if invoice_id:
            mapping[invoice_id] = spec.page_chunks(invoice_id)

    for chunk, invoice_number in ((_CHUNKS[0], "BRL-7702"), (_CHUNKS[1], "TSD-620458")):
        invoice_id = seeded_ids.get(invoice_number)
        if not invoice_id:
            continue
        bound = json.loads(json.dumps(chunk))
        bound["metadata"]["invoice_id"] = invoice_id
        bound["matched_by"] = "invoice_id"
        mapping[invoice_id] = [bound]
    return mapping


def summarise(turns: list[dict]) -> dict:
    """Per-path min/typical/worst — the shape Feature 21's open cost/latency
    question is asked in."""
    summary: dict[str, dict] = {}
    for path in sorted({t["path"] for t in turns}):
        rows = [t for t in turns if t["path"] == path]
        calls = sorted(t["llm_call_count"] for t in rows)
        latencies = sorted(t["latency_ms"] for t in rows)
        scored = lambda key: [t[key] for t in rows if t.get(key) is not None]  # noqa: E731

        def median(values):
            if not values:
                return None
            mid = len(values) // 2
            return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2

        def mean(values):
            return round(sum(values) / len(values), 3) if values else None

        summary[path] = {
            "turns": len(rows),
            "llm_calls_min": calls[0] if calls else None,
            "llm_calls_median": median(calls),
            "llm_calls_max": calls[-1] if calls else None,
            "llm_calls_total": sum(calls),
            "latency_ms_min": latencies[0] if latencies else None,
            "latency_ms_median": median(latencies),
            "latency_ms_max": latencies[-1] if latencies else None,
            "tokens_in_total": sum(t.get("tokens_in") or 0 for t in rows),
            "tokens_out_total": sum(t.get("tokens_out") or 0 for t in rows),
            "pass_rate": round(sum(1 for t in rows if t.get("passed")) / len(rows), 3) if rows else None,
            "faithfulness_mean": mean(scored("faithfulness_score")),
            "relevance_mean": mean(scored("relevance_score")),
            "accuracy_mean": mean(scored("accuracy_score")),
            # Component-level. Reported with their own denominators, because
            # `persona_mean` in particular is over a self-selected subset (only
            # turns that required domain judgement) and a mean without its `n`
            # would be read as covering the whole set.
            "context_mean": mean(scored("context_score")),
            "context_scored_turns": len(scored("context_score")),
            "orchestration_mean": mean(scored("orchestration_score")),
            "orchestration_scored_turns": len(scored("orchestration_score")),
            "persona_mean": mean(scored("persona_score")),
            "persona_scored_turns": len(scored("persona_score")),
            # Feature 23 Track 2 (2026-08-23). None on a separate-judge run,
            # which does not score these at all -- absent, not zero.
            "judge_mode": sorted({t.get("judge_mode") for t in rows if t.get("judge_mode")}),
            "helpfulness_mean": mean(scored("helpfulness_score")),
            "helpfulness_scored_turns": len(scored("helpfulness_score")),
            "completeness_mean": mean(scored("completeness_score")),
            "completeness_scored_turns": len(scored("completeness_score")),
            "tone_mean": mean(scored("tone_score")),
            "tone_scored_turns": len(scored("tone_score")),
            "judge_llm_calls_total": sum(t.get("judge_llm_calls") or 0 for t in rows),
            "errors": sum(1 for t in rows if t.get("error")),
            "tokens_by_agent": _agent_rollup(rows),
            # gpt-5-mini list price, the same $0.25/$2.00 per 1M the previous
            # round costed against, so the two are comparable.
            "cost_per_turn_usd": round(
                (
                    sum(t.get("tokens_in") or 0 for t in rows) * 0.25
                    + sum(t.get("tokens_out") or 0 for t in rows) * 2.00
                )
                / 1_000_000
                / len(rows),
                5,
            )
            if rows
            else None,
        }
    return summary


def _agent_rollup(rows: list[dict]) -> dict:
    """Per-call-site totals across a path's turns."""
    rollup: dict[str, dict] = {}
    for turn in rows:
        for name, entry in (turn.get("tokens_by_agent") or {}).items():
            target = rollup.setdefault(
                name, {"calls": 0, "tokens_in": 0, "tokens_out": 0, "latency_ms": 0.0}
            )
            for key in ("calls", "tokens_in", "tokens_out", "latency_ms"):
                target[key] += entry.get(key) or 0
    for entry in rollup.values():
        entry["latency_ms"] = round(entry["latency_ms"], 1)
    return rollup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", default="default", help="comma list: default,sage")
    parser.add_argument("--cases", default=None, help="comma list of case ids (default: all)")
    parser.add_argument("--persist-url", default=None, help="SQLAlchemy URL for agent_eval_run rows")
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--no-score", action="store_true", help="measure only; skip the judge")
    parser.add_argument(
        "--judge",
        default="separate",
        choices=["separate", "combined"],
        help=(
            "separate (default): faithfulness/relevance/accuracy as their own judge "
            "calls, the series every figure quoted in the docs so far is on. "
            "combined: Feature 23 Track 2's one-call five-metric judge -- also the "
            "only mode that scores helpfulness, persona/tone fit and completeness. "
            "The two are not assumed comparable; run both over the same cases "
            "before treating them as one series."
        ),
    )
    # Left as None so a substitution run can default to its own file rather
    # than overwriting the baseline output the docs quote figures from.
    parser.add_argument("--out", default=None)
    # Phase 4 substitution axis. Test-time only -- see the module docstring.
    parser.add_argument(
        "--provider",
        default=None,
        choices=list(SUPPORTED_LLM_PROVIDERS),
        help=(
            "run the chat paths against this provider for this run only, instead of "
            "LLM_PROVIDER. The judge stays on the configured default either way."
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "candidate model for this run only: an Azure deployment name (e.g. gpt-4o) "
            "or an Ollama tag (e.g. llama3.2:latest). Defaults to the named provider's "
            "configured model when --provider is given alone."
        ),
    )
    parser.add_argument(
        "--api-version",
        default=None,
        help=(
            "Azure OpenAI API version for this run only. Strict structured-output "
            "compliance needs 2024-08-01-preview or later on GPT-4o/4o-mini."
        ),
    )
    parser.add_argument(
        "--persist-candidate",
        action="store_true",
        help=(
            "allow a --provider/--model run to write agent_eval_run rows. Off by "
            "default so a candidate's scores cannot silently join the baseline "
            "quality trend; rows written this way carry model_under_test in notes."
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)

    paths = [p.strip() for p in args.paths.split(",") if p.strip()]
    selected = [c for c in CASES if not args.cases or c.case_id in args.cases.split(",")]
    case_by_id = {c.case_id: c for c in selected}
    stats = tenant_stats_summary()

    from utils.llm import get_llm

    # Built BEFORE the candidate override is entered, and from `get_llm()`, so a
    # substitution run is graded by the same judge as the baseline it will be
    # compared against. This ordering is the comparability guarantee -- see the
    # module docstring's point 2.
    judge_llm = get_llm()
    print(f"Judge/model: {type(judge_llm).__name__}")
    model_under_test = describe_model_under_test(args.provider, args.model)
    args.out = args.out or default_output_path(model_under_test)
    if model_under_test:
        print(f"Model under test (chat paths only, this run only): {model_under_test}")
        if args.api_version:
            print(f"  api_version override: {args.api_version}")
    print(f"Cases: {len(selected)}  Paths: {paths}")

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    turns: list[dict] = []
    with Session(engine) as session:
        seeded_ids = _seed(session, ALL_ROWS)
        invoice_chunks = _build_invoice_chunk_map(seeded_ids)
        for invoice_number, spec in ((LARGE.invoice_number, LARGE), (SMALL.invoice_number, SMALL)):
            pages = invoice_chunks.get(seeded_ids[invoice_number], [])
            print(
                f"fixture {invoice_number}: {len(pages)} indexed page(s), "
                f"{sum(len(p['document']) for p in pages):,} chars, "
                f"{sum(count_tokens(p['document']) for p in pages):,} tokens"
            )
        # A no-op unless --provider/--model was passed. `score_turn` runs inside
        # this block only because it is handed the already-built `judge_llm`
        # object -- it resolves no model of its own, so the override cannot
        # reach it.
        with _candidate_model(args.provider, args.model, args.api_version):
            for case in selected:
                for path in paths:
                    print(f"\n=== {case.case_id} [{path}] ===")
                    turn = run_turn(
                        case,
                        path,
                        session,
                        stats,
                        _CHUNKS,
                        invoice_chunks,
                        model_under_test=model_under_test,
                    )
                    print(
                        f"  llm_calls={turn['llm_call_count']}  latency={turn['latency_ms']:.0f}ms  "
                        f"sql={'yes' if turn['generated_sql'] else 'no'}  err={turn['error']}"
                    )
                    for call in turn["tool_calls"]:
                        print(
                            f"    tool {call['tool']} -> {call['status']} in {call['duration_ms']:.0f}ms, "
                            f"{call.get('chunk_count', 0)} chunk(s), "
                            f"{call.get('result_json_tokens', 0):,} result tokens"
                        )
                    if not args.no_score:
                        turn = score_turn(
                            turn, case, judge_llm, combined_judge=args.judge == "combined"
                        )
                        print(
                            f"  faithfulness={turn['faithfulness_score']} "
                            f"relevance={turn['relevance_score']} "
                            f"accuracy={turn['accuracy_score']} pass={turn['passed']}"
                        )
                        print(
                            f"  context={turn['context_score']} "
                            f"orchestration={turn['orchestration_score']} "
                            f"persona={turn['persona_score']}"
                        )
                        if args.judge == "combined":
                            print(
                                f"  helpfulness={turn['helpfulness_score']} "
                                f"tone={turn['tone_score']} "
                                f"completeness={turn['completeness_score']} "
                                f"(judge calls={turn['judge_llm_calls']})"
                            )
                    turns.append(turn)

    summary = summarise(turns)

    persisted = 0
    # A substitution run is opt-in for persistence. `agent_eval_run` is the
    # baseline quality trend the workbook charts; a candidate's scores landing
    # in it unannounced would show up there as a quality regression (or an
    # improvement) of the *deployed* model, which it is not.
    skip_candidate_persist = bool(model_under_test) and not args.persist_candidate
    if skip_candidate_persist:
        print(
            f"\nNot persisting: this run measured {model_under_test}, not the configured "
            "model. Pass --persist-candidate to write these rows anyway (they will carry "
            f"model_under_test={model_under_test} in notes). Results are in {args.out}."
        )
    if not args.no_persist and not skip_candidate_persist:
        target = args.persist_url
        if not target:
            from config import get_settings

            target = get_settings().DATABASE_URL
        try:
            persisted = persist(turns, case_by_id, target)
            print(f"\nPersisted {persisted} agent_eval_run rows to {target.split('@')[-1]}")
        except Exception as e:
            print(f"\nPersist FAILED ({type(e).__name__}: {e}) — results are still in {args.out}")

    payload = {
        "run_at": datetime.utcnow().isoformat(),
        "paths": paths,
        # None on a baseline run. Named here as well as per-turn so a saved
        # output file identifies itself without having to read into `turns`.
        "model_under_test": model_under_test,
        "api_version_override": args.api_version,
        # Feature 23 Track 2. Named at the top level so a saved output file
        # identifies which judge produced its figures without reading into
        # `turns`, for the same reason `model_under_test` is.
        "judge_mode": "none" if args.no_score else args.judge,
        # Stated because `summarise()`'s cost figure does NOT reprice a
        # candidate: it applies gpt-5-mini's list rate to whatever tokens were
        # burned, which makes the number a token-normalised comparison, not the
        # candidate's real bill.
        "cost_basis": "gpt-5-mini list price ($0.25/$2.00 per 1M) applied to every run",
        "summary": summary,
        "persisted_rows": persisted,
        "turns": turns,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)

    print("\n" + json.dumps(summary, indent=2))
    print(f"\nWrote {len(turns)} turns to {args.out}")


if __name__ == "__main__":
    main()
