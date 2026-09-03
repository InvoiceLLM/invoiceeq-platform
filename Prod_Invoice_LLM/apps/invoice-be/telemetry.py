"""Feature 23 (AI Control Tower) — Phase 1: one telemetry event per real LLM call.

Every LLM invocation this application makes emits exactly one Application Insights
``customEvents`` row named ``llm_agent_call``, carrying ``agent_name``, ``model``,
``tokens_in``, ``tokens_out``, ``latency_ms``, ``status``, ``tenant_id``,
``request_id`` and ``run_source``. Phase 2's cost rollup is a KQL query over
those rows — no new storage, no new Azure resource.

Instrumentation only: nothing here changes what any agent returns. Every path is
wrapped so a telemetry failure degrades to a debug log and the agent call carries
on untouched.

How it reaches Application Insights
-----------------------------------
``main.py`` (API) and ``queue_worker/main_worker.py`` (worker) already call
``configure_azure_monitor(connection_string=..., logger_name=...)`` at import when
``APPLICATIONINSIGHTS_CONNECTION_STRING`` is set — that is Feature 19 (Task 19.2)
work this module deliberately reuses rather than initialising a second SDK. That
call attaches an OpenTelemetry ``LoggingHandler`` to one specific Python logger
(``invoice_be_telemetry`` in the API, ``invoice_worker_telemetry`` in the worker),
so this module logs its event through whichever of those two loggers actually has
the handler in this process (see ``_resolve_event_logger``).

The Azure Monitor exporter maps a log record carrying the
``microsoft.custom_event.name`` attribute onto ``Microsoft.ApplicationInsights.Event``
(i.e. the ``customEvents`` table) rather than ``traces`` — that attribute name is
the exporter's own contract (``_MICROSOFT_CUSTOM_EVENT_NAME`` in
``azure/monitor/opentelemetry/exporter/_constants.py``), not something invented here.

The same record also propagates to the root logger, where Feature 19's
``StructuredJsonFormatter`` writes it to stdout as JSON — so the fields are visible
in Log Analytics container logs and in local dev even with no connection string
configured at all.

**Manual step (founder):** ``APPLICATIONINSIGHTS_CONNECTION_STRING`` must exist as a
Container App secret of that name on ``invoice-be`` and ``queue-worker`` (the bicep
in ``infra/modules/compute/`` already declares the env var + secretRef). With the
secret unset the module no-ops into stdout-only logging — it never raises.

The one thing here that is *not* a custom event (Gap 300)
---------------------------------------------------------
``tracked_llm_call()`` also opens an OpenTelemetry **CLIENT span** around the call it
wraps, which the same Azure Monitor exporter writes to ``AppDependencies`` — not
``customEvents``. That is the whole point of it: a dependency-vs-request-duration
breakdown ("how much of this turn was the model, the database, app logic?") is a join
between ``AppRequests`` and ``AppDependencies``, and no ``customEvents`` row can
participate in it. See the ``Gap 300`` constants block below for the exporter contract
that turns that span into a dependency row, and why it is emitted by hand rather than
by adding an OpenAI auto-instrumentation package.
"""

from __future__ import annotations

import json
import logging
import functools
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator, List, Optional
from urllib.parse import urlparse

from utils.logging_config import request_id_ctx, tenant_id_ctx, trace_id_ctx

logger = logging.getLogger(__name__)

# The single Application Insights customEvents name every LLM call lands under.
# Phase 2's cost KQL filters on exactly this string.
LLM_CALL_EVENT_NAME = "llm_agent_call"

# Phase 3's quality event. One row per graded golden-set answer, mirroring what
# `models.AgentEvalRun` persists to Postgres.
#
# Why both: Postgres is the durable record and the thing you can join against
# tenant data, but an Azure Monitor **workbook cannot query Postgres** -- its
# data sources are Log Analytics/App Insights, Azure Resource Graph, ARM and
# ADX. For the quality trend to sit on the same time axis as the cost trend and
# the alert timeline in one workbook (Feature 23's "the workbook must show
# trend" decision), the scores have to also exist as telemetry. This is a mirror
# of the DB row, not a second source of truth: `scripts/run_agent_eval.py`
# writes the row first and emits this second.
EVAL_RESULT_EVENT_NAME = "agent_eval_run"

# Feature 23's online-eval signals (`services/online_eval_signals.py`). One event
# per signal per computed window.
#
# Same reason as EVAL_RESULT_EVENT_NAME: those five signals are computed in SQL
# over `chat_message` / `chat_feedback` / `agent_eval_run`, and an Azure Monitor
# workbook cannot query Postgres. Without this mirror the online panel of
# `ai_control_tower.workbook.json` has no data source at all.
#
# `confidence` travels *on the event*, not just in the docs, because three of the
# five signals are a proxy/heuristic/offline-only measurement and a dashboard
# that renders all five as equally solid is worse than no dashboard.
ONLINE_SIGNAL_EVENT_NAME = "online_eval_signal"

# Feature 20 Area 1 (`services/azure_cost.py`). Real Azure *infrastructure*
# spend, which `llm_agent_call` above cannot see: that event measures LLM tokens,
# and on the live dev environment tokens are ~3% of the bill -- Container Apps,
# PostgreSQL, ACR and Log Analytics ingestion are the rest.
#
# Two names, not one, because a run produces one set of totals and a
# variable-length breakdown, and KQL cannot chart a list packed into a single
# row's customDimensions. `azure_cost_snapshot` is one row per collection run
# (MTD total, latest day, budget, forecast); `azure_cost_slice` is one row per
# service / resource type per run, so `summarize sum(amount) by name, bin(...)`
# works directly.
#
# These are emitted by `scripts/sweep_azure_cost.py` on a schedule rather than
# from a request path: the Cost Management API is heavily throttled (429s are
# routine) and the underlying data only refreshes a few times a day, so a
# per-request lookup would be both rude and pointless.
AZURE_COST_SNAPSHOT_EVENT_NAME = "azure_cost_snapshot"
AZURE_COST_SLICE_EVENT_NAME = "azure_cost_slice"

# Feature 23's two benchmark tracks (`scripts/run_extraction_benchmark.py`,
# `scripts/run_agent_eval.py`). One event per completed *run*, not per case.
#
# These exist for the same reason `azure_cost_snapshot` does: both tracks
# currently report only to stdout (the nightly job runs `--no-write`, because a
# Container Apps Job replica's filesystem is discarded on exit) or to a local
# JSON file, and an Azure Monitor workbook can query neither. Without these two
# events there is no data source at all behind a "is extraction recall drifting?"
# or "is chat quality drifting?" panel.
#
# Aggregate, not itemised, and deliberately so on both tracks:
#
#   * Track 1's unit of measurement genuinely *is* the run -- recall,
#     false-positive rate and document-level precision are ratios over the whole
#     corpus, and a per-case event could not carry any of the three.
#   * Track 2 already emits one `agent_eval_run` row per graded turn
#     (`track_eval_result` above) -- but only from `persist()`, so a
#     `--no-persist` run (which is exactly what the pre-deploy gate runs) emits
#     nothing today. This event is per path per run, so the gate's runs join the
#     same trend, and the per-turn detail lives in the blob artifact whose name
#     travels on the event.
#
# `run_label` is on both events because the same two scripts are invoked by two
# different cadences against the same telemetry resource -- the nightly job and
# the pre-deploy gate -- and a trend that silently mixed a 5-case smoke subset
# into a 20-case nightly series would show every push as a quality cliff.
EXTRACTION_BENCHMARK_EVENT_NAME = "extraction_benchmark_run"
AGENT_EVAL_SUMMARY_EVENT_NAME = "agent_eval_summary"

# Feature 24 (Ops Digest Agent) declared an `OPS_DIGEST_EVENT_NAME` here and a
# `track_ops_digest_run()` emitter below. The feature was deleted on 2026-08-25
# (Gap 311) and these two were the only artifacts the deletion missed; Gap 314
# removed them on 2026-08-26 after a repo-wide grep found zero callers. No
# `ops_digest_run` row was ever emitted from a deployed replica -- the job that
# would have called it (`caj-ops-digest-dev`) was never deployed -- so nothing
# queries this event name and no workbook panel loses a source. Full text in git
# history; closing record is `docs/be_features_tracker.md`, Feature 24/Gap 314.

# ---------------------------------------------------------------------------
# Gap 319 — the nightly recommendation pass, persisted
# ---------------------------------------------------------------------------
# Feature 20/23/24's recommendation pass (`services/ops_recommendation.py`,
# Gap 318) produces three category verdicts per nightly run and, until this
# event existed, printed them to the job's stdout and nothing else — so a
# verdict survived exactly as long as the replica did.
#
# It has to be a custom event for the same reason `agent_eval_run` and
# `online_eval_signal` are: the panel that renders it (Gap 320) is an Azure
# Monitor Workbook, and a workbook can query Log Analytics / Application
# Insights / Resource Graph / ARM / ADX — **not Postgres**. Nothing else in this
# system can hold a row a workbook can read.
#
# **One row per category per run, not one per run.** Three rows a night, the
# same choice `online_eval_signal` makes (one row per signal, not one row with
# five signals packed into it): a workbook grid is a flat row set, and
# `Category | Status | Explanation | Recommendation` is one row per category by
# construction. Packing the three into one event would force every panel to
# `mv-expand` a nested array before it could filter or colour on `status`.
#
# The three rows of one run share one `generated_at` — set once by the pass, not
# per emission — so "the latest run" is `arg_max(generated_at, ...)` over this
# stream and can never return two categories from one run and one from another.
# `TimeGenerated` is ingestion time and deliberately not used for that.
#
# `metrics` from `CategoryRecommendation` is **not** mirrored. It is unbounded
# by design (the health category carries a dict per container app) and every
# number in it already has its own event and its own panel —
# `azure_cost_snapshot` for spend, `agent_eval_summary` for the quality means,
# the live Azure Monitor metrics for CPU/memory. This event carries the verdict
# and the fields that produced it, which is what no other event can say.
OPS_RECOMMENDATION_EVENT_NAME = "ops_recommendation"

# How much of a category's prose and findings ride on the event.
#
# The binding limit is Application Insights' own: a single custom-property value
# is capped at 8,192 characters, so a `findings` blob larger than that would be
# cut *by the ingestion pipeline*, mid-string, producing a value that no longer
# parses as JSON — the silent-corruption version of the truncation this module
# already does explicitly for `chat_turn` (see `MAX_TURN_SQL_CHARS` /
# `MAX_TURN_TOOL_OUTPUT_CHARS` above). So the cut is made here, under that limit,
# and made in a way that keeps the value valid JSON: whole findings are dropped
# from the end and replaced by one marker entry of the same shape, never a
# string cut through the middle of an object.
#
# The prose fields are truncated with the same `_truncate()` marker every other
# event here uses, because `explanation` is a join of one sentence per finding
# and can grow with the number of container apps.
MAX_RECOMMENDATION_TEXT_CHARS = 2000
MAX_RECOMMENDATION_FINDING_TEXT_CHARS = 400
#: A category with more findings than this has stopped being a recommendation
#: and become the per-field dump the check-and-flag design exists to avoid; the
#: count of what was dropped still travels, as `findings_omitted`.
MAX_RECOMMENDATION_FINDINGS = 25
#: Under Application Insights' 8,192-character property cap, with headroom for
#: the marker entry appended when anything is dropped.
MAX_RECOMMENDATION_FINDINGS_CHARS = 8000

