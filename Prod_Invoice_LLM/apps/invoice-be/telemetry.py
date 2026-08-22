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
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, Iterator, Optional

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

# Exporter contract — see module docstring.
_CUSTOM_EVENT_NAME_ATTRIBUTE = "microsoft.custom_event.name"

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
    """
    usage = LlmUsage()
    handler = _build_usage_handler(usage)
    reset_token = _usage_handler_ctx.set(handler) if handler is not None else None

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
        track_agent_call(
            agent_name,
            model or resolve_model_name(llm),
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
