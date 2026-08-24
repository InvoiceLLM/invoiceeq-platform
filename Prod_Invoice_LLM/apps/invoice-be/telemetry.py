"""Feature 23 (AI Control Tower) — Phase 1: one telemetry event per real LLM call.

Every LLM invocation this application makes emits exactly one Application Insights
``customEvents`` row named ``llm_agent_call``, carrying ``agent_name``, ``model``,
``tokens_in``, ``tokens_out``, ``latency_ms``, ``status``, ``tenant_id`` and
``request_id``. Phase 2's cost rollup is a KQL query over those rows — no new
storage, no new Azure resource.

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

import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator, Optional
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

# Feature 24 (Ops Digest Agent). One event per scheduled digest run.
#
# This one is not a mirror of anything -- unlike the four above, there is no
# durable Postgres row behind it. The digest itself is delivered to a Teams
# channel and an inbox, neither of which can be queried, so this event is the
# only way to answer "did the digest job actually run, and what did it find?"
# after the fact. Without it a dead scheduler and a quiet week look identical,
# which is the exact failure the feature's own `audit_job_failed` exception
# exists to catch for Feature 23's eval job.
OPS_DIGEST_EVENT_NAME = "ops_digest_run"

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
    """
    try:
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
        }
        for key, value in extra_attributes.items():
            if value is None or key in _RESERVED_LOG_RECORD_KEYS or key in attributes:
                continue
            attributes[key] = value

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
    """
    try:
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
    window_days: Optional[int] = None,
    tenant_id: str = "",
    **extra_attributes: Any,
) -> None:
    """Emit one ``online_eval_signal`` custom event — the telemetry mirror of a
    ``services.online_eval_signals.SignalResult``.

    ``value`` stays absent when it is None. That is not tidiness: a None value
    from that module means "the denominator was empty, nothing was measured",
    and emitting it as 0.0 would render an ingestion outage as a perfectly
    healthy day on every chart built on this event.

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
            attributes["window_days"] = int(window_days)
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


#: The nine scored dimensions of ``services.agent_eval.EvalScores``, in the
#: three groups that class's docstring keeps deliberately apart: answer-level
#: (the only three ``decide_pass()`` reads), component-level (the "which part of
#: the pipeline broke" decomposition), and soft-metric (combined judge only).
#: Named here so the event and the workbook agree on one vocabulary and a
#: dimension cannot be silently dropped from the mirror by a typo.
EVAL_SCORE_DIMENSIONS = (
    "faithfulness",
    "relevance",
    "accuracy",
    "context",
    "orchestration",
    "persona",
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


def track_ops_digest_run(
    *,
    window_hours: float,
    items_collected: int,
    critical_count: int,
    needs_decision_count: int,
    self_resolved_count: int,
    collection_errors: int,
    llm_calls: int = 0,
    synthesis_error: str = "",
    delivered_to: str = "",
    delivery_errors: int = 0,
    **extra_attributes: Any,
) -> None:
    """Emit one ``ops_digest_run`` event — Feature 24's own run record.

    One row per scheduled run, and the *only* durable evidence that this agent
    ran at all: a digest goes to Teams/email, neither of which is queryable, so
    without this event "the digest job has been silently dead for a week" and
    "nothing happened for a week" are the same observation. That is precisely
    the failure mode the feature's own ``audit_job_failed`` exception exists to
    catch for the *eval* job, and it would be careless to build this agent with
    the same blind spot it was written to close.

    ``delivered_to`` carries channel labels only (``webhook:https://…`` truncated
    at the query string, ``email:2``) — never a full webhook URL, which is a
    replayable credential.

    Never raises, same contract as every other emitter here.
    """
    try:
        attributes: Dict[str, Any] = {
            "window_hours": round(float(window_hours or 0.0), 2),
            "items_collected": int(items_collected or 0),
            "critical_count": int(critical_count or 0),
            "needs_decision_count": int(needs_decision_count or 0),
            "self_resolved_count": int(self_resolved_count or 0),
            "collection_errors": int(collection_errors or 0),
            "llm_calls": int(llm_calls or 0),
            "synthesis_error": synthesis_error or "",
            "delivered_to": delivered_to or "",
            "delivery_errors": int(delivery_errors or 0),
            "status": _STATUS_ERROR if (synthesis_error or delivery_errors) else _STATUS_SUCCESS,
        }
        for key, value in extra_attributes.items():
            if value is None or key in _RESERVED_LOG_RECORD_KEYS or key in attributes:
                continue
            attributes[key] = value

        _emit_event(OPS_DIGEST_EVENT_NAME, attributes)
    except Exception:  # pragma: no cover - telemetry must never break a run
        logger.debug("track_ops_digest_run failed", exc_info=True)


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

    __slots__ = ("tokens_in", "tokens_out", "llm_calls")

    def __init__(self) -> None:
        self.tokens_in = 0
        self.tokens_out = 0
        self.llm_calls = 0

    def add(self, tokens_in: int, tokens_out: int) -> None:
        self.tokens_in += int(tokens_in or 0)
        self.tokens_out += int(tokens_out or 0)
        self.llm_calls += 1


def _record_llm_result(usage: LlmUsage, response: Any) -> None:
    """Pull prompt/completion counts off a LangChain ``LLMResult``.

    Two shapes, because providers differ on which one they populate:
    ``llm_output["token_usage"]`` (what AzureChatOpenAI returns) and the
    per-generation ``usage_metadata`` (the newer, provider-neutral field).
    """
    llm_output = getattr(response, "llm_output", None) or {}
    token_usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
    if token_usage:
        usage.add(
            token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0,
            token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0,
        )
        return

    for generation_list in getattr(response, "generations", None) or []:
        for generation in generation_list or []:
            message = getattr(generation, "message", None)
            metadata = getattr(message, "usage_metadata", None) or {}
            if metadata:
                usage.add(metadata.get("input_tokens") or 0, metadata.get("output_tokens") or 0)


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
    span = _start_llm_dependency_span(
        agent_name, model_name, llm=llm, tenant_id=tenant_id, request_id=request_id
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
            error_type=error_type,
            **extra_attributes,
        )