#: The two severities `services/ops_recommendation.py` grades with, restated as
#: literals here rather than imported: nothing in `telemetry.py` imports from
#: `services/`, and reversing that for two three-letter strings would put a
#: `config`-reading module import behind every LLM call site. Pinned equal to
#: their source by `tests/test_telemetry.py`, so a drift fails a test instead of
#: silently zeroing `red_count` on every event.
RECOMMENDATION_SEVERITY_RED = "red"
RECOMMENDATION_SEVERITY_YELLOW = "yellow"

# ---------------------------------------------------------------------------
# Gap 302/303 — the Trace: one event per whole chat turn
# ---------------------------------------------------------------------------
# `llm_agent_call` is per *call*. Several of them share a `trace_id` and between
# them they say a turn cost N tokens and took M ms; they cannot say what the
# agent actually did — which route ran, what SQL it wrote, what the tools
# returned, why the loop stopped. For a non-deterministic agent that is the only
# thing that diagnoses a failure, which is Feature 23's "Run, Trace, Thread"
# premise and the reason Gap 302 exists.
#
# One row per turn, emitted by the two places that own a completed turn
# (`routers/chat.py::post_chat_message` and
# `queue_worker/handlers.py::handle_process_chat_job`), after their commit. It
# fires on **every** outcome, including a declined turn, an errored turn and a
# cache hit — before this event those three produced no turn-level telemetry at
# all, so "the agent refused 400 times today" was unaskable.
#
# Gap 303 half (a) rides the same event: `turn_index` and
# `seconds_since_prev_turn` make the Thread level a `summarize ... by session_id`
# over this one stream rather than a second event type. Half (b) — session
# length / abandonment at a 30-minute idle cutoff — is then derivable in KQL from
# these two fields with no new emission and no new scheduled job; see
# `infra/monitoring/chat_thread_sessions.kql`.
CHAT_TURN_EVENT_NAME = "chat_turn"

# ---------------------------------------------------------------------------
# How much real content a `chat_turn` event carries — founder decision, 2026-08-24
# ---------------------------------------------------------------------------
# The decision was that a Trace captures the **real generated SQL text and the
# real tool-call results**, not a structural summary of them: a turn whose SQL
# was subtly wrong is not diagnosable from `sql_generated=true`.
#
# So this event genuinely carries customer-adjacent content, and the caps below
# are the only thing bounding it. They are deliberately the same two budgets
# `services/agent_eval.py` already uses for the judge prompt
# (`MAX_QUERY_CHARS = 3000` / `MAX_CONTEXT_CHARS = 12000`) rather than new
# numbers — the same two payloads, sized by the same reasoning, and a reader
# comparing an event against a judge prompt sees the same truncation.
#
# **Retention and review, stated here because nothing else states it**: these
# events land in `customEvents` in the workspace-based Application Insights
# component, i.e. in the Log Analytics workspace, and inherit *its* retention —
# `infra/06-compute-env.bicep`'s `logRetentionInDays`, which is **30 days** in
# `params.dev.json` and **90 days** in `params.prod.json`. There is no
# table-level retention override anywhere in `infra/` and no purge policy. No
# scrubbing or redaction is applied here, deliberately (the founder did not
# require it for this pass) — which is the opposite of the choice made for the
# online quality judge, whose row stores scores only. security-tester owns the
# review of that decision; it is **not** done here.
MAX_TURN_SQL_CHARS = 3000
MAX_TURN_TOOL_OUTPUT_CHARS = 12000

#: `status` on a `chat_turn`. Four outcomes, all of which really happen and only
#: one of which produced any telemetry before this event existed.
TURN_STATUS_SUCCESS = "success"
#: The model returned `sql: null` — a deliberate refusal, not a failure.
TURN_STATUS_DECLINED = "declined"
#: The route raised, or every SQL attempt failed. The user got an error string.
TURN_STATUS_ERROR = "error"
#: Served from the Redis answer cache. Excluded from any "what did the agent do"
#: analysis by construction: no model call was made and no SQL was generated, so
#: averaging these into a latency or token trend would report free turns.
TURN_STATUS_CACHE_HIT = "cache_hit"

# Exporter contract — see module docstring.
_CUSTOM_EVENT_NAME_ATTRIBUTE = "microsoft.custom_event.name"

# ---------------------------------------------------------------------------
# Gap 300 — the LLM call as an `AppDependencies` row
# ---------------------------------------------------------------------------
# `llm_agent_call` above answers "what did this call cost?". It cannot answer
# "how much of this request's duration was the model?", because it lives in
# `customEvents` and a dependency-vs-request breakdown is a join between
# `AppRequests` and `AppDependencies`. Confirmed live 2026-08-24: `AppDependencies`
# in `law-invoicellm-dev` carried exactly five DependencyTypes -- `InProc`,
# `Azure queue`, `postgresql`, `HTTP`, `Azure blob` -- and zero rows matching
# `openai`, because the Azure Monitor distro auto-instruments psycopg2/requests/
# urllib3 and the Azure SDKs but has no instrumentation for the openai/LangChain
# client path.
#
# So the span is emitted by hand, from `tracked_llm_call()` -- the wrapper that
# is already at every real LLM call site -- rather than by adding an
# `opentelemetry-instrumentation-openai*` package. Three reasons, all checked
# rather than assumed: (1) no such package is in `pyproject.toml` or `uv.lock`
# (the distro pulls in django/fastapi/flask/logging/psycopg2/requests/urllib/
# urllib3 and nothing else), so it would be a new dependency pinning its own
# `opentelemetry-instrumentation` against the one the Azure distro owns;
# (2) it patches the `openai` SDK client, so it would cover neither the `ollama`
# provider nor `MockInvoiceLLM`, both of which this app really runs on; and
# (3) it sits outside the "telemetry never raises" contract everything in this
# module follows.
#
# How a hand-made span becomes a dependency row -- exporter contract, same
# status as `microsoft.custom_event.name` above, read off
# `azure/monitor/opentelemetry/exporter/export/trace/_exporter.py` (1.0.0b56):
#
#   * a span whose kind is CLIENT is exported as `RemoteDependencyData`, i.e.
#     the `AppDependencies` table (`_exporter.py:353-369`);
#   * `gen_ai.system` on that span sets `DependencyType` to
#     `"GenAI | <value>"` (`_GEN_AI_ATTRIBUTE_PREFIX`, `_exporter.py:120`), and
#     the exporter applies it *after* the HTTP/DB/messaging branches, so it wins
#     even if the span also carries HTTP attributes;
#   * `peer.service` sets `DependencyTarget`
#     (`_get_target_for_dependency_from_peer`, `export/trace/_utils.py:148`),
#     falling back to the `gen_ai.system` value when absent.
#
# The `gen_ai.*` names are OpenTelemetry semantic conventions (the
# `opentelemetry.semconv._incubating.attributes.gen_ai_attributes` module carries
# the same strings). They are written out as literals here rather than imported
# because that module is under a `_incubating` private path — the same reason
# `microsoft.custom_event.name` is a literal.
_GEN_AI_SYSTEM_ATTRIBUTE = "gen_ai.system"
_GEN_AI_OPERATION_ATTRIBUTE = "gen_ai.operation.name"
_GEN_AI_REQUEST_MODEL_ATTRIBUTE = "gen_ai.request.model"
_GEN_AI_INPUT_TOKENS_ATTRIBUTE = "gen_ai.usage.input_tokens"
_GEN_AI_OUTPUT_TOKENS_ATTRIBUTE = "gen_ai.usage.output_tokens"
_PEER_SERVICE_ATTRIBUTE = "peer.service"
_SERVER_ADDRESS_ATTRIBUTE = "server.address"
_ERROR_TYPE_ATTRIBUTE = "error.type"

# Every call this app makes is a chat completion; `embeddings` runs through
# sentence-transformers locally, not through `tracked_llm_call`.
_GEN_AI_OPERATION_CHAT = "chat"

# semconv `GenAiSystemValues` members. `mock` is not one of theirs -- it is this
# app's own honest label for a `MockInvoiceLLM` answer, for exactly the reason
# `resolve_model_name()` reports `"mock"` rather than the configured deployment:
# a fabricated call must not be indistinguishable from a real one in a rollup.
_GEN_AI_SYSTEM_AZURE_OPENAI = "az.ai.openai"
_GEN_AI_SYSTEM_OLLAMA = "ollama"
_GEN_AI_SYSTEM_MOCK = "mock"

# Instrumentation scope name on the emitted spans — what `AppDependencies` shows
# in `SDKVersion`/scope, and the string to grep for when auditing where a
# dependency row came from.
_LLM_TRACER_NAME = "invoice_be.telemetry.llm"

# The two logger names configure_azure_monitor() is called with, in the two
# processes that make LLM calls. Order matters only for the no-App-Insights
# fallback, which is stdout-only either way.
_EVENT_LOGGER_NAMES = ("invoice_be_telemetry", "invoice_worker_telemetry")

# Keys logging.Logger reserves on LogRecord; passing any of them via `extra`
# raises KeyError. Extra attributes from call sites are filtered against this.
_RESERVED_LOG_RECORD_KEYS = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "taskName", "thread", "threadName",
    }
)

_STATUS_SUCCESS = "success"
_STATUS_ERROR = "error"

# ---------------------------------------------------------------------------
# Gap 304 — `run_source`: which population of traffic a call belongs to
# ---------------------------------------------------------------------------
# `llm_agent_call` is the only source of cost and latency in this product, and
# until this field existed it had no way to say whether a given row came from a
# real user turn or from a golden-bank/benchmark eval turn. That is not a
# reporting nicety: `services/benchmark_artifacts.py::configure_run_telemetry()`
# used to attach the Azure Monitor exporter *late* (after all eval turns had
# finished) precisely so a benchmark run's own per-call events never reached
# `customEvents` — because with no discriminator they would silently be added to
# every production cost/latency number in the same dashboards.
#
# This field was the prerequisite for changing that, and **the change has since
# been made** (2026-08-24, Gap 304 half 1): both eval scripts now attach the
# exporter immediately after `configure_run_source()`, i.e. before the first
# graded turn, so an eval run's per-call events, its per-turn `agent_eval_run`
# events and its GenAI dependency spans all export tagged `golden`/`predeploy`.
# Every consumer of any of the three must therefore filter on this field:
# `| where run_source == "production"` is now a required clause in a production
# cost/latency query, not an available one.
#
# Three values, matching the three ways this app's LLM calls are really made:
#   * `production` — a real user/queue turn. The default, so every existing call
#     site is correctly tagged with no change at any of them.
#   * `golden`     — a golden-bank eval turn (`scripts/run_agent_eval.py`,
#     `scripts/run_extraction_benchmark.py`) on the nightly or an ad-hoc cadence.
#   * `predeploy`  — the same scripts run as the pre-deploy gate, over a smaller
#     subset. Kept distinct from `golden` for the same reason `run_label` is on
#     the aggregate events: a 5-case gate subset and a 20-case nightly run are
#     not one trend.
RUN_SOURCE_PRODUCTION = "production"
RUN_SOURCE_GOLDEN = "golden"
RUN_SOURCE_PREDEPLOY = "predeploy"

# Same pattern as `tenant_id_ctx`/`request_id_ctx`/`trace_id_ctx` above, and for
# the same reason: a contextvar with a safe default means the value travels to
# every emitter without being threaded through any call site's signature. It
# lives here rather than in `utils/logging_config.py` because unlike those three
# it is not a request-correlation ID — nothing outside Feature 23's telemetry
# reads it.
run_source_ctx: ContextVar[str] = ContextVar("run_source", default=RUN_SOURCE_PRODUCTION)


def set_run_source(run_source: str) -> str:
    """Tag every ``llm_agent_call`` this context emits from here on.

    For eval/benchmark scripts only — production sets nothing and gets
    ``production`` from the contextvar's default. Returns the value actually
    applied so the caller can print it. Never raises, same contract as every
    emitter here.
    """
    resolved = str(run_source or RUN_SOURCE_PRODUCTION)
    try:
        run_source_ctx.set(resolved)
    except Exception:  # pragma: no cover - telemetry must never break a call
        logger.debug("Could not set run_source to %s", run_source, exc_info=True)
    return resolved


def _resolve_run_source(explicit: Optional[str] = None) -> str:
    """Explicit argument wins, then the contextvar, then ``production``."""
    try:
        return str(explicit or run_source_ctx.get() or RUN_SOURCE_PRODUCTION)
    except Exception:  # pragma: no cover - telemetry must never break a call
        return RUN_SOURCE_PRODUCTION


_cached_event_logger: Optional[logging.Logger] = None


def _resolve_event_logger() -> logging.Logger:
    """The logger Azure Monitor's handler is attached to *in this process*.

    Resolved lazily rather than at import: ``main.py`` imports the routers (and
    therefore the agents, and therefore this module) on the line above the one
    that calls ``configure_azure_monitor``, so at import time neither logger has
    a handler yet. The result is only cached once a handler is genuinely present.
    """
    global _cached_event_logger
    if _cached_event_logger is not None:
        return _cached_event_logger
    for name in _EVENT_LOGGER_NAMES:
        candidate = logging.getLogger(name)
        if candidate.handlers:
            _cached_event_logger = candidate
            return candidate
    # No connection string configured (local dev, tests, CI): the record still
    # propagates to root and comes out as a structured stdout line.
    return logging.getLogger(_EVENT_LOGGER_NAMES[0])


def track_agent_call(
    agent_name: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    latency_ms: float,
    status: str,
    tenant_id: str,
    request_id: Optional[str] = None,
    **extra_attributes: Any,
) -> None:
    """Emit one ``llm_agent_call`` Application Insights custom event.

    Never raises. ``tenant_id``/``request_id`` fall back to the contextvars
    Feature 19's ``TracingAndLoggingMiddleware`` (API) and ``main_worker`` (queue)
    already populate, so this event correlates with the existing structured log
    lines on the same IDs rather than inventing a second scheme.

    ``run_source`` (Gap 304) is resolved the same way, from ``run_source_ctx``,
    defaulting to ``production``. It can also be passed explicitly as a keyword —
    handled before the ``extra_attributes`` loop below, which would otherwise
    drop it as a duplicate key and leave a call site silently mis-tagged.
    """
    try:
        run_source = _resolve_run_source(extra_attributes.pop("run_source", None))
        attributes: Dict[str, Any] = {
            "agent_name": agent_name,
            "model": model or "unknown",
            "tokens_in": int(tokens_in or 0),
            "tokens_out": int(tokens_out or 0),
            "tokens_total": int(tokens_in or 0) + int(tokens_out or 0),
            "latency_ms": round(float(latency_ms or 0.0), 2),
            "status": status or _STATUS_SUCCESS,
            "tenant_id": str(tenant_id or tenant_id_ctx.get() or ""),
            "request_id": str(request_id or request_id_ctx.get() or ""),
            "trace_id": str(trace_id_ctx.get() or ""),
            "run_source": run_source,
        }
        for key, value in extra_attributes.items():
            if value is None or key in _RESERVED_LOG_RECORD_KEYS or key in attributes:
                continue
            attributes[key] = value

        # Gap 302: if this call happened inside a chat turn, it is part of that
        # turn's cost. Done here rather than in `tracked_llm_call()` so a call
        # site that emits the event directly is counted too, and inside the
        # existing `try` so the never-raises contract already covers it.
        turn = _chat_turn_ctx.get()
        if turn is not None:
            turn.record_llm_call(agent_name, attributes["tokens_in"], attributes["tokens_out"])

        _emit_event(LLM_CALL_EVENT_NAME, attributes)
    except Exception:  # pragma: no cover - telemetry must never break a call
        logger.debug("track_agent_call failed for agent %s", agent_name, exc_info=True)


def _emit_event(event_name: str, attributes: Dict[str, Any]) -> None:
    """Log one record shaped so both consumers read it: Application Insights'
    exporter (via ``microsoft.custom_event.name``) and Feature 19's
    ``StructuredJsonFormatter`` on stdout (via ``extra_fields``)."""
    _resolve_event_logger().info(
        event_name,
        extra={
            _CUSTOM_EVENT_NAME_ATTRIBUTE: event_name,
            # Flat, so each field is its own customDimensions entry in
            # Application Insights...
            **attributes,
            # ...and nested, because Feature 19's StructuredJsonFormatter
            # reads exactly this key when the same record reaches stdout.
            "extra_fields": attributes,
        },
    )


def track_eval_result(
    agent_name: str,
    case_id: str,
    passed: bool,
    *,
    faithfulness_score: Optional[float] = None,
    relevance_score: Optional[float] = None,
    accuracy_score: Optional[float] = None,
    context_score: Optional[float] = None,
    orchestration_score: Optional[float] = None,
    persona_score: Optional[float] = None,
    latency_ms: float = 0.0,
    llm_call_count: int = 0,
    tenant_id: str = "",
    **extra_attributes: Any,
) -> None:
    """Emit one ``agent_eval_run`` custom event — the telemetry mirror of an
    ``AgentEvalRun`` row (see ``EVAL_RESULT_EVENT_NAME`` for why both exist).

    Never raises, same contract as ``track_agent_call``: a nightly quality job
    must not fail because telemetry was unavailable.

    ``run_source`` (Gap 304) is resolved here exactly as ``track_agent_call``
    resolves it — from ``run_source_ctx``, with an explicit keyword winning —
    rather than being left to whatever a caller happens to pass through
    ``**extra_attributes``. It has to be first-class for the same reason it does
    on ``llm_agent_call``: once the exporter attaches at the *start* of an eval
    run (2026-08-24), these per-turn rows reach ``customEvents`` alongside
    production events and need the same discriminator. Popped before the
    ``extra_attributes`` loop below, which drops any key already present in the
    dict and would therefore have silently discarded an explicit value.
    """
    try:
        run_source = _resolve_run_source(extra_attributes.pop("run_source", None))
        attributes: Dict[str, Any] = {
            "agent_name": agent_name,
            "case_id": case_id,
            # Emitted as 0/1 rather than a bool: `customEvents` puts booleans in
            # `customDimensions` as strings, and a pass-rate is `avg(pass)` in
            # KQL, which needs a number it can average without a parse step.
            "pass": 1 if passed else 0,
            "latency_ms": round(float(latency_ms or 0.0), 2),
            "llm_call_count": int(llm_call_count or 0),
            "tenant_id": str(tenant_id or tenant_id_ctx.get() or ""),
            "request_id": str(request_id_ctx.get() or ""),
            "run_source": run_source,
        }
        # Absent scores stay absent -- a 0.0 would be indistinguishable from a
        # real zero in every trend chart built on this event.
        for key, value in (
            ("faithfulness_score", faithfulness_score),
            ("relevance_score", relevance_score),
            ("accuracy_score", accuracy_score),
            # Component-level (Feature 23, 2026-08-21). Same absent-stays-absent
            # rule, and it matters more here: `persona_score` is NULL on most
            # turns by design, so a 0.0 default would read as "the persona failed
            # on every greeting" in the workbook's trend.
            ("context_score", context_score),
            ("orchestration_score", orchestration_score),
            ("persona_score", persona_score),
        ):
            if value is not None:
                attributes[key] = round(float(value), 4)
        for key, value in extra_attributes.items():
            if value is None or key in _RESERVED_LOG_RECORD_KEYS or key in attributes:
                continue
            attributes[key] = value

        _emit_event(EVAL_RESULT_EVENT_NAME, attributes)
    except Exception:  # pragma: no cover - telemetry must never break a run
        logger.debug("track_eval_result failed for agent %s", agent_name, exc_info=True)


def track_online_signal(
    signal_name: str,
    *,
    value: Optional[float] = None,
    numerator: int = 0,
    denominator: int = 0,
    confidence: str = "",
    threshold: Optional[float] = None,
    breached: bool = False,
    window_days: Optional[float] = None,
    tenant_id: str = "",
    **extra_attributes: Any,
) -> None:
    """Emit one ``online_eval_signal`` custom event — the telemetry mirror of a
    ``services.online_eval_signals.SignalResult``.

    ``value`` stays absent when it is None. That is not tidiness: a None value
    from that module means "the denominator was empty, nothing was measured",
    and emitting it as 0.0 would render an ingestion outage as a perfectly
    healthy day on every chart built on this event.

    ``window_days`` is a **float**, not an int (changed with Gap 305's wiring).
    `compute_online_signals()` has always taken a window *length* in days and the
    scheduled caller has always passed a fraction of one — its 6-hour window is
    0.25 days — so the previous ``int()`` cast would have
    emitted ``window_days=0`` for every event the scheduled caller produces,
    i.e. a zero-length window, which is worse than omitting the field. Whole
    numbers still compare equal (``7.0 == 7``), so nothing that read the old
    field breaks.

    Never raises, same contract as the other two emitters.
    """
    try:
        attributes: Dict[str, Any] = {
            "signal_name": signal_name,
            "numerator": int(numerator or 0),
            "denominator": int(denominator or 0),
            "confidence": confidence or "unknown",
            # 0/1 so a KQL `avg()`/`countif()` needs no parse step, same reason
            # as `pass` on the eval event.
            "breached": 1 if breached else 0,
            "tenant_id": str(tenant_id or tenant_id_ctx.get() or ""),
        }
        if value is not None:
            attributes["value"] = round(float(value), 6)
        if threshold is not None:
            attributes["threshold"] = round(float(threshold), 6)
        if window_days is not None:
            attributes["window_days"] = round(float(window_days), 6)
        for key, extra in extra_attributes.items():
            if extra is None or key in _RESERVED_LOG_RECORD_KEYS or key in attributes:
                continue
            attributes[key] = extra

        _emit_event(ONLINE_SIGNAL_EVENT_NAME, attributes)
    except Exception:  # pragma: no cover - telemetry must never break a run
        logger.debug("track_online_signal failed for %s", signal_name, exc_info=True)


def track_azure_cost_snapshot(
    *,
    scope: str,
    currency: str,
    month_to_date_total: float,
    latest_day_amount: Optional[float] = None,
    latest_day: Optional[str] = None,
    day_over_day_change_pct: Optional[float] = None,
    budget_name: Optional[str] = None,
    budget_amount: Optional[float] = None,
    budget_current_spend: Optional[float] = None,
    budget_forecast_spend: Optional[float] = None,
    budget_percent_used: Optional[float] = None,
    budget_percent_forecast: Optional[float] = None,
    forecast_projected_total: Optional[float] = None,
    forecast_remaining: Optional[float] = None,
    collection_errors: int = 0,
    **extra_attributes: Any,
) -> None:
    """Emit one ``azure_cost_snapshot`` event — totals, budget and forecast.

    Absent values stay absent, for the same reason as ``track_online_signal``'s
    ``value``: a budget that has not been deployed, or a forecast call that lost
    a 429 race, is not "0 spend", and rendering it as one would show a healthy
    month on a chart that has no data behind it. ``collection_errors`` travels
    on the event so a partial snapshot is visible as partial in the workbook
    rather than silently reading as a quiet day.

    Never raises, same contract as every other emitter here.
    """
    try:
        attributes: Dict[str, Any] = {
            "scope": scope or "",
            "currency": currency or "",
            "month_to_date_total": round(float(month_to_date_total or 0.0), 4),
            "collection_errors": int(collection_errors or 0),
        }
        for key, value in (
            ("latest_day_amount", latest_day_amount),
            ("day_over_day_change_pct", day_over_day_change_pct),
            ("budget_amount", budget_amount),
            ("budget_current_spend", budget_current_spend),
            ("budget_forecast_spend", budget_forecast_spend),
            ("budget_percent_used", budget_percent_used),
            ("budget_percent_forecast", budget_percent_forecast),
            ("forecast_projected_total", forecast_projected_total),
            ("forecast_remaining", forecast_remaining),
        ):
            if value is not None:
                attributes[key] = round(float(value), 4)
        for key, text in (("latest_day", latest_day), ("budget_name", budget_name)):
            if text:
                attributes[key] = str(text)
        for key, value in extra_attributes.items():
            if value is None or key in _RESERVED_LOG_RECORD_KEYS or key in attributes:
                continue
            attributes[key] = value

        _emit_event(AZURE_COST_SNAPSHOT_EVENT_NAME, attributes)
    except Exception:  # pragma: no cover - telemetry must never break a run
        logger.debug("track_azure_cost_snapshot failed for %s", scope, exc_info=True)


def track_azure_cost_slice(
    *,
    dimension: str,
    dimension_value: str,
    amount: float,
    currency: str,
    scope: str = "",
    **extra_attributes: Any,
) -> None:
    """Emit one ``azure_cost_slice`` event — spend for one service/resource type.

    ``dimension`` is on the event, not implied by the caller, so a single KQL
    query can separate ``ServiceName`` rows (``Azure Container Apps``) from
    ``ResourceType`` rows (``microsoft.app/containerapps``) — the two overlap in
    meaning and would otherwise double-count in any naive ``sum()``.

    The field is ``dimension_value`` and not the obvious ``name`` because
    ``name`` is one of ``_RESERVED_LOG_RECORD_KEYS`` above: passing it through
    ``extra=`` makes ``logging`` raise, this function swallows the exception by
    contract, and the result is an event that silently never appears. Caught by
    ``tests/test_azure_cost.py`` on the first run rather than in production.

    Never raises.
    """
    try:
        attributes: Dict[str, Any] = {
            "dimension": dimension or "",
            "dimension_value": dimension_value or "unattributed",
            "amount": round(float(amount or 0.0), 4),
            "currency": currency or "",
            "scope": scope or "",
        }
        for key, value in extra_attributes.items():
            if value is None or key in _RESERVED_LOG_RECORD_KEYS or key in attributes:
                continue
            attributes[key] = value

        _emit_event(AZURE_COST_SLICE_EVENT_NAME, attributes)
    except Exception:  # pragma: no cover - telemetry must never break a run
        logger.debug(
            "track_azure_cost_slice failed for %s/%s", dimension, dimension_value, exc_info=True
        )


def track_extraction_benchmark_run(
    *,
    run_label: str,
    mode: str,
    clean_documents: int,
    seeded_cases: int,
    true_positive: int,
    false_negative: int,
    false_positive: int,
    true_negative: int,
    not_applicable: int,
    alert_recall_pct: Optional[float] = None,
    clean_false_positive_rate_pct: Optional[float] = None,
    document_level_precision_pct: Optional[float] = None,
    field_accuracy_correct: int = 0,
    field_accuracy_total: int = 0,
    field_accuracy_pct: Optional[float] = None,
    missed_cases: int = 0,
    false_positive_documents: int = 0,
    collateral_alert_types: int = 0,
    errors: int = 0,
    generated_at: str = "",
    artifact_blob: str = "",
    **extra_attributes: Any,
) -> None:
    """Emit one ``extraction_benchmark_run`` event — Track 1's scored run.

    The five raw confusion-matrix counts travel alongside the three derived
    percentages rather than instead of them. That is not redundancy: the derived
    figures are ``None`` whenever their denominator is empty (a
    ``--cases``-filtered run with no clean documents in it has no
    false-positive rate at all), and a panel that could only see the ratio would
    be unable to tell "0 clean documents were run" from "0% false positives".
    The counts also let a KQL query recompute any of the three over a *window*
    of runs, which averaging the per-run percentages would get wrong.

    Absent derived metrics stay absent, same rule and the same reason as
    ``track_azure_cost_snapshot``'s budget fields: a 0.0 recall reads as "every
    seeded issue was missed", which is the loudest possible signal, and emitting
    it for "nothing was measured" would make the alert on that panel worthless.

    ``mode`` (``verify``/``live``) and ``run_label`` (``nightly``/``predeploy``/
    ``adhoc``) are both required, because a single number here is meaningless
    without them: verify mode is deterministic and free, live mode measures the
    deployed model, and the two produce different figures over the same corpus
    by design.

    Never raises, same contract as every other emitter here.
    """
    try:
        attributes: Dict[str, Any] = {
            "run_label": run_label or "adhoc",
            "mode": mode or "unknown",
            "clean_documents": int(clean_documents or 0),
            "seeded_cases": int(seeded_cases or 0),
            "true_positive": int(true_positive or 0),
            "false_negative": int(false_negative or 0),
            "false_positive": int(false_positive or 0),
            "true_negative": int(true_negative or 0),
            "not_applicable": int(not_applicable or 0),
            "field_accuracy_correct": int(field_accuracy_correct or 0),
            "field_accuracy_total": int(field_accuracy_total or 0),
            "missed_cases": int(missed_cases or 0),
            "false_positive_documents": int(false_positive_documents or 0),
            "collateral_alert_types": int(collateral_alert_types or 0),
            "errors": int(errors or 0),
            # 0/1, same reason as `pass` on the eval event: a gate verdict is
            # `avg()`-ed into a pass rate in KQL, which needs a number.
            "gate_failed": 1 if (missed_cases or false_positive_documents or errors) else 0,
        }
        for key, value in (
            ("alert_recall_pct", alert_recall_pct),
            ("clean_false_positive_rate_pct", clean_false_positive_rate_pct),
            ("document_level_precision_pct", document_level_precision_pct),
            ("field_accuracy_pct", field_accuracy_pct),
        ):
            if value is not None:
                attributes[key] = round(float(value), 4)
        # The join back to the raw per-case detail. Empty when the upload was
        # skipped or failed -- never a fabricated path, so a workbook link that
        # is present is always a link that resolves.
        for key, text in (("generated_at", generated_at), ("artifact_blob", artifact_blob)):
            if text:
                attributes[key] = str(text)
        for key, value in extra_attributes.items():
            if value is None or key in _RESERVED_LOG_RECORD_KEYS or key in attributes:
                continue
            attributes[key] = value

        _emit_event(EXTRACTION_BENCHMARK_EVENT_NAME, attributes)
    except Exception:  # pragma: no cover - telemetry must never break a run
        logger.debug("track_extraction_benchmark_run failed for %s", mode, exc_info=True)


#: The ten scored dimensions of ``services.agent_eval.EvalScores``, in the
#: three groups that class's docstring keeps deliberately apart: answer-level
#: (the only three ``decide_pass()`` reads), component-level (the "which part of
#: the pipeline broke" decomposition), and soft-metric (combined judge only).
#: Named here so the event and the workbook agree on one vocabulary and a
#: dimension cannot be silently dropped from the mirror by a typo.
#:
#: ``context_drift`` joined the component group 2026-08-26 (Gap 307). It is
#: scored only on the multi-turn tier, and ``track_agent_eval_summary()`` skips
#: any dimension whose mean is None -- so the ``default`` bucket's event is
#: byte-for-byte what it was before this line existed, and only the
#: ``default-multiturn`` bucket carries the new attribute. No new event.
EVAL_SCORE_DIMENSIONS = (
    "faithfulness",
    "relevance",
    "accuracy",
    "context",
    "orchestration",
    "persona",
    "context_drift",
    "helpfulness",
    "completeness",
    "tone",
)


def track_agent_eval_summary(
    *,
    run_label: str,
    path: str,
    judge_mode: str,
    turns: int,
    errors: int = 0,
    pass_rate: Optional[float] = None,
    scores: Optional[Dict[str, Optional[float]]] = None,
    scored_turns: Optional[Dict[str, Optional[int]]] = None,
    llm_calls_total: int = 0,
    judge_llm_calls_total: int = 0,
    tokens_in_total: int = 0,
    tokens_out_total: int = 0,
    latency_ms_median: Optional[float] = None,
    cost_per_turn_usd: Optional[float] = None,
    model_under_test: str = "",
    generated_at: str = "",
    artifact_blob: str = "",
    **extra_attributes: Any,
) -> None:
    """Emit one ``agent_eval_summary`` event — Track 2's whole run, per path.

    One row per path per run, not per turn: ``track_eval_result`` above already
    emits the per-turn row, and this is the aggregate that turn-level event
    cannot produce — a mean over a *self-selected* subset. ``persona_score`` is
    NULL on most turns by design, so ``avg(persona_score)`` in KQL over the
    per-turn events silently averages a different denominator than the other
    eight dimensions do. That is why each mean here is emitted next to its own
    ``*_scored_turns`` count.

    A dimension that scored nothing is absent from the event entirely, not zero
    — a ``separate``-judge run does not score helpfulness/completeness/tone at
    all, and a 0.0 there would render as "the assistant was maximally unhelpful
    every night" on the exact panel this event exists to feed.

    ``judge_mode`` travels on every event because a faithfulness figure from the
    combined judge is not assumed to be on the same scale as one from the
    separate judge (see ``services/agent_eval.py``), and a trend that mixed them
    without saying so would be unreadable.

    Never raises, same contract as every other emitter here.
    """
    try:
        attributes: Dict[str, Any] = {
            "run_label": run_label or "adhoc",
            "path": path or "unknown",
            "judge_mode": judge_mode or "separate",
            "turns": int(turns or 0),
            "errors": int(errors or 0),
            "llm_calls_total": int(llm_calls_total or 0),
            "judge_llm_calls_total": int(judge_llm_calls_total or 0),
            "tokens_in_total": int(tokens_in_total or 0),
            "tokens_out_total": int(tokens_out_total or 0),
        }
        if pass_rate is not None:
            attributes["pass_rate"] = round(float(pass_rate), 4)
        if latency_ms_median is not None:
            attributes["latency_ms_median"] = round(float(latency_ms_median), 2)
        if cost_per_turn_usd is not None:
            attributes["cost_per_turn_usd"] = round(float(cost_per_turn_usd), 6)

        scores = scores or {}
        scored_turns = scored_turns or {}
        for dimension in EVAL_SCORE_DIMENSIONS:
            value = scores.get(dimension)
            if value is None:
                continue
            attributes[f"{dimension}_mean"] = round(float(value), 4)
            count = scored_turns.get(dimension)
            if count is not None:
                attributes[f"{dimension}_scored_turns"] = int(count)

        for key, text in (
            # Empty on a baseline run, and deliberately not rendered as
            # "default": a comparison table needs the baseline row to name the
            # model it actually ran, which only the run's own output can say.
            ("model_under_test", model_under_test),
            ("generated_at", generated_at),
            ("artifact_blob", artifact_blob),
        ):
            if text:
                attributes[key] = str(text)
        for key, value in extra_attributes.items():
            if value is None or key in _RESERVED_LOG_RECORD_KEYS or key in attributes:
                continue
            attributes[key] = value

        _emit_event(AGENT_EVAL_SUMMARY_EVENT_NAME, attributes)
    except Exception:  # pragma: no cover - telemetry must never break a run
        logger.debug("track_agent_eval_summary failed for path %s", path, exc_info=True)


# ---------------------------------------------------------------------------
# Gap 302 — the turn accumulator
# ---------------------------------------------------------------------------


def _truncate(text: Any, limit: int) -> str:
    """Cut `text` at `limit`, saying so in the value itself.

    Same shape as `services/agent_eval.py::_truncate` — a marker in the string,
    not a silent cut — because a reader of a `chat_turn` event has to be able to
    tell "the SQL was this" from "the SQL started like this".
    """
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n... (truncated at {limit} chars)"


class ChatTurn:
    """Everything one chat turn did, accumulated while it happens.

    Two kinds of field, filled from two directions:

      * the counters (`llm_calls`, `tokens_in`, `tokens_out`, `agents_called`)
        are incremented by `track_agent_call()` below for every
        `tracked_llm_call()` that runs inside the scope, so a turn's model cost
        is summed without any route knowing it is being counted;
      * everything else is set by `agents/query_agent.py` as the turn resolves —
        the route it picked, the SQL it wrote, what the tools returned, why it
        stopped.

    Deliberately a plain mutable object rather than a frozen record: the point is
    that the SQL branch, the RAG branch and the accumulator all write into the
    same instance during one turn without threading a return value through six
    call sites.
    """

    __slots__ = (
        "turn_id", "session_id", "tenant_id", "route", "status", "stop_reason",
        "tool_calls_made", "tools_called", "llm_calls", "tokens_in", "tokens_out",
        "agents_called", "generated_sql", "sql_attempts", "zero_result",
        "zero_result_fallback_recovered", "zero_result_diagnosis", "citation_count", "result_invoice_count",
        "tool_output", "turn_index", "seconds_since_prev_turn", "error_type",
        "drift_flags",
    )

    def __init__(self, *, session_id: str = "", tenant_id: str = "") -> None:
        #: Stable per-turn id, generated here rather than reusing the assistant
        #: `message_id`: a turn that errors before its message row is written
        #: still needs one identifier, and the message id is only known to the
        #: router, after this object is finished with.
        self.turn_id = str(uuid.uuid4())
        self.session_id = str(session_id or "")
        self.tenant_id = str(tenant_id or "")
        self.route = ""
        self.status = TURN_STATUS_SUCCESS
        self.stop_reason = ""
        self.tool_calls_made = 0
        self.tools_called: list = []
        self.llm_calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.agents_called: list = []
        self.generated_sql = ""
        self.sql_attempts = 0
        self.zero_result = False
        self.zero_result_fallback_recovered = False
        # C3 (Feature 6.1): which rung of the zero-row ladder answered, if any.
        self.zero_result_diagnosis = ""
        self.citation_count = 0
        self.result_invoice_count = 0
        self.tool_output = ""
        self.turn_index: Optional[int] = None
        self.seconds_since_prev_turn: Optional[float] = None
        self.error_type = ""
        # Gap 324: online drift heuristic flags for this turn (empty = none
        # detected), set by `agents/query_agent.py::run_query_agent()` after
        # the turn resolves. See `services/turn_drift.py`.
        self.drift_flags: list = []

    def record_llm_call(self, agent_name: str, tokens_in: int, tokens_out: int) -> None:
        """One `tracked_llm_call()` finished inside this turn."""
        self.llm_calls += 1
        self.tokens_in += int(tokens_in or 0)
        self.tokens_out += int(tokens_out or 0)
        if agent_name and agent_name not in self.agents_called:
            self.agents_called.append(str(agent_name))

    def event_fields(self) -> Dict[str, Any]:
        """The keyword arguments `track_chat_turn()` takes, as a plain dict.

        Returned to the caller on `run_query_agent()`'s result rather than
        emitted from inside the agent, because the two things this event still
        needs — the assistant `message_id` and the turn's wall clock — are only
        known to whichever of the two write paths owns the turn.
        """
        return {
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "route": self.route,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "tool_calls_made": self.tool_calls_made,
            "tools_called": ",".join(str(t) for t in self.tools_called),
            "llm_call_count": self.llm_calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "agents_called": ",".join(self.agents_called),
            "generated_sql": self.generated_sql,
            "sql_attempts": self.sql_attempts,
            "zero_result": self.zero_result,
            "zero_result_fallback_recovered": self.zero_result_fallback_recovered,
            "zero_result_diagnosis": self.zero_result_diagnosis,
            "citation_count": self.citation_count,
            "result_invoice_count": self.result_invoice_count,
            "tool_output": self.tool_output,
            "turn_index": self.turn_index,
            "seconds_since_prev_turn": self.seconds_since_prev_turn,
            "error_type": self.error_type,
            "drift_flags": ",".join(self.drift_flags),
        }


_chat_turn_ctx: ContextVar[Optional[ChatTurn]] = ContextVar("chat_turn", default=None)


@contextmanager
def chat_turn_scope(*, session_id: str = "", tenant_id: str = "") -> Iterator[ChatTurn]:
    """Count every `tracked_llm_call()` made inside this block against one turn.

    Reset in a `finally` rather than left set, unlike
    `queue_worker/main_worker.py`'s correlation contextvars: this one runs on a
    pooled thread that will serve another turn, and a leaked accumulator would
    add the next turn's model calls to this turn's totals — silently, and only
    under load, which is the worst way to find it.

    Nesting is additive on purpose: SAGE's tools call
    `run_sql_generation_loop()`, which opens its own `tracked_llm_call`, and
    those round-trips genuinely are part of this turn's cost.

    Never raises — a failure to install the accumulator degrades to "no counters
    on this turn's event", not a failed turn.
    """
    turn = ChatTurn(session_id=session_id, tenant_id=tenant_id)
    token = None
    try:
        token = _chat_turn_ctx.set(turn)
    except Exception:  # pragma: no cover - telemetry must never break a turn
        logger.debug("Could not install the chat turn accumulator", exc_info=True)
    try:
        yield turn
    finally:
        if token is not None:
            try:
                _chat_turn_ctx.reset(token)
            except Exception:  # pragma: no cover
                logger.debug("Could not reset the chat turn accumulator", exc_info=True)


def current_chat_turn() -> Optional[ChatTurn]:
    """The turn being accumulated on this context, or None outside a turn.

    None is the normal state everywhere except inside `run_query_agent()` — the
    eval harness, the ingestion pipeline and the trainer all make LLM calls that
    belong to no chat turn, and they must not be counted into one.
    """
    try:
        return _chat_turn_ctx.get()
    except Exception:  # pragma: no cover
        return None


def track_chat_turn(
    *,
    turn_id: str = "",
    session_id: str = "",
    message_id: str = "",
    route: str = "",
    status: str = TURN_STATUS_SUCCESS,
    latency_ms: float = 0.0,
    stop_reason: str = "",
    tool_calls_made: int = 0,
    tools_called: str = "",
    llm_call_count: int = 0,
    tokens_in: int = 0,
    tokens_out: int = 0,
    agents_called: str = "",
    generated_sql: str = "",
    sql_attempts: int = 0,
    zero_result: bool = False,
    zero_result_fallback_recovered: bool = False,
    zero_result_diagnosis: str = "",
    citation_count: int = 0,
    result_invoice_count: int = 0,
    tool_output: str = "",
    turn_index: Optional[int] = None,
    seconds_since_prev_turn: Optional[float] = None,
    error_type: str = "",
    tenant_id: str = "",
    drift_flags: str = "",
    **extra_attributes: Any,
) -> None:
    """Emit one ``chat_turn`` custom event — the Trace (Gap 302) for one turn.

    Never raises, same contract as every other emitter here: this fires after the
    user already has their answer, and a telemetry failure must be invisible to
    a turn that has already succeeded.

    ``generated_sql`` and ``tool_output`` carry the **real** text, truncated at
    ``MAX_TURN_SQL_CHARS``/``MAX_TURN_TOOL_OUTPUT_CHARS`` — see the constants
    block for the founder decision behind that and for the retention/security
    caveat it creates. ``tool_output_chars`` travels alongside so a reader can
    tell a short result from a truncated one without parsing the marker.

    ``trace_id``/``request_id``/``run_source`` are resolved from the contextvars
    exactly as ``track_agent_call`` resolves them, so a turn event and the
    ``llm_agent_call`` events it counted correlate on the same IDs. On the queue
    path that only works because ``handle_process_chat_job`` now binds those
    contextvars on the thread it really runs on (Gap 304's attribution fix).

    Absent ``turn_index``/``seconds_since_prev_turn`` stay absent rather than
    becoming 0: a first turn in a session genuinely has no predecessor, and a 0
    there would read as "the user sent two messages in the same instant" in
    every Thread-level query built on this event.
    """
    try:
        run_source = _resolve_run_source(extra_attributes.pop("run_source", None))
        sql_text = _truncate(generated_sql, MAX_TURN_SQL_CHARS)
        tool_text = _truncate(tool_output, MAX_TURN_TOOL_OUTPUT_CHARS)
        attributes: Dict[str, Any] = {
            "turn_id": str(turn_id or ""),
            "session_id": str(session_id or ""),
            "message_id": str(message_id or ""),
            "route": str(route or "unknown"),
            "status": str(status or TURN_STATUS_SUCCESS),
            "latency_ms": round(float(latency_ms or 0.0), 2),
            "stop_reason": str(stop_reason or ""),
            "tool_calls_made": int(tool_calls_made or 0),
            "tools_called": str(tools_called or ""),
            "llm_call_count": int(llm_call_count or 0),
            "tokens_in": int(tokens_in or 0),
            "tokens_out": int(tokens_out or 0),
            "tokens_total": int(tokens_in or 0) + int(tokens_out or 0),
            "agents_called": str(agents_called or ""),
            "sql_generated": bool(generated_sql),
            "generated_sql": sql_text,
            "sql_attempts": int(sql_attempts or 0),
            "zero_result": bool(zero_result),
            "zero_result_fallback_recovered": bool(zero_result_fallback_recovered),
            "zero_result_diagnosis": str(zero_result_diagnosis or ""),
            "citation_count": int(citation_count or 0),
            "result_invoice_count": int(result_invoice_count or 0),
            "tool_output": tool_text,
            # Pre-truncation length, so "12000 chars of results" and "the whole
            # result was 11,998 chars" are distinguishable in a query.
            "tool_output_chars": len(str(tool_output or "")),
            "error_type": str(error_type or ""),
            # Gap 324: comma-joined flag names from services/turn_drift.py's
            # heuristic, "" when none fired. Never None -- a rate query needs
            # every turn present in the denominator, not just flagged ones.
            "drift_flags": str(drift_flags or ""),
            "tenant_id": str(tenant_id or tenant_id_ctx.get() or ""),
            "request_id": str(request_id_ctx.get() or ""),
            "trace_id": str(trace_id_ctx.get() or ""),
            "run_source": run_source,
        }
        if turn_index is not None:
            attributes["turn_index"] = int(turn_index)
        if seconds_since_prev_turn is not None:
            attributes["seconds_since_prev_turn"] = round(float(seconds_since_prev_turn), 3)
        for key, value in extra_attributes.items():
            if value is None or key in _RESERVED_LOG_RECORD_KEYS or key in attributes:
                continue
            attributes[key] = value

        _emit_event(CHAT_TURN_EVENT_NAME, attributes)
    except Exception:  # pragma: no cover - telemetry must never break a turn
        logger.debug("track_chat_turn failed for route %s", route, exc_info=True)


# `track_ops_digest_run()` stood here until Gap 314 (2026-08-26) — see the note
# where `OPS_DIGEST_EVENT_NAME` was declared, above.


def _finding_entry(finding: Dict[str, Any]) -> Dict[str, Any]:
    """One `ops_recommendation.Finding` dict, bounded and JSON-safe.

    The five keys are fixed rather than copied from the input, so the array a
    workbook `mv-expand`s is homogeneous whatever a future `Finding` gains, and
    a `value` that is not a JSON scalar (a datetime, a dataclass) becomes its
    `str()` here instead of failing the whole `json.dumps` below.
    """
    value = finding.get("value")
    if not isinstance(value, (int, float, bool, str)) and value is not None:
        value = str(value)
    if isinstance(value, str):
        value = _truncate(value, MAX_RECOMMENDATION_FINDING_TEXT_CHARS)
    return {
        "field": _truncate(finding.get("field"), MAX_RECOMMENDATION_FINDING_TEXT_CHARS),
        "value": value,
        "severity": str(finding.get("severity") or ""),
        "detail": _truncate(finding.get("detail"), MAX_RECOMMENDATION_FINDING_TEXT_CHARS),
        "recommendation": _truncate(
            finding.get("recommendation"), MAX_RECOMMENDATION_FINDING_TEXT_CHARS
        ),
    }


def _omitted_marker(count: int) -> Dict[str, Any]:
    """The in-band "there were more than these" entry — same five keys.

    Same principle as `_truncate`'s marker: what was cut is stated *in the
    value*, so a reader of a `findings` array can tell a category with three
    findings from a category with three hundred.
    """
    return {
        "field": "(omitted)",
        "value": count,
        "severity": "",
        "detail": f"{count} further finding(s) omitted — this event caps `findings`",
        "recommendation": "",
    }


def _bounded_findings(findings: Optional[List[Dict[str, Any]]]) -> "tuple[str, int]":
    """``(json_text, omitted_count)`` — valid JSON, always under the cap.

    Drops **whole findings** from the end and re-serialises until it fits, rather
    than cutting the serialised string: an Application Insights property that has
    been cut mid-object is not JSON, and Gap 320's panel parses this.
    """
    entries = [f for f in (findings or []) if isinstance(f, dict)]
    kept = [_finding_entry(f) for f in entries[:MAX_RECOMMENDATION_FINDINGS]]
    omitted = len(entries) - len(kept)
    while True:
        payload = kept + ([_omitted_marker(omitted)] if omitted else [])
        text = json.dumps(payload, default=str)
        if len(text) <= MAX_RECOMMENDATION_FINDINGS_CHARS or not kept:
            return text, omitted
        kept.pop()
        omitted += 1


def track_ops_recommendation(
    *,
    category: str,
    title: str = "",
    status: str,
    explanation: str = "",
    recommendation: str = "",
    worst_severity: str = "",
    findings: Optional[List[Dict[str, Any]]] = None,
    errors: Optional[List[str]] = None,
    run_label: str = "",
    generated_at: str = "",
    **extra_attributes: Any,
) -> None:
    """Emit one ``ops_recommendation`` event — one category of one nightly pass.

    Three of these per nightly run, never one carrying three: see
    ``OPS_RECOMMENDATION_EVENT_NAME`` for why the row, not the run, is the unit.

    The counts (``finding_count``/``red_count``/``yellow_count``) travel next to
    the serialised ``findings`` for the same reason ``track_extraction_benchmark_run``
    carries its raw confusion-matrix cells next to the derived percentages: a
    panel that only had the JSON blob would have to ``parse_json`` and
    ``mv-expand`` before it could so much as count reds, and a trend over a
    *window* of runs would be unbuildable.

    ``worst_severity`` is emitted as ``""`` rather than omitted when a category
    has no findings. It is a three-value vocabulary (``red``/``yellow``/none) and
    the third value is a real, common, meaningful answer — "checked, nothing
    outside its band" — not missing data, which is what an absent field means
    everywhere else in this module.

    ``errors`` is joined into one string rather than serialised as JSON: it is a
    list of human-readable failure sentences ("container health: metrics for
    ca-invoice-be-dev: HTTPError: 403"), the panel renders it as text, and
    nothing needs to iterate it.

    No ``tenant_id`` and no ``request_id``, matching ``agent_eval_summary`` /
    ``extraction_benchmark_run`` / ``azure_cost_snapshot`` (and the deleted
    ``ops_digest_run``) rather than ``agent_eval_run`` / ``online_eval_signal``:
    this is a system-wide ops verdict produced by a scheduled job with no request
    and no tenant in scope, and an always-empty ``tenant_id`` column invites a
    join that can never match.

    Never raises, same contract as every other emitter here — and it matters as
    much as anywhere in this module, because the caller is a step bolted onto the
    end of an already-successful nightly job (Gaps 308/317).
    """
    try:
        entries = [f for f in (findings or []) if isinstance(f, dict)]
        findings_json, omitted = _bounded_findings(entries)
        problems = [str(e) for e in (errors or []) if e]
        attributes: Dict[str, Any] = {
            "run_label": run_label or "adhoc",
            "category": category or "unknown",
            "title": title or category or "unknown",
            "status": status or "unknown",
            "explanation": _truncate(explanation, MAX_RECOMMENDATION_TEXT_CHARS),
            "recommendation": _truncate(recommendation, MAX_RECOMMENDATION_TEXT_CHARS),
            "worst_severity": str(worst_severity or ""),
            "finding_count": len(entries),
            "red_count": sum(
                1 for f in entries if f.get("severity") == RECOMMENDATION_SEVERITY_RED
            ),
            "yellow_count": sum(
                1 for f in entries if f.get("severity") == RECOMMENDATION_SEVERITY_YELLOW
            ),
            "findings": findings_json,
            "findings_omitted": omitted,
            "error_count": len(problems),
            "errors": _truncate(" | ".join(problems), MAX_RECOMMENDATION_TEXT_CHARS),
        }
        # The join key across one run's three rows, and the "latest run" filter
        # Gap 320's panel sorts on. Emitted only when the caller has one, never
        # defaulted to now(): a fabricated stamp would let two runs' rows
        # interleave under a single `arg_max`.
        if generated_at:
            attributes["generated_at"] = str(generated_at)
        for key, value in extra_attributes.items():
            if value is None or key in _RESERVED_LOG_RECORD_KEYS or key in attributes:
                continue
            attributes[key] = value

        _emit_event(OPS_RECOMMENDATION_EVENT_NAME, attributes)
    except Exception:  # pragma: no cover - telemetry must never break a run
        logger.debug("track_ops_recommendation failed for %s", category, exc_info=True)


# ---------------------------------------------------------------------------
# Token capture
# ---------------------------------------------------------------------------
# LangChain's `with_structured_output(...).invoke()` returns the parsed Pydantic
# object, not the AIMessage -- so at the structured call sites (extraction, chat
# classification, SQL generation, trainer rule drafting) there is no response
# object to read `usage_metadata` off, and the alternatives all change behaviour:
# `include_raw=True` changes the returned shape, and passing `config={"callbacks":
# [...]}` into `.invoke()` changes a call signature that a dozen test doubles
# implement as `invoke(self, prompt)`.
#
# LangChain's own answer to this is a context-scoped callback registered through
# `register_configure_hook` -- the same mechanism `get_openai_callback()` uses.
# The handler is attached by the framework to every run started while the
# contextvar is set, so nothing at any call site changes: no extra argument, no
# different return value, and the test doubles (which never route through
# LangChain's callback manager at all) simply report zero tokens.

_usage_handler_ctx: ContextVar[Optional[Any]] = ContextVar("llm_usage_handler", default=None)
_hook_registered = False


class LlmUsage:
    """Token counters accumulated across the LLM runs inside one tracked block.

    Accumulates rather than overwrites: a tracked block can legitimately contain
    more than one round-trip (``invoke_with_retry``'s backoff retries, the SQL
    generate/repair loop), and the cost of that block is the sum of them.
    """

    __slots__ = ("tokens_in", "tokens_out", "llm_calls", "cached_tokens", "reasoning_tokens")

    def __init__(self) -> None:
        self.tokens_in = 0
        self.tokens_out = 0
        self.llm_calls = 0
        # B1 (Feature 6.1): the two counts every latency claim in Block A rests
        # on. `cached_tokens` is Azure's prompt-cache hit count -- A4 reorders the
        # prompt to raise it, and without this field "the prefix is cached now" is
        # an assertion, not a measurement. `reasoning_tokens` is what a reasoning
        # deployment burns before the first visible token -- A1 lowers
        # `reasoning_effort` to shrink it, and the whole 15.6s -> 5.6s projection
        # is unverifiable while it is invisible.
        self.cached_tokens = 0
        self.reasoning_tokens = 0

    def add(
        self,
        tokens_in: int,
        tokens_out: int,
        cached_tokens: int = 0,
        reasoning_tokens: int = 0,
    ) -> None:
        self.tokens_in += int(tokens_in or 0)
        self.tokens_out += int(tokens_out or 0)
        self.cached_tokens += int(cached_tokens or 0)
        self.reasoning_tokens += int(reasoning_tokens or 0)
        self.llm_calls += 1


def _detail(container: Any, group: str, key: str) -> int:
    """One nested token-detail count, or 0 when the provider did not send it.

    B1. Every field this reads is optional: a non-reasoning deployment sends no
    `completion_tokens_details`, and a prompt below Azure's 1,024-token cache
    minimum sends no `cached_tokens`. Absent must read as zero, never as a
    failure -- this runs inside the token-capture path of every LLM call.
    """
    try:
        group_value = (container or {}).get(group) or {}
        if not isinstance(group_value, dict):
            group_value = getattr(group_value, "__dict__", {}) or {}
        return int(group_value.get(key) or 0)
    except Exception:  # pragma: no cover - telemetry must never break a call
        return 0


def _record_llm_result(usage: LlmUsage, response: Any) -> None:
    """Pull prompt/completion counts off a LangChain ``LLMResult``.

    Two shapes, because providers differ on which one they populate:
    ``llm_output["token_usage"]`` (what AzureChatOpenAI returns) and the
    per-generation ``usage_metadata`` (the newer, provider-neutral field).
    """
    llm_output = getattr(response, "llm_output", None) or {}
    token_usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
    if token_usage:
        # B1: the OpenAI/Azure shape nests these one level down, and both
        # sub-objects are absent on a non-reasoning deployment or a cache miss --
        # hence `_detail()`, which treats "absent" as zero rather than as an error.
        usage.add(
            token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0,
            token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0,
            _detail(token_usage, "prompt_tokens_details", "cached_tokens"),
            _detail(token_usage, "completion_tokens_details", "reasoning_tokens"),
        )
        return

    for generation_list in getattr(response, "generations", None) or []:
        for generation in generation_list or []:
            message = getattr(generation, "message", None)
            metadata = getattr(message, "usage_metadata", None) or {}
            if metadata:
                # LangChain's provider-neutral shape spells the same two counts
                # differently: `input_token_details.cache_read` and
                # `output_token_details.reasoning`.
                usage.add(
                    metadata.get("input_tokens") or 0,
                    metadata.get("output_tokens") or 0,
                    _detail(metadata, "input_token_details", "cache_read"),
                    _detail(metadata, "output_token_details", "reasoning"),
                )


def _build_usage_handler(usage: LlmUsage) -> Optional[Any]:
    """A LangChain callback handler feeding `usage`, or None if unavailable."""
    global _hook_registered
    try:
        from langchain_core.callbacks.base import BaseCallbackHandler

        class _UsageCallbackHandler(BaseCallbackHandler):
            raise_error = False

            def __init__(self, target: LlmUsage) -> None:
                super().__init__()
                self._target = target

            def on_llm_end(self, response: Any, **kwargs: Any) -> None:
                try:
                    _record_llm_result(self._target, response)
                except Exception:  # pragma: no cover
                    logger.debug("LLM usage capture failed", exc_info=True)

        if not _hook_registered:
            from langchain_core.tracers.context import register_configure_hook

            register_configure_hook(_usage_handler_ctx, True)
            _hook_registered = True

        return _UsageCallbackHandler(usage)
    except Exception:  # pragma: no cover - langchain absent/incompatible
        logger.debug("LLM usage callback unavailable; tokens will report 0", exc_info=True)
        return None


def resolve_model_name(llm: Any = None) -> str:
    """The model/deployment that actually served the call.

    Read off the LLM object first, and only then off settings: ``get_llm()``
    silently falls back to ``MockInvoiceLLM`` when the Azure key is missing, and
    reporting the configured deployment name for a call a mock answered would put
    fabricated cost data straight into the rollup.
    """
    candidate = llm
    # `bind_tool_schemas()` (SAGE's planner) hands back a RunnableBinding wrapping
    # the chat model, so the model name is one or more `.bound` hops down.
    for _ in range(3):
        if candidate is None:
            break
        for attribute in ("deployment_name", "azure_deployment", "model_name", "model"):
            value = getattr(candidate, attribute, None)
            if isinstance(value, str) and value:
                return value
        if type(candidate).__name__ == "MockInvoiceLLM":
            return "mock"
        candidate = getattr(candidate, "bound", None)
    try:
        from config import get_settings

        settings = get_settings()
        provider = (getattr(settings, "LLM_PROVIDER", "") or "").lower()
        if provider == "azure":
            return settings.AZURE_OPENAI_DEPLOYMENT_NAME or "azure-openai"
        if provider == "ollama":
            return settings.OLLAMA_MODEL or "ollama"
        return provider or "unknown"
    except Exception:  # pragma: no cover
        return "unknown"


# ---------------------------------------------------------------------------
# Dependency span (Gap 300) — see the constants block for the exporter contract
# ---------------------------------------------------------------------------


def resolve_gen_ai_system(llm: Any = None, model: Optional[str] = None) -> str:
    """The `gen_ai.system` value for this call — what `DependencyType` becomes.

    Reads the already-resolved model name first: ``resolve_model_name()`` walks
    the ``RunnableBinding`` chain and reports ``"mock"`` for a ``MockInvoiceLLM``
    answer, so checking its output catches a wrapped mock that a bare
    ``type(llm).__name__`` check would miss.
    """
    if (model or "").strip().lower() == _GEN_AI_SYSTEM_MOCK:
        return _GEN_AI_SYSTEM_MOCK
    if type(llm).__name__ == "MockInvoiceLLM":
        return _GEN_AI_SYSTEM_MOCK
    try:
        from config import get_settings

        provider = (getattr(get_settings(), "LLM_PROVIDER", "") or "").strip().lower()
    except Exception:  # pragma: no cover - settings unavailable
        provider = ""
    if provider == "azure":
        return _GEN_AI_SYSTEM_AZURE_OPENAI
    if provider == "ollama":
        return _GEN_AI_SYSTEM_OLLAMA
    # `LLM_PROVIDER` defaults to "azure" in config.py, so this is the
    # someone-configured-something-else case; report what they configured.
    return provider or _GEN_AI_SYSTEM_AZURE_OPENAI


def resolve_gen_ai_peer(gen_ai_system: str) -> str:
    """Hostname of the endpoint that served the call — what `DependencyTarget` becomes.

    **Hostname only, deliberately**: the configured endpoint can carry a path and
    query string, and an Azure OpenAI URL's query string is a place API versions
    and (in some SDK shapes) keys travel. A dependency target is a host, so
    nothing beyond ``.hostname`` is ever read.

    Empty for a mock — there is no peer, and the exporter then falls back to the
    ``gen_ai.system`` value for the target, which is the honest answer.
    """
    if gen_ai_system == _GEN_AI_SYSTEM_MOCK:
        return ""
    try:
        from config import get_settings

        settings = get_settings()
        if gen_ai_system == _GEN_AI_SYSTEM_OLLAMA:
            endpoint = getattr(settings, "OLLAMA_BASE_URL", "") or ""
        else:
            endpoint = getattr(settings, "AZURE_OPENAI_ENDPOINT", "") or ""
        endpoint = endpoint.strip()
        if not endpoint:
            return ""
        if "://" not in endpoint:
            endpoint = "https://" + endpoint
        return urlparse(endpoint).hostname or ""
    except Exception:  # pragma: no cover - settings unavailable/unparseable
        return ""


def _start_llm_dependency_span(
    agent_name: str,
    model: Optional[str],
    *,
    llm: Any = None,
    tenant_id: Optional[str] = None,
    request_id: Optional[str] = None,
    run_source: Optional[str] = None,
) -> Optional[Any]:
    """Open one CLIENT span for an LLM call, or return ``None``.

    Started rather than entered as the *current* span on purpose. Making it
    current would mutate the OpenTelemetry context across the ``yield`` of a
    contextmanager that is used inside both sync and async call sites; starting
    it plainly still reads the current context for its **parent**, which is the
    only part that matters here — the parent is the FastAPI request span, so the
    resulting row carries the request's ``operation_Id``/``operation_ParentId``
    and the "how much of this request was the model?" breakdown works.

    Never raises. Without a configured tracer provider (local dev, tests, CI, any
    process with no ``APPLICATIONINSIGHTS_CONNECTION_STRING``) the OpenTelemetry
    API hands back a no-op tracer, and this costs an object allocation.

    Carries ``run_source`` (Gap 304) for the same reason ``llm_agent_call``
    does, and this is the load-bearing half of it: from 2026-08-24 an eval run
    attaches the exporter at *start*, so these spans land in ``AppDependencies``
    next to production dependency spans. ``run_source`` is the only field that
    tells them apart — the event-level tag protects ``customEvents`` only.
    """
    try:
        from opentelemetry import trace as _otel_trace

        gen_ai_system = resolve_gen_ai_system(llm, model)
        model_name = model or "unknown"
        attributes: Dict[str, Any] = {
            _GEN_AI_SYSTEM_ATTRIBUTE: gen_ai_system,
            _GEN_AI_OPERATION_ATTRIBUTE: _GEN_AI_OPERATION_CHAT,
            _GEN_AI_REQUEST_MODEL_ATTRIBUTE: model_name,
            # Not semconv, and the reason this is worth carrying: `DependencyType`
            # collapses every LLM call in the app to one value, so the per-feature
            # -area breakdown Gap 300 exists to unblock needs the agent name in
            # `customDimensions` to group by.
            "agent_name": agent_name,
            "tenant_id": str(tenant_id or tenant_id_ctx.get() or ""),
            "request_id": str(request_id or request_id_ctx.get() or ""),
            "run_source": _resolve_run_source(run_source),
        }
        peer = resolve_gen_ai_peer(gen_ai_system)
        if peer:
            attributes[_PEER_SERVICE_ATTRIBUTE] = peer
            attributes[_SERVER_ADDRESS_ATTRIBUTE] = peer

        return _otel_trace.get_tracer(_LLM_TRACER_NAME).start_span(
            # semconv span name for a chat completion: "{operation} {model}".
            f"{_GEN_AI_OPERATION_CHAT} {model_name}",
            kind=_otel_trace.SpanKind.CLIENT,
            attributes=attributes,
        )
    except Exception:  # pragma: no cover - telemetry must never break a call
        logger.debug("Could not start LLM dependency span for %s", agent_name, exc_info=True)
        return None


def _end_llm_dependency_span(
    span: Optional[Any],
    *,
    usage: Optional[LlmUsage] = None,
    status: str = _STATUS_SUCCESS,
    error_type: Optional[str] = None,
) -> None:
    """Close the span opened by ``_start_llm_dependency_span``.

    Token counts are only known here, after the wrapped block has run, which is
    why the span is closed by hand rather than with a ``with`` block.

    Never raises, and ends the span even if setting an attribute failed — an
    unended span is a leak in the batch processor, so the ``end()`` lives in its
    own ``finally``.
    """
    if span is None:
        return
    try:
        from opentelemetry.trace import Status, StatusCode

        if usage is not None:
            span.set_attribute(_GEN_AI_INPUT_TOKENS_ATTRIBUTE, int(usage.tokens_in))
            span.set_attribute(_GEN_AI_OUTPUT_TOKENS_ATTRIBUTE, int(usage.tokens_out))
            span.set_attribute("llm_calls", int(usage.llm_calls))
            # B1: on the span as well as the event, so an AppDependencies query
            # can compare cache hit rate against the dependency's own duration
            # without joining back to customEvents.
            span.set_attribute("cached_tokens", int(usage.cached_tokens))
            span.set_attribute("reasoning_tokens", int(usage.reasoning_tokens))
        if status == _STATUS_ERROR:
            # The exporter reads `span.status.is_ok` for the dependency's
            # `Success` column, so this is what makes a failed call show as a
            # failed dependency rather than a slow one.
            span.set_status(Status(StatusCode.ERROR, error_type or ""))
            if error_type:
                span.set_attribute(_ERROR_TYPE_ATTRIBUTE, error_type)
        else:
            span.set_status(Status(StatusCode.OK))
    except Exception:  # pragma: no cover - telemetry must never break a call
        logger.debug("Could not annotate LLM dependency span", exc_info=True)
    finally:
        try:
            span.end()
        except Exception:  # pragma: no cover
            logger.debug("Could not end LLM dependency span", exc_info=True)


@contextmanager
def tracked_llm_call(
    agent_name: str,
    *,
    llm: Any = None,
    model: Optional[str] = None,
    tenant_id: Optional[str] = None,
    request_id: Optional[str] = None,
    **extra_attributes: Any,
) -> Iterator[LlmUsage]:
    """Wrap one LLM invocation; emit its ``llm_agent_call`` event on exit.

    Times the block, captures token counts, records ``status`` as ``success`` or
    ``error``, and re-raises anything the block raised completely unchanged — so a
    call site's own error handling behaves exactly as it did before.

    Gap 300: the same block also produces one OpenTelemetry CLIENT span, which
    the Azure Monitor exporter writes to ``AppDependencies``. Two emissions, one
    wrapper, because they answer different questions — the event carries tokens
    and cost, the span carries duration *inside the parent request*.
    """
    usage = LlmUsage()
    handler = _build_usage_handler(usage)
    reset_token = _usage_handler_ctx.set(handler) if handler is not None else None

    # Resolved up front rather than in the `finally` below, because the
    # dependency span needs the model name at *start* time. The `model_name or
    # resolve_model_name(llm)` in the finally keeps the pre-Gap-300 behaviour
    # exactly if this ever came back empty.
    model_name = model
    if not model_name:
        try:
            model_name = resolve_model_name(llm)
        except Exception:  # pragma: no cover - resolve_model_name is defensive already
            model_name = None
    # `.get()`, not `.pop()`: `track_agent_call` pops it for itself below, and the
    # two surfaces must agree about the same call — a call site that passes
    # `run_source=` explicitly would otherwise tag its event and its dependency
    # span differently.
    span = _start_llm_dependency_span(
        agent_name,
        model_name,
        llm=llm,
        tenant_id=tenant_id,
        request_id=request_id,
        run_source=extra_attributes.get("run_source"),
    )

    started = time.perf_counter()
    status = _STATUS_SUCCESS
    error_type: Optional[str] = None
    try:
        yield usage
    except BaseException as exc:
        status = _STATUS_ERROR
        error_type = type(exc).__name__
        raise
    finally:
        try:
            if reset_token is not None:
                _usage_handler_ctx.reset(reset_token)
        except Exception:  # pragma: no cover
            logger.debug("Failed to reset LLM usage context", exc_info=True)
        # Closed before the event is emitted so the span's own duration stays as
        # close as possible to the `latency_ms` the event reports.
        _end_llm_dependency_span(span, usage=usage, status=status, error_type=error_type)
        track_agent_call(
            agent_name,
            model_name or resolve_model_name(llm),
            usage.tokens_in,
            usage.tokens_out,
            (time.perf_counter() - started) * 1000.0,
            status,
            tenant_id or "",
            request_id,
            llm_calls=usage.llm_calls,
            cached_tokens=usage.cached_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            error_type=error_type,
            **extra_attributes,
        )


# ---------------------------------------------------------------------------
# Non-LLM dependency spans (B1, Feature 6.1)
#
# The chat-latency measurement of 2026-09-03 put a median SQL turn at 27.8s and
# could account for only 22.3s of it -- classify 3.1s, generation 15.6s, summary
# 3.6s. The remaining ~5.5s is real time inside the turn that no telemetry
# describes, and Block A's config changes do not touch any of it, which is why
# A1-A4 land at ~13-14s rather than the 8-10s the founder asked for.
#
# `dependencies` is empty for invoice-be today: the only spans the app emits are
# `tracked_llm_call`'s (Gap 300). These wrap the non-model work of a turn --
# embeddings, vector query, SQL execution, the two block builders, history and
# tenant stats -- as sibling CLIENT spans under the same request, so the
# breakdown becomes a query rather than an argument.
#
# Exporter contract: a CLIENT span exports as `RemoteDependencyData`. Without
# `gen_ai.system` the `DependencyType` is generic, so the field to group by is
# `dependency_name` in `customDimensions` -- set deliberately, not incidentally.
# ---------------------------------------------------------------------------

DEPENDENCY_EVENT_NAME = "dependency_call"
_DEPENDENCY_TRACER_NAME = "invoice_be.dependency"


@contextmanager
def track_dependency(
    dependency_name: str,
    *,
    dependency_type: str = "InProc",
    tenant_id: Optional[str] = None,
    request_id: Optional[str] = None,
    **extra_attributes: Any,
) -> Iterator[None]:
    """Time one non-LLM dependency; emit a CLIENT span and a custom event.

    Never raises, and re-raises whatever the block raised completely unchanged --
    the same contract `tracked_llm_call` holds, for the same reason: a call site's
    error handling must behave exactly as it did before instrumentation.

    The event is emitted as well as the span because the span needs a configured
    tracer provider to go anywhere, and local runs, tests and CI have none; the
    event reaches stdout through Feature 19's structured formatter either way,
    which is what makes the sum-of-spans assertion testable without Azure.
    """
    started = time.perf_counter()
    status = _STATUS_SUCCESS
    error_type: Optional[str] = None
    span = None
    try:
        from opentelemetry import trace as _otel_trace

        span = _otel_trace.get_tracer(_DEPENDENCY_TRACER_NAME).start_span(
            dependency_name,
            kind=_otel_trace.SpanKind.CLIENT,
            attributes={
                "dependency_name": dependency_name,
                "dependency_type": dependency_type,
                "tenant_id": str(tenant_id or tenant_id_ctx.get() or ""),
                "request_id": str(request_id or request_id_ctx.get() or ""),
                "run_source": _resolve_run_source(None),
            },
        )
    except Exception:  # pragma: no cover - telemetry must never break a call
        logger.debug("Could not start dependency span %s", dependency_name, exc_info=True)

    try:
        yield
    except BaseException as exc:
        status = _STATUS_ERROR
        error_type = type(exc).__name__
        raise
    finally:
        duration_ms = (time.perf_counter() - started) * 1000.0
        if span is not None:
            try:
                from opentelemetry.trace import Status, StatusCode

                if status == _STATUS_ERROR:
                    span.set_status(Status(StatusCode.ERROR, error_type or ""))
                    if error_type:
                        span.set_attribute(_ERROR_TYPE_ATTRIBUTE, error_type)
                else:
                    span.set_status(Status(StatusCode.OK))
            except Exception:  # pragma: no cover
                logger.debug("Could not annotate dependency span", exc_info=True)
            finally:
                try:
                    span.end()
                except Exception:  # pragma: no cover
                    logger.debug("Could not end dependency span", exc_info=True)
        try:
            attributes: Dict[str, Any] = {
                "dependency_name": dependency_name,
                "dependency_type": dependency_type,
                "duration_ms": round(duration_ms, 2),
                "status": status,
                "tenant_id": str(tenant_id or tenant_id_ctx.get() or ""),
                "request_id": str(request_id or request_id_ctx.get() or ""),
                "trace_id": str(trace_id_ctx.get() or ""),
                "run_source": _resolve_run_source(None),
            }
            if error_type:
                attributes["error_type"] = error_type
            for key, value in extra_attributes.items():
                if value is None or key in _RESERVED_LOG_RECORD_KEYS or key in attributes:
                    continue
                attributes[key] = value
            _emit_event(DEPENDENCY_EVENT_NAME, attributes)
        except Exception:  # pragma: no cover - telemetry must never break a call
            logger.debug("track_dependency failed for %s", dependency_name, exc_info=True)


def tracked_dependency(dependency_name: str, dependency_type: str = "InProc"):
    """Decorator form of `track_dependency`, for wrapping at the definition.

    Applied at the definition rather than at each call site on purpose: a wrapped
    definition covers every caller, including ones added later, and it cannot
    drift the way seven separately-edited call sites can. `functools.wraps` keeps
    the name and docstring, so `patch("module.name")` at a call site still works.
    """
    def decorate(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with track_dependency(dependency_name, dependency_type=dependency_type):
                return func(*args, **kwargs)

        return wrapper

    return decorate
