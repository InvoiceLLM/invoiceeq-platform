"""Feature 23 Phase 1 — unit tests for `telemetry.py`.

Scope note, stated up front: these prove the *mechanics* of the telemetry helper
— that one event is emitted per tracked block, that it carries the fields Phase
2's cost KQL will read, that token counts really are captured off a LangChain
run, that an exception is re-raised unchanged with `status="error"`, and that a
broken emitter cannot break the agent call it wraps. They cannot prove the event
actually lands in Application Insights; that needs a live connection string and
is a manual/portal verification step (see feature_23_ai_control_tower.md).

Emission is asserted through `caplog` rather than by mocking the exporter,
because the stdout log record and the Application Insights customEvent are the
same record — the exporter branches on the `microsoft.custom_event.name`
attribute, which is asserted here directly.
"""
import logging
from datetime import date, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

import telemetry
from telemetry import LLM_CALL_EVENT_NAME, track_agent_call, tracked_llm_call


def _events(caplog):
    return [r for r in caplog.records if r.getMessage() == LLM_CALL_EVENT_NAME]


def test_track_agent_call_emits_one_custom_event_with_the_cost_fields(caplog):
    with caplog.at_level(logging.INFO):
        track_agent_call(
            "unit.agent", "gpt-5-mini", 120, 34, 512.5, "success", "tenant-1", "req-1"
        )

    records = _events(caplog)
    assert len(records) == 1
    record = records[0]
    # The attribute the Azure Monitor exporter branches on to route this record
    # to `customEvents` instead of `traces`.
    assert getattr(record, "microsoft.custom_event.name") == LLM_CALL_EVENT_NAME
    assert record.agent_name == "unit.agent"
    assert record.model == "gpt-5-mini"
    assert record.tokens_in == 120
    assert record.tokens_out == 34
    assert record.tokens_total == 154
    assert record.latency_ms == 512.5
    assert record.status == "success"
    assert record.tenant_id == "tenant-1"
    assert record.request_id == "req-1"
    # Feature 19's StructuredJsonFormatter reads exactly this key.
    assert record.extra_fields["agent_name"] == "unit.agent"


def test_tracked_llm_call_captures_real_token_usage_from_a_langchain_run(caplog):
    model = GenericFakeChatModel(
        messages=iter(
            [
                AIMessage(
                    content="ok",
                    usage_metadata={"input_tokens": 41, "output_tokens": 9, "total_tokens": 50},
                )
            ]
        )
    )

    with caplog.at_level(logging.INFO):
        with tracked_llm_call("unit.chat", llm=model, tenant_id="tenant-2") as usage:
            model.invoke("hello")

    assert (usage.tokens_in, usage.tokens_out, usage.llm_calls) == (41, 9, 1)
    record = _events(caplog)[-1]
    assert record.tokens_in == 41
    assert record.tokens_out == 9
    assert record.status == "success"
    assert record.tenant_id == "tenant-2"


def test_tracked_llm_call_records_error_status_and_re_raises_unchanged(caplog):
    with caplog.at_level(logging.INFO):
        with pytest.raises(RuntimeError, match="upstream 503"):
            with tracked_llm_call("unit.failing", tenant_id="tenant-3"):
                raise RuntimeError("upstream 503")

    record = _events(caplog)[-1]
    assert record.status == "error"
    assert record.error_type == "RuntimeError"


def test_a_broken_emitter_never_breaks_the_wrapped_call(monkeypatch):
    """The whole point of the helper: telemetry failure is not an agent failure."""

    def _explode(*_args, **_kwargs):
        raise RuntimeError("Application Insights is down")

    monkeypatch.setattr(telemetry, "_resolve_event_logger", _explode)

    with tracked_llm_call("unit.resilient", tenant_id="tenant-4"):
        answer = "the agent still returns its answer"

    assert answer == "the agent still returns its answer"


def test_resolve_model_name_reports_mock_rather_than_the_configured_deployment():
    """`get_llm()` falls back to MockInvoiceLLM when no Azure key is configured.

    Reporting the configured deployment name for a call a mock answered would
    put fabricated cost data straight into Phase 2's rollup.
    """
    from utils.llm import MockInvoiceLLM

    assert telemetry.resolve_model_name(MockInvoiceLLM()) == "mock"


# ─────────────────────────────────────────────────────────────────────────────
# Call-site coverage — the lightweight (hard-metrics-only) tier
# ─────────────────────────────────────────────────────────────────────────────
#
# Feature 23's 2026-08-23 rescope gives three registry rows a *lightweight*
# depth of treatment — cost, latency and error/retry rate only, no judged soft
# metrics: Trainer/EVOLVE correction loop, Dashboard insights, and the Trainer
# QA-panel summary. All five call sites behind those three rows were already
# instrumented in Phase 1; what did not exist was any test proving it, so the
# wrapper could have been dropped from any of them silently.
#
# These tests call the real functions (not `tracked_llm_call` directly) with a
# fake model in place of `get_llm()`, and assert the emitted event carries the
# fields a cost/latency/error rollup reads. They are the regression floor under
# the "nothing this application sends to a model is outside the cost rollup"
# claim in feature_23_ai_control_tower.md.

_HARD_METRIC_FIELDS = ("tokens_in", "tokens_out", "tokens_total", "latency_ms", "status", "llm_calls")


class _FakeLLM:
    """Stand-in for `get_llm()` at a `.with_structured_output()` call site.

    Hand-written rather than a `MagicMock` on purpose: a MagicMock answers every
    attribute, so `resolve_model_name()` would find a non-string for
    `deployment_name` on every hop, fall through to settings, and the `model`
    field would prove nothing about attribution at this call site. A real
    `model_name` string makes that assertion mean something.
    """

    def __init__(self, result, model_name="gpt-5-mini-fake"):
        self.model_name = model_name
        self._result = result

    def with_structured_output(self, schema):  # noqa: ARG002 - shape only
        return self

    def invoke(self, prompt):  # noqa: ARG002 - shape only
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _assert_hard_metrics(record, agent_name, *, status="success"):
    """The three hard metrics the lightweight tier promises, on one event.

    Token counts are asserted for *shape*, not value: the fakes above never route
    through LangChain's callback manager, so they report 0 tokens by design (see
    telemetry.py's "Token counts — why a callback" note). Real capture off a real
    LangChain run is proved by
    `test_tracked_llm_call_captures_real_token_usage_from_a_langchain_run` and,
    at a real call site, by the QA-summary test below.
    """
    assert getattr(record, "microsoft.custom_event.name") == LLM_CALL_EVENT_NAME
    assert record.agent_name == agent_name
    for field in _HARD_METRIC_FIELDS:
        assert hasattr(record, field), f"{agent_name} event is missing {field}"
    assert record.tokens_total == record.tokens_in + record.tokens_out
    assert isinstance(record.latency_ms, float)
    assert record.status == status
    assert record.model, f"{agent_name} event has no model attributed"


# ── Registry row: Dashboard insights ─────────────────────────────────────────

def _insights_db_session():
    """One in-memory tenant with one invoice — the minimum that reaches the LLM.

    `get_dashboard_insights` returns early with `{"insights": []}` and makes no
    model call at all when the tenant has no invoices, so an empty database would
    make this test pass for the wrong reason.
    """
    from sqlalchemy.pool import StaticPool
    from sqlmodel import Session, SQLModel, create_engine

    from dependencies import MOCK_TENANT_ID
    from models import Invoice

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    session = Session(engine)
    session.add(
        Invoice(
            id=uuid4(),
            tenant_id=MOCK_TENANT_ID,
            file_path="mock/telemetry.pdf",
            vendor_name="ACME",
            grand_total=1000.0,
            currency="USD",
            invoice_date=date(2026, 6, 20),
            created_at=datetime(2026, 6, 20),
            status="AUDIT_REQUIRED",
            sa_alerts=[],
        )
    )
    session.commit()
    return session


def _tenant_context():
    from dependencies import MOCK_TENANT_ID, TenantContext

    return TenantContext(
        tenant_id=MOCK_TENANT_ID, user_id="user-telemetry", role="Admin", billing_plan="pro"
    )


@pytest.fixture
def cache_missing_redis():
    """Force a dashboard-insights cache miss without needing a live Redis.

    Only a cache miss reaches the model, which is exactly why the event count is
    the true call count rather than the panel's view count.
    """
    fake = MagicMock()
    fake.get.return_value = None
    with patch("routers.dashboard._get_redis_client", return_value=fake):
        yield fake


def test_dashboard_insights_emits_one_hard_metrics_event(caplog, cache_missing_redis):
    from routers.dashboard import DashboardInsight, DashboardInsightsSchema, get_dashboard_insights

    schema = DashboardInsightsSchema(
        insights=[DashboardInsight(title="Concentration risk", detail="ACME dominates spend.", severity="warning")]
    )
    session = _insights_db_session()
    try:
        with caplog.at_level(logging.INFO):
            with patch("routers.dashboard.get_llm", return_value=_FakeLLM(schema)):
                result = get_dashboard_insights(context=_tenant_context(), db_session=session)
    finally:
        session.close()

    assert result["insights"][0]["title"] == "Concentration risk"
    records = [r for r in _events(caplog) if r.agent_name == "dashboard.insights"]
    assert len(records) == 1
    _assert_hard_metrics(records[0], "dashboard.insights")
    assert records[0].model == "gpt-5-mini-fake"
    assert records[0].tenant_id == str(_tenant_context().tenant_id)
    # The per-agent extra that makes a cost-per-insight rollup possible.
    assert records[0].invoice_count == 1


def test_dashboard_insights_failure_is_still_measurable_as_an_error(caplog, cache_missing_redis):
    """The handler swallows the exception and returns an empty panel (Gap 30's
    fail-soft contract), so an outage here is invisible to the caller. The event
    is the only place the error rate for this agent can be measured at all."""
    from routers.dashboard import get_dashboard_insights

    session = _insights_db_session()
    try:
        with caplog.at_level(logging.INFO):
            with patch(
                "routers.dashboard.get_llm",
                return_value=_FakeLLM(RuntimeError("Azure OpenAI 503")),
            ):
                result = get_dashboard_insights(context=_tenant_context(), db_session=session)
    finally:
        session.close()

    assert result == {"insights": []}  # unchanged fail-soft behaviour
    record = [r for r in _events(caplog) if r.agent_name == "dashboard.insights"][-1]
    _assert_hard_metrics(record, "dashboard.insights", status="error")
    assert record.error_type == "RuntimeError"


# ── Registry row: Trainer QA-panel summary ───────────────────────────────────

def test_trainer_qa_summary_emits_one_hard_metrics_event_with_real_tokens(caplog):
    """The one lightweight call site that takes an unstructured `llm.invoke()`,
    so a real LangChain model can stand in and real token counts are captured
    through the production code path rather than through the helper directly."""
    from routers.trainer import _answer_qa_from_session_data

    model = GenericFakeChatModel(
        messages=iter(
            [
                AIMessage(
                    content="This ACME invoice totals USD 110.00.",
                    usage_metadata={"input_tokens": 88, "output_tokens": 12, "total_tokens": 100},
                )
            ]
        )
    )
    session = {"extracted_data": {"vendor_name": "ACME Corporation", "grand_total": 110.0}}

    with caplog.at_level(logging.INFO):
        with patch("routers.trainer.get_llm", return_value=model):
            result = _answer_qa_from_session_data(session, "What is this invoice for?", tenant_id="tenant-qa")

    assert "ACME" in result["content"]
    records = [r for r in _events(caplog) if r.agent_name == "trainer.qa_summary"]
    assert len(records) == 1
    _assert_hard_metrics(records[0], "trainer.qa_summary")
    assert (records[0].tokens_in, records[0].tokens_out, records[0].tokens_total) == (88, 12, 100)
    assert records[0].tenant_id == "tenant-qa"
    assert records[0].field_count == 2


def test_trainer_qa_summary_failure_is_still_measurable_as_an_error(caplog):
    """Same shape as the dashboard: the caller turns the exception into a
    user-facing sentence, so the event is the only error signal that survives."""
    from routers.trainer import _answer_qa_from_session_data

    failing = MagicMock()
    failing.invoke.side_effect = RuntimeError("upstream 503")
    session = {"extracted_data": {"vendor_name": "ACME Corporation"}}

    with caplog.at_level(logging.INFO):
        with patch("routers.trainer.get_llm", return_value=failing):
            result = _answer_qa_from_session_data(session, "What is this?", tenant_id="tenant-qa")

    assert "Failed to answer" in result["content"]
    record = [r for r in _events(caplog) if r.agent_name == "trainer.qa_summary"][-1]
    _assert_hard_metrics(record, "trainer.qa_summary", status="error")
    assert record.error_type == "RuntimeError"


def test_trainer_qa_summary_makes_no_call_and_emits_nothing_without_extracted_data(caplog):
    """The early return is a real branch, not a formality — emitting an event for
    it would inflate this agent's call count with calls that never happened."""
    from routers.trainer import _answer_qa_from_session_data

    with caplog.at_level(logging.INFO):
        with patch("routers.trainer.get_llm") as m_get_llm:
            _answer_qa_from_session_data({"extracted_data": {}}, "anything", tenant_id="tenant-qa")

    m_get_llm.assert_not_called()
    assert [r for r in _events(caplog) if r.agent_name == "trainer.qa_summary"] == []


# ── Registry row: Trainer / EVOLVE correction loop ───────────────────────────
#
# Three distinct model calls sit behind this one registry row, and each is its
# own agent name because each has its own volume driver: the conversational
# refinement (every correction turn), the alert-anchored missed-alert draft
# (every Feature 18 "I expected an alert" correction) and the rule guardrail
# (every preview/commit, Gap 217).

def test_trainer_refine_constraints_emits_one_hard_metrics_event(caplog):
    from agents.trainer_agent import ConstraintList, refine_constraints

    refined = ConstraintList(constraints=["Parse dates as DD/MM/YYYY"])

    with caplog.at_level(logging.INFO):
        with patch("agents.trainer_agent.get_llm", return_value=_FakeLLM(refined)):
            result = refine_constraints(
                "Dates are day-first on this vendor",
                ["The invoice_number field is always prefixed with INV-"],
                scope="existing_vendor",
                tenant_id="tenant-evolve",
            )

    assert result == ["Parse dates as DD/MM/YYYY"]
    records = [r for r in _events(caplog) if r.agent_name == "trainer.refine_constraints"]
    assert len(records) == 1
    _assert_hard_metrics(records[0], "trainer.refine_constraints")
    assert records[0].tenant_id == "tenant-evolve"
    assert records[0].scope == "existing_vendor"


def test_trainer_refine_constraints_error_is_recorded_before_the_gap_212_reraise(caplog):
    """Gap 212 converts the failure into a `ConstraintRefinementError` and leaves
    the rules untouched. The event has to be emitted anyway — a correction loop
    that fails closed silently is exactly the case an error-rate metric is for."""
    from agents.trainer_agent import ConstraintRefinementError, refine_constraints

    with caplog.at_level(logging.INFO):
        with patch(
            "agents.trainer_agent.get_llm", return_value=_FakeLLM(RuntimeError("upstream 503"))
        ):
            with pytest.raises(ConstraintRefinementError):
                refine_constraints("anything", ["R1"], scope="existing_vendor", tenant_id="t")

    record = [r for r in _events(caplog) if r.agent_name == "trainer.refine_constraints"][-1]
    _assert_hard_metrics(record, "trainer.refine_constraints", status="error")
    assert record.error_type == "RuntimeError"


def test_trainer_missed_alert_draft_emits_one_hard_metrics_event(caplog):
    """Feature 18's alert-anchored correction — the call the registry row's
    "Per correction" volume driver actually counts."""
    from dependencies import MOCK_TENANT_ID
    from routers.trainer import MissedAlertPayload, MissedAlertRuleDraft, flag_missed_alert
    from services import trainer_sessions

    session_id = f"telemetry-{uuid4()}"
    trainer_sessions.save_session(
        session_id,
        {
            "session_id": session_id,
            "tenant_id": str(MOCK_TENANT_ID),
            "scope": "existing_vendor",
            "vendor_name": "ACME Corporation",
            "file_path": None,
            "ocr_text": "",
            "constraints": [],
            "extracted_data": {"vendor_name": "ACME Corporation", "tax_amount": 10.0},
            "chat_history": [],
            "flow_direction": "INBOUND",
            "alerts": [],
        },
    )
    draft = MissedAlertRuleDraft(
        rule_text="On this vendor's invoices tax_amount is a CGST+SGST split and must be summed."
    )
    payload = MissedAlertPayload(alert_type="tax_mismatch", field="tax_amount", context="")

    with caplog.at_level(logging.INFO):
        with patch("routers.trainer.get_llm", return_value=_FakeLLM(draft)):
            response = flag_missed_alert(session_id, payload, tenant_context=_tenant_context())

    assert response["stagedRule"]["text"] == draft.rule_text
    records = [r for r in _events(caplog) if r.agent_name == "trainer.missed_alert_rule"]
    assert len(records) == 1
    _assert_hard_metrics(records[0], "trainer.missed_alert_rule")
    assert records[0].tenant_id == str(MOCK_TENANT_ID)
    # Attributing the cost by alert type is what makes a noisy correction path
    # visible per check, not just in aggregate.
    assert records[0].alert_type == "tax_mismatch"


def test_trainer_rule_guardrail_emits_one_hard_metrics_event(caplog):
    """Gap 217's guardrail runs on every rule preview and commit, so it is real
    recurring spend on the trainer path, not a rare validation branch."""
    from routers.trainer import RuleClassification, _validate_rule_text

    verdict = RuleClassification(is_instruction=False, reason="data-interpretation fact", flagged_rule="")

    with caplog.at_level(logging.INFO):
        with patch("routers.trainer.get_llm", return_value=_FakeLLM(verdict)):
            _validate_rule_text(
                ["Tax is listed as GST not VAT for this vendor"], tenant_id="tenant-evolve"
            )

    records = [r for r in _events(caplog) if r.agent_name == "trainer.rule_guardrail"]
    assert len(records) == 1
    _assert_hard_metrics(records[0], "trainer.rule_guardrail")
    assert records[0].tenant_id == "tenant-evolve"
    assert records[0].rule_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# Gap 300 — the LLM call as an `AppDependencies` row
# ─────────────────────────────────────────────────────────────────────────────
#
# These are deliberately not caplog tests: the dependency span is the one thing
# `telemetry.py` emits that is *not* a log record. They install a real
# OpenTelemetry SDK `TracerProvider` with an in-memory exporter, so what is
# asserted is the actual span object the Azure Monitor exporter would receive.
#
# `test_llm_dependency_span_converts_to_a_remote_dependency_envelope` goes one
# step further and runs that span through the real
# `azure-monitor-opentelemetry-exporter` conversion function — the same code
# path a deployed container runs — so the claim "this lands in AppDependencies
# with DependencyType 'GenAI | az.ai.openai'" is executed, not asserted from
# reading the exporter's source. It is the closest a local test can get to the
# live KQL that opened this gap; the live check itself needs a deploy.

import config  # noqa: E402


@pytest.fixture
def recorded_spans():
    """Spans emitted during the test, captured in memory.

    Attaches to the process-global `TracerProvider` (creating an SDK one on the
    first use) rather than swapping it: OpenTelemetry only honours
    `set_tracer_provider` once per process, and `telemetry.py` resolves its
    tracer from the global on every call, exactly as it does in a container.
    """
    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    provider = otel_trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        otel_trace.set_tracer_provider(provider)

    exporter = InMemorySpanExporter()
    processor = SimpleSpanProcessor(exporter)
    provider.add_span_processor(processor)
    try:
        yield exporter
    finally:
        # There is no public "remove processor"; shutting it down stops it
        # recording so it cannot capture a later test's spans.
        processor.shutdown()


@pytest.fixture
def azure_openai_configured(monkeypatch):
    """Pin the provider/endpoint so the span's system + target don't depend on
    the developer's local `.env`. `get_settings()` is `lru_cache`d, so patching
    the singleton's attributes is what `telemetry.py` will read."""
    settings = config.get_settings()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "azure")
    monkeypatch.setattr(
        settings, "AZURE_OPENAI_ENDPOINT", "https://oai-invoicellm-dev.openai.azure.com/"
    )
    # `resolve_model_name()` falls back to the configured deployment for a model
    # object that carries no name of its own (which `GenericFakeChatModel` is).
    monkeypatch.setattr(settings, "AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-5-mini")
    yield settings


def _llm_spans(exporter):
    return [
        s
        for s in exporter.get_finished_spans()
        if s.instrumentation_scope is not None
        and s.instrumentation_scope.name == "invoice_be.telemetry.llm"
    ]


def test_tracked_llm_call_emits_one_client_span_with_the_gen_ai_attributes(
    recorded_spans, azure_openai_configured
):
    """The core of Gap 300: a CLIENT span carrying `gen_ai.system`, which is what
    makes the exporter write an `AppDependencies` row typed as GenAI."""
    from opentelemetry.trace import SpanKind

    model = GenericFakeChatModel(
        messages=iter(
            [
                AIMessage(
                    content="ok",
                    usage_metadata={"input_tokens": 77, "output_tokens": 12, "total_tokens": 89},
                )
            ]
        )
    )

    with tracked_llm_call("chat.sql_generate", llm=model, tenant_id="tenant-dep"):
        model.invoke("how many invoices are overdue?")

    spans = _llm_spans(recorded_spans)
    assert len(spans) == 1
    span = spans[0]
    assert span.kind is SpanKind.CLIENT
    # semconv span name for a chat completion, "{operation} {model}".
    assert span.name == "chat gpt-5-mini"
    assert span.attributes["gen_ai.system"] == "az.ai.openai"
    assert span.attributes["gen_ai.operation.name"] == "chat"
    assert span.attributes["gen_ai.request.model"] == "gpt-5-mini"
    # The endpoint hostname, which becomes DependencyTarget.
    assert span.attributes["peer.service"] == "oai-invoicellm-dev.openai.azure.com"
    assert span.attributes["server.address"] == "oai-invoicellm-dev.openai.azure.com"
    # Same token counts the `llm_agent_call` event carries — the two surfaces
    # must not disagree about the same call.
    assert span.attributes["gen_ai.usage.input_tokens"] == 77
    assert span.attributes["gen_ai.usage.output_tokens"] == 12
    assert span.attributes["llm_calls"] == 1
    # Not semconv; the per-feature-area grouping key the gap exists to unblock.
    assert span.attributes["agent_name"] == "chat.sql_generate"
    assert span.attributes["tenant_id"] == "tenant-dep"
    assert span.status.is_ok
    assert span.end_time > span.start_time


def test_llm_dependency_span_is_a_child_of_the_surrounding_request_span(
    recorded_spans, azure_openai_configured
):
    """Why the span exists at all: `AppDependencies` rows only support a
    dependency-vs-request-duration breakdown if they hang off the request's
    trace. This asserts the parent link the FastAPI request span supplies."""
    from opentelemetry import trace as otel_trace

    tracer = otel_trace.get_tracer("test.request")
    with tracer.start_as_current_span("POST /api/chat") as request_span:
        request_context = request_span.get_span_context()
        with tracked_llm_call("chat.conversational", model="gpt-5-mini", tenant_id="t"):
            pass

    span = _llm_spans(recorded_spans)[0]
    assert span.parent is not None
    assert span.parent.span_id == request_context.span_id
    assert span.context.trace_id == request_context.trace_id


def test_llm_dependency_span_converts_to_a_remote_dependency_envelope(
    recorded_spans, azure_openai_configured
):
    """Executed proof that this reaches `AppDependencies`, not `traces`.

    Runs the recorded span through the installed
    `azure-monitor-opentelemetry-exporter`'s own span→envelope conversion (the
    exact function the deployed container runs on export) and asserts the
    envelope is `RemoteDependencyData` typed `GenAI | az.ai.openai` — i.e. the
    `DependencyType` the KQL that opened this gap searched for and did not find.
    """
    exporter_module = pytest.importorskip(
        "azure.monitor.opentelemetry.exporter.export.trace._exporter"
    )

    with tracked_llm_call("sage.plan", model="gpt-5-mini", tenant_id="tenant-dep"):
        pass

    envelope = exporter_module._convert_span_to_envelope(_llm_spans(recorded_spans)[0])

    assert envelope.data.base_type == "RemoteDependencyData"
    dependency = envelope.data.base_data
    assert dependency.type == "GenAI | az.ai.openai"
    assert dependency.target == "oai-invoicellm-dev.openai.azure.com"
    assert dependency.name == "chat gpt-5-mini"
    assert dependency.success is True
    # `agent_name` survives into customDimensions; the semconv-standard
    # `peer.*`/`server.*` keys are consumed into the target instead.
    assert dependency.properties["agent_name"] == "sage.plan"


def test_llm_dependency_span_marks_a_failed_call_as_a_failed_dependency(
    recorded_spans, azure_openai_configured
):
    """A model outage has to show as a failed dependency, not a fast one — the
    exporter reads `span.status.is_ok` for the `Success` column."""
    from opentelemetry.trace import StatusCode

    with pytest.raises(RuntimeError, match="upstream 503"):
        with tracked_llm_call("chat.classify", model="gpt-5-mini", tenant_id="t"):
            raise RuntimeError("upstream 503")

    span = _llm_spans(recorded_spans)[0]
    assert span.status.status_code is StatusCode.ERROR
    assert span.attributes["error.type"] == "RuntimeError"
    assert span.end_time is not None  # ended despite the exception


def test_a_mock_llm_answer_is_never_labelled_as_azure_openai(
    recorded_spans, azure_openai_configured
):
    """Same rule `resolve_model_name` follows: a call a mock answered must not be
    indistinguishable from a real one in a dependency rollup."""
    from utils.llm import MockInvoiceLLM

    with tracked_llm_call("chat.conversational", llm=MockInvoiceLLM(), tenant_id="t"):
        pass

    span = _llm_spans(recorded_spans)[0]
    assert span.attributes["gen_ai.system"] == "mock"
    assert span.attributes["gen_ai.request.model"] == "mock"
    # No peer for a mock — there was no network call to name.
    assert "peer.service" not in span.attributes


def test_ollama_provider_is_reported_as_its_own_gen_ai_system(monkeypatch):
    """The other provider this app really supports. Asserted on the resolvers
    directly so it does not depend on a tracer provider being installed."""
    settings = config.get_settings()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://ollama-host:11434")

    system = telemetry.resolve_gen_ai_system(None, "llama3")
    assert system == "ollama"
    assert telemetry.resolve_gen_ai_peer(system) == "ollama-host"


def test_resolve_gen_ai_peer_never_leaks_more_than_a_hostname(monkeypatch):
    """A dependency target is a host. The configured endpoint can carry a path
    and query string, and an Azure OpenAI URL's query string is where api-version
    (and in some SDK shapes, a key) travels."""
    settings = config.get_settings()
    monkeypatch.setattr(settings, "LLM_PROVIDER", "azure")
    monkeypatch.setattr(
        settings,
        "AZURE_OPENAI_ENDPOINT",
        "https://oai-invoicellm-dev.openai.azure.com/openai/deployments/x?api-key=secret",
    )

    assert telemetry.resolve_gen_ai_peer("az.ai.openai") == "oai-invoicellm-dev.openai.azure.com"


def test_a_broken_dependency_span_never_breaks_the_wrapped_call(monkeypatch, caplog):
    """Same contract as `test_a_broken_emitter_never_breaks_the_wrapped_call`,
    for the new emission path: span failure is not an agent failure, and the
    `llm_agent_call` event must still be emitted."""

    def _explode(*_args, **_kwargs):
        raise RuntimeError("no tracer provider")

    monkeypatch.setattr(telemetry, "resolve_gen_ai_system", _explode)

    with caplog.at_level(logging.INFO):
        with tracked_llm_call("unit.resilient", model="gpt-5-mini", tenant_id="tenant-5"):
            answer = "the agent still returns its answer"

    assert answer == "the agent still returns its answer"
    assert _events(caplog)[-1].agent_name == "unit.resilient"


def test_a_hostile_span_object_is_still_ended_and_never_raises():
    """`_end_llm_dependency_span` ends the span even when annotating it fails —
    an unended span is a leak in the batch processor."""

    class _HostileSpan:
        def __init__(self):
            self.ended = False

        def set_attribute(self, *_args, **_kwargs):
            raise RuntimeError("span is already ended")

        def set_status(self, *_args, **_kwargs):
            raise RuntimeError("span is already ended")

        def end(self):
            self.ended = True

    span = _HostileSpan()
    telemetry._end_llm_dependency_span(span, usage=telemetry.LlmUsage(), status="success")
    assert span.ended is True

    # And a None span (the no-tracer path) is simply a no-op.
    telemetry._end_llm_dependency_span(None, usage=telemetry.LlmUsage(), status="error")


# ─────────────────────────────────────────────────────────────────────────────
# Gap 304 (partial) — `run_source` on every `llm_agent_call`
# ─────────────────────────────────────────────────────────────────────────────
#
# The whole point of this field is that it is a *prerequisite*, not a feature:
# `services/benchmark_artifacts.py::configure_run_telemetry()` deliberately
# attaches the exporter after all eval turns have run, so a benchmark's own
# per-call events never reach `customEvents`. Before that can safely change,
# there has to be a way to tell benchmark traffic apart from real traffic —
# otherwise every production cost and latency number is silently polluted.
#
# So what these tests protect is: (1) a production call site that says nothing
# is tagged `production`, which is what makes zero call-site changes correct;
# (2) an eval script tags its own run through the *existing* `--run-label`
# switch, so the per-call tag and the aggregate event's label cannot disagree;
# (3) neither path can raise. They do **not** assert that a benchmark's events
# reach Application Insights — they still deliberately do not.


@pytest.fixture
def isolated_run_source():
    """Reset `run_source_ctx` after the test.

    A contextvar set inside a test would otherwise leak into every test that
    runs after it in the same thread — and this suite runs with `pytest-randomly`
    ordering, so that leak would be intermittent rather than reproducible.
    """
    token = telemetry.run_source_ctx.set(telemetry.RUN_SOURCE_PRODUCTION)
    try:
        yield
    finally:
        telemetry.run_source_ctx.reset(token)


def test_a_call_that_says_nothing_about_its_source_is_tagged_production(caplog):
    """The reason no production call site needed to change: the default is the
    honest answer for every one of them.

    Run inside an explicitly empty `contextvars.Context()`, which is what a fresh
    request/worker thread really gets. Asserting against the ambient context
    instead would make this test order-dependent: `tests/
    test_run_extraction_benchmark_cli.py` drives the benchmark CLI *in process*,
    so its `configure_run_source()` call leaves `golden` set for every test that
    runs after it — which is correct behaviour for a script that owns its own
    process, and an artefact of running a script's `main()` under pytest.
    """
    import contextvars

    def _emit():
        track_agent_call("chat.sql_summary", "gpt-5-mini", 10, 5, 100.0, "success", "t")

    with caplog.at_level(logging.INFO):
        contextvars.Context().run(_emit)

    assert _events(caplog)[-1].run_source == "production"
    assert telemetry.RUN_SOURCE_PRODUCTION == "production"


def test_set_run_source_tags_every_subsequent_event_in_this_context(
    caplog, isolated_run_source
):
    """What an eval script gets for one call at startup: every `llm_agent_call`
    its turns produce afterwards is separable from real traffic."""
    telemetry.set_run_source(telemetry.RUN_SOURCE_GOLDEN)

    with caplog.at_level(logging.INFO):
        with tracked_llm_call("chat.sql_generation", model="gpt-5-mini", tenant_id="t"):
            pass
        track_agent_call("eval.judge", "gpt-5-mini", 1, 1, 1.0, "success", "t")

    assert [r.run_source for r in _events(caplog)] == ["golden", "golden"]


def test_configure_run_source_reuses_the_existing_run_label_switch(isolated_run_source):
    """`--run-label` is the one flag; `run_source` is derived from it rather than
    being a second switch that could be set inconsistently. `nightly`/`adhoc` are
    both golden-bank populations — the cadence difference between them is already
    carried by `run_label` on the aggregate event."""
    from services.benchmark_artifacts import (
        RUN_LABEL_ADHOC,
        RUN_LABEL_NIGHTLY,
        RUN_LABEL_PREDEPLOY,
        configure_run_source,
    )

    assert configure_run_source(RUN_LABEL_NIGHTLY) == "golden"
    assert telemetry.run_source_ctx.get() == "golden"
    assert configure_run_source(RUN_LABEL_ADHOC) == "golden"
    assert configure_run_source(RUN_LABEL_PREDEPLOY) == "predeploy"
    assert telemetry.run_source_ctx.get() == "predeploy"


def test_an_explicit_run_source_keyword_is_not_silently_dropped(caplog, isolated_run_source):
    """`track_agent_call` drops any extra whose key already exists in the
    attribute dict — so `run_source` has to be handled *before* that loop, or a
    call site passing it explicitly would be mis-tagged with no error at all.
    This is the regression test for exactly that trap."""
    telemetry.set_run_source(telemetry.RUN_SOURCE_GOLDEN)

    with caplog.at_level(logging.INFO):
        track_agent_call(
            "chat.classify", "gpt-5-mini", 1, 1, 1.0, "success", "t",
            run_source=telemetry.RUN_SOURCE_PREDEPLOY,
        )

    assert _events(caplog)[-1].run_source == "predeploy"


def test_a_broken_run_source_context_still_emits_a_production_tagged_event(
    monkeypatch, caplog
):
    """Same contract as every other emitter here: this field can never be the
    reason an event is lost, and an unreadable source degrades to the safe
    default rather than to a missing field."""

    class _HostileContextVar:
        def get(self, *_args, **_kwargs):
            raise RuntimeError("context is gone")

    monkeypatch.setattr(telemetry, "run_source_ctx", _HostileContextVar())

    with caplog.at_level(logging.INFO):
        track_agent_call("chat.sql_summary", "gpt-5-mini", 1, 1, 1.0, "success", "t")

    assert _events(caplog)[-1].run_source == "production"


# ─────────────────────────────────────────────────────────────────────────────
# Gap 304 half (1) — the other two surfaces an exported eval run now reaches
# ─────────────────────────────────────────────────────────────────────────────
#
# The section above tagged `llm_agent_call`, which was enough while
# `services/benchmark_artifacts.py::configure_run_telemetry()` still deferred
# the exporter until after every graded turn. Since 2026-08-24 it attaches
# *before* the first turn, so an eval run also exports:
#
#   * its per-turn `agent_eval_run` events (`track_eval_result`), and
#   * one GenAI CLIENT span per LLM call, into `AppDependencies`.
#
# Both land in the same table as production rows. The span is the load-bearing
# one: `DependencyType` collapses every LLM call to `GenAI | az.ai.openai`, so
# without `run_source` in its attributes there is no way at all to tell an eval
# run's dependency rows from a real user's. These tests pin the field on both.


def _eval_events(caplog):
    return [r for r in caplog.records if r.getMessage() == telemetry.EVAL_RESULT_EVENT_NAME]


def test_an_eval_result_carries_the_population_that_produced_it(caplog, isolated_run_source):
    """`agent_eval_run` events now reach `customEvents` from a real eval run, so
    they need the same discriminator `llm_agent_call` has. Resolved from the
    contextvar rather than left to whatever the caller passes — nothing set it
    before this change, so the field was absent on every row."""
    telemetry.set_run_source(telemetry.RUN_SOURCE_GOLDEN)

    with caplog.at_level(logging.INFO):
        telemetry.track_eval_result(
            "chat.default", "titan_steel_payment_status", True, latency_ms=1200.0
        )

    record = _eval_events(caplog)[-1]
    assert record.run_source == "golden"
    assert record.case_id == "titan_steel_payment_status"
    assert getattr(record, "microsoft.custom_event.name") == telemetry.EVAL_RESULT_EVENT_NAME


def test_an_explicit_run_source_on_an_eval_result_is_not_silently_dropped(
    caplog, isolated_run_source
):
    """Same trap as `track_agent_call`: the `**extra_attributes` loop drops any
    key already in the dict, so an explicit `run_source=` had to be popped
    *before* it or the row would be mis-tagged with no error at all."""
    telemetry.set_run_source(telemetry.RUN_SOURCE_GOLDEN)

    with caplog.at_level(logging.INFO):
        telemetry.track_eval_result(
            "chat.default", "greeting_no_tool", False,
            run_source=telemetry.RUN_SOURCE_PREDEPLOY,
        )

    assert _eval_events(caplog)[-1].run_source == "predeploy"


def test_an_eval_result_from_production_context_still_says_production(caplog):
    """The default is what makes the gate/nightly split honest: a row that says
    nothing about its source is a production row."""
    import contextvars

    def _emit():
        telemetry.track_eval_result("chat.default", "case", True)

    with caplog.at_level(logging.INFO):
        contextvars.Context().run(_emit)

    assert _eval_events(caplog)[-1].run_source == "production"


def test_the_dependency_span_carries_run_source_so_appdependencies_stays_separable(
    recorded_spans, azure_openai_configured, isolated_run_source
):
    """The half of Gap 304 (1) that actually needed new code.

    `DependencyType` is `GenAI | az.ai.openai` for every LLM call this app makes,
    production or eval — so once an eval run exports its spans, this attribute is
    the only thing that keeps a dependency-time breakdown from silently including
    the nightly job's 20 graded turns.
    """
    telemetry.set_run_source(telemetry.RUN_SOURCE_GOLDEN)

    with tracked_llm_call("chat.sql_generate", model="gpt-5-mini", tenant_id="t"):
        pass

    span = _llm_spans(recorded_spans)[0]
    assert span.attributes["run_source"] == "golden"


def test_run_source_survives_the_exporters_own_span_conversion(
    recorded_spans, azure_openai_configured, isolated_run_source
):
    """Executed rather than reasoned: the recorded span goes through the installed
    exporter's real span→envelope function, and `run_source` has to come out in
    `customDimensions` — a KQL filter cannot use an attribute the exporter drops
    (`peer.service`/`server.address` are consumed into the target exactly that
    way, which is why this is worth asserting)."""
    exporter_module = pytest.importorskip(
        "azure.monitor.opentelemetry.exporter.export.trace._exporter"
    )
    telemetry.set_run_source(telemetry.RUN_SOURCE_PREDEPLOY)

    with tracked_llm_call("eval.faithfulness", model="gpt-5-mini", tenant_id="t"):
        pass

    envelope = exporter_module._convert_span_to_envelope(_llm_spans(recorded_spans)[0])
    dependency = envelope.data.base_data
    assert dependency.type == "GenAI | az.ai.openai"
    assert dependency.properties["run_source"] == "predeploy"
    # And the caveat this makes measurable rather than invisible: the judge's own
    # calls are exported under the same tag as the system under test, so a
    # "golden cost" rollup that does not exclude `eval.*` is measuring the grader
    # too. `services/agent_eval.py::_invoke_structured` names them this way.
    assert dependency.properties["agent_name"].startswith("eval.")


def test_an_explicit_run_source_tags_the_event_and_the_span_identically(
    recorded_spans, azure_openai_configured, isolated_run_source, caplog
):
    """`tracked_llm_call` reads the explicit keyword without consuming it, so the
    two surfaces describing one call cannot disagree about which population it
    belongs to."""
    telemetry.set_run_source(telemetry.RUN_SOURCE_GOLDEN)

    with caplog.at_level(logging.INFO):
        with tracked_llm_call(
            "chat.classify",
            model="gpt-5-mini",
            tenant_id="t",
            run_source=telemetry.RUN_SOURCE_PREDEPLOY,
        ):
            pass

    assert _events(caplog)[-1].run_source == "predeploy"
    assert _llm_spans(recorded_spans)[0].attributes["run_source"] == "predeploy"


# ─────────────────────────────────────────────────────────────────────────────
# Gap 305 (partial) — the zero-result flag on `chat.sql_summary`
# ─────────────────────────────────────────────────────────────────────────────
#
# `zero_result_rate` is one of `services/online_eval_signals.py`'s five signals,
# and today the only way to compute it is to scan `chat_message.content` in
# Postgres for the `NO_RECORDS_FOUND` sentinel after the fact — which needs
# direct DB access and cannot be queried from Log Analytics at all.
#
# `agents/query_agent.py`'s SQL loop already detects the condition; nothing was
# emitted there. These tests pin two things: that the loop records it (including
# the deterministic invoice-number fallback's outcome, which distinguishes "the
# generated SQL was wrong" from "there is genuinely no such invoice"), and that
# it rides the *existing* `chat.sql_summary` event rather than becoming a new
# event type. `chat.sql_summary` is the carrier because it is emitted exactly
# once per turn whose SQL actually executed — a declined turn or one that failed
# all three attempts never reaches it — so `countif(zero_result) / count()` over
# that agent_name is a well-formed rate with no separate denominator to build.
#
# Scope stated rather than implied: this covers the default chat SQL route only.
# `agents/query_tools.py`'s `identify_invoices`/`aggregate` share the same loop
# and get the flags on their `SqlGenerationOutcome`, but neither tool makes a
# follow-up LLM call, so there is no existing event of theirs to ride; the SAGE
# path (`ENABLE_AGENTIC_SAGE`, default off, and off for every tenant today) is
# therefore not covered.

from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

# Imported at module scope, not inside the tests: `SQLModel.metadata` is only
# populated once `models` has been imported, so a `create_all()` that runs before
# it produces an empty schema and every query fails with "no such table".
from dependencies import MOCK_TENANT_ID  # noqa: E402
import models  # noqa: E402,F401 - imported for its `SQLModel.metadata` side effect

_ZERO_RESULT_ENGINE = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
)


@pytest.fixture(name="sql_route_session")
def sql_route_session_fixture():
    SQLModel.metadata.create_all(_ZERO_RESULT_ENGINE)
    with Session(_ZERO_RESULT_ENGINE) as session:
        yield session
    SQLModel.metadata.drop_all(_ZERO_RESULT_ENGINE)


class _ScriptedSqlLLM:
    """One scripted SQL-generation result, then a fixed summary answer.

    Same shape as `tests/test_chat_sql_quality.py::_RecordingLLM`, kept local so
    this file stays runnable on its own.
    """

    def __init__(self, sql):
        self._sql = sql
        self.summary_prompts = []
        self.model_name = "gpt-5-mini-fake"

    def with_structured_output(self, schema):  # noqa: ARG002 - shape only
        outer = self

        class _Structured:
            def invoke(self, prompt):  # noqa: ARG002 - shape only
                return MagicMock(sql=outer._sql, explanation_or_error=None)

        return _Structured()

    def invoke(self, prompt):
        self.summary_prompts.append(prompt)
        return MagicMock(content="Formatted summary.")


def _run_sql_route(
    db_session, llm, message, *, execute=None, session_id=None, cached=None, route="SQL"
):
    """One turn through the real `run_query_agent()` SQL route.

    `session_id`/`cached`/`route` were added for Gap 302's tests: the thread
    position (`turn_index`) needs several turns in one session, and the
    cache-hit status needs `get_cached_answer()` to actually return something.
    All three default to the pre-Gap-302 behaviour.
    """
    from contextlib import ExitStack

    from agents import query_agent

    patches = [
        patch("agents.query_agent.classify_query", return_value=route),
        patch("agents.query_agent.query_invoice_chunks", return_value=[]),
        patch("agents.query_agent.get_llm", return_value=llm),
        patch("agents.query_agent.get_cached_answer", return_value=cached),
        patch("agents.query_agent.set_cached_answer"),
        patch("agents.query_agent._get_tenant_stats_summary", return_value=""),
    ]
    if execute is not None:
        patches.append(patch("agents.query_agent.execute_generated_sql", side_effect=execute))

    with ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        return query_agent.run_query_agent(
            str(session_id or uuid4()), message, str(MOCK_TENANT_ID), db_session
        )


def _summary_events(caplog):
    return [r for r in _events(caplog) if r.agent_name == "chat.sql_summary"]


def test_a_zero_result_turn_is_flagged_on_the_sql_summary_event(sql_route_session, caplog):
    """The measurement this unblocks: a real turn that found nothing is now
    queryable from Log Analytics, with no Postgres access and no new event."""
    llm = _ScriptedSqlLLM(f"SELECT id FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")

    with caplog.at_level(logging.INFO):
        result = _run_sql_route(sql_route_session, llm, "how much did we spend on freight?")

    # No rows were seeded, so the real query genuinely matched nothing — and the
    # user really is told so, which is the state `zero_result_rate` measures.
    from agents.query_agent import NO_RECORDS_FOUND

    assert NO_RECORDS_FOUND in result["content"]
    record = _summary_events(caplog)[-1]
    assert record.zero_result is True
    assert record.zero_result_fallback_recovered is False


def test_a_turn_that_found_rows_carries_the_flag_as_false(sql_route_session, caplog):
    """The denominator half. The field is present on *every* summary event, not
    only the zero ones — a rate needs both, and a field that only appears on
    failures cannot produce one."""
    ids = [str(uuid4())]

    def _execute(sql, tenant_id, db_sess, snapshot=None):  # noqa: ARG001 - shape only
        if snapshot is not None:
            snapshot.extend(ids)
        return "\n\nid | currency\n--- | ---\n" + "\n".join(f"{i} | USD" for i in ids)

    llm = _ScriptedSqlLLM(f"SELECT id, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")

    with caplog.at_level(logging.INFO):
        _run_sql_route(sql_route_session, llm, "what did we spend?", execute=_execute)

    record = _summary_events(caplog)[-1]
    assert record.zero_result is False
    assert record.zero_result_fallback_recovered is False


def test_the_invoice_number_fallback_reports_recovered_rather_than_zero_result(
    sql_route_session, caplog
):
    """The distinction that makes the flag diagnostic rather than decorative: the
    generated SQL missed an invoice that really exists, and the deterministic
    fallback found it. The user got an answer, so this is not a zero-result turn
    — but it is a generated-SQL defect, and only this second field says so.

    The fallback lookup itself is stubbed rather than driven through real rows:
    it issues raw SQL with a *dashed* tenant literal, and SQLModel stores UUID
    columns dashless on SQLite (checked, not assumed:
    `SELECT tenant_id FROM invoice` returns `'00000000...'` with no hyphens), so
    no seeded row can be matched by it under this engine. What is under test here
    is the flag the fallback's outcome sets, not the fallback's own SQL — which
    `tests/test_chat_sql_quality.py` already covers for the same reason.
    """
    llm = _ScriptedSqlLLM(f"SELECT id FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")
    recovered_rows = "\n\ninvoice_number | vendor_name\n--- | ---\nUS-20260722-001 | Titan Steel"

    with caplog.at_level(logging.INFO):
        with patch(
            "agents.query_agent.lookup_invoice_by_number_fallback",
            return_value=recovered_rows,
        ):
            result = _run_sql_route(
                sql_route_session, llm, "give me the details of invoice US-20260722-001"
            )

    from agents.query_agent import NO_RECORDS_FOUND

    assert NO_RECORDS_FOUND not in result["content"]
    record = _summary_events(caplog)[-1]
    assert record.zero_result_fallback_recovered is True
    assert record.zero_result is False


def test_the_flag_does_not_appear_on_the_sql_generation_event(sql_route_session, caplog):
    """It rides one specific existing event, deliberately. The SQL-generation
    block closes at `.invoke()` so its `latency_ms` stays model time and never
    absorbs query execution — the row count is not known yet when that event is
    emitted, and a field that was sometimes absent would break the rate."""
    llm = _ScriptedSqlLLM(f"SELECT id FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")

    with caplog.at_level(logging.INFO):
        _run_sql_route(sql_route_session, llm, "how much did we spend on freight?")

    generation = [r for r in _events(caplog) if r.agent_name == "chat.sql_generation"]
    assert len(generation) == 1
    assert not hasattr(generation[0], "zero_result")


def test_the_outcome_records_the_flags_for_every_caller_of_the_shared_loop():
    """`run_sql_generation_loop()` is shared with SAGE's `identify_invoices` /
    `aggregate` tools. They have no follow-up LLM call to carry the flag onto,
    but the loop still records it on the outcome — so wiring the SAGE path later
    is a call-site change, not a re-derivation of the condition."""
    from agents.query_agent import NO_RECORDS_FOUND, run_sql_generation_loop

    llm = _ScriptedSqlLLM("SELECT id FROM invoice WHERE tenant_id = 'x'")

    with patch("agents.query_agent.execute_generated_sql", return_value=NO_RECORDS_FOUND):
        outcome = run_sql_generation_loop(
            llm=llm,
            system_prompt="prompt",
            wrapped_user_message="q",
            user_message="q",
            tenant_id="x",
            db_session=MagicMock(),
            telemetry_agent_name="sage.aggregate",
        )

    assert outcome.zero_result is True
    assert outcome.zero_result_fallback_recovered is False


# ─────────────────────────────────────────────────────────────────────────────
# Gap 302 (Trace) + Gap 303 half (a) (Thread position) — the `chat_turn` event
# ─────────────────────────────────────────────────────────────────────────────
#
# What these pin, in the order the risk sits:
#
# 1. **Every turn outcome produces exactly one event.** Before this, a declined
#    turn, an errored turn and a cache hit produced no turn-level telemetry at
#    all, so their rates were unaskable. A test that only covered the happy path
#    would leave the entire reason the gap was opened uncovered.
# 2. **The content is real, not structural.** The founder's decision was that a
#    Trace carries the actual generated SQL and the actual tool output — a turn
#    whose SQL was subtly wrong is not diagnosable from `sql_generated=true`.
#    Asserted against the real strings, and the truncation caps are asserted
#    separately so "full content" cannot silently become "unbounded content".
# 3. **The correlation IDs really reach the background pool.** This is a live
#    attribution bug being fixed, not a new field: `ThreadPoolExecutor.submit()`
#    copies no context, so every judge call and every queued turn's
#    `llm_agent_call` events were landing with `trace_id=""`. Pinned by observing
#    the contextvars from inside the work itself rather than by reading the code.
# 4. **The accumulator counts the turn, not the thread.** It is reset on the way
#    out, because the pool thread will serve another turn and a leaked
#    accumulator would inflate the next one's totals silently and only under
#    load.


def _turn_events(caplog):
    return [
        r for r in caplog.records if r.getMessage() == telemetry.CHAT_TURN_EVENT_NAME
    ]


def _emit_turn(result, **overrides):
    """Emit the turn `run_query_agent()` just described, as the routers do."""
    fields = dict(result.get("turn_telemetry") or {})
    fields.update(overrides)
    telemetry.track_chat_turn(**fields)


def test_a_successful_sql_turn_carries_the_real_sql_and_the_real_tool_output(
    sql_route_session, caplog
):
    """The founder decision, asserted as content rather than as a flag: the event
    holds the SQL the model actually wrote and the rows the database actually
    returned, because "the SQL was wrong in a way that still executed" is the
    failure this exists to diagnose and no boolean can express it."""
    sql = f"SELECT id, currency FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'"
    rows = "\n\nid | currency\n--- | ---\nabc | USD"
    llm = _ScriptedSqlLLM(sql)

    with caplog.at_level(logging.INFO):
        result = _run_sql_route(
            sql_route_session, llm, "what did we spend?", execute=lambda *a, **k: rows
        )
        _emit_turn(result, message_id="msg-1", latency_ms=1234.5)

    events = _turn_events(caplog)
    assert len(events) == 1
    event = events[0]
    assert getattr(event, "microsoft.custom_event.name") == telemetry.CHAT_TURN_EVENT_NAME
    assert event.status == telemetry.TURN_STATUS_SUCCESS
    assert event.route == "SQL"
    assert event.sql_generated is True
    assert event.generated_sql == sql
    assert rows.strip() in event.tool_output
    assert event.tool_output_chars == len(f"DATABASE RESULTS:\n{rows}")
    assert event.sql_attempts == 1
    assert event.message_id == "msg-1"
    assert event.latency_ms == 1234.5
    assert event.tenant_id == str(MOCK_TENANT_ID)
    assert event.turn_id


def test_the_turn_accumulates_every_llm_call_made_inside_it(sql_route_session, caplog):
    """A turn's cost is the sum of its calls, and nothing at the call sites knows
    it is being counted. The SQL route makes two — generation and summary — and
    both must land on one turn event without a `summarize` over `llm_agent_call`."""
    llm = _ScriptedSqlLLM(f"SELECT id FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")

    with caplog.at_level(logging.INFO):
        result = _run_sql_route(
            sql_route_session, llm, "what did we spend?", execute=lambda *a, **k: "| id |"
        )
        _emit_turn(result, message_id="msg-2")

    event = _turn_events(caplog)[0]
    assert event.llm_call_count == 2
    assert "chat.sql_generation" in event.agents_called
    assert "chat.sql_summary" in event.agents_called
    # Same two calls, counted independently by the per-call events.
    assert len([r for r in _events(caplog) if r.agent_name.startswith("chat.")]) == 2


def test_the_accumulator_does_not_leak_into_the_next_turn(sql_route_session, caplog):
    """The reason `chat_turn_scope()` resets in a `finally` rather than leaving
    the contextvar set the way `main_worker` does: this runs on a pooled thread
    that will serve another turn, and a leaked accumulator would add turn N's
    model calls to turn N+1's totals — silently, and only under load."""
    llm = _ScriptedSqlLLM(f"SELECT id FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")

    with caplog.at_level(logging.INFO):
        first = _run_sql_route(
            sql_route_session, llm, "first question?", execute=lambda *a, **k: "| id |"
        )
        second = _run_sql_route(
            sql_route_session, llm, "second question?", execute=lambda *a, **k: "| id |"
        )

    assert first["turn_telemetry"]["llm_call_count"] == 2
    assert second["turn_telemetry"]["llm_call_count"] == 2
    assert first["turn_telemetry"]["turn_id"] != second["turn_telemetry"]["turn_id"]
    # Outside a turn there is no accumulator at all, so the eval harness, the
    # ingestion pipeline and the trainer cannot be counted into one.
    assert telemetry.current_chat_turn() is None


def test_a_declined_turn_is_recorded_as_declined_rather_than_as_a_failure(
    sql_route_session, caplog
):
    """A refusal is a real product outcome, not an error — the two must not share
    a status, or "how often does the assistant decline?" and "how often does it
    break?" become one unreadable number. Before this event neither was
    measurable at all: a declined turn emitted no turn-level telemetry."""
    llm = _ScriptedSqlLLM(None)  # `sql: null` — the model declined

    with caplog.at_level(logging.INFO):
        result = _run_sql_route(sql_route_session, llm, "write me some code")
        _emit_turn(result, message_id="msg-3")

    event = _turn_events(caplog)[0]
    assert event.status == telemetry.TURN_STATUS_DECLINED
    assert event.stop_reason == "sql_declined"
    assert event.sql_generated is False
    assert event.generated_sql == ""
    # The refusal really was returned to the user, i.e. this is the live shape
    # rather than a synthetic status.
    assert "cannot answer" in result["content"]


def test_an_errored_turn_is_recorded_with_the_exception_type(sql_route_session, caplog):
    """Every attempt failed and the user got an error string. `error_type` is on
    the event because "the SQL route is down" and "the SQL route is generating
    invalid SQL" are the same status and different problems."""
    llm = _ScriptedSqlLLM(f"SELECT id FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")

    def _always_fails(*args, **kwargs):
        raise RuntimeError("relation \"invoice\" does not exist")

    with caplog.at_level(logging.INFO):
        result = _run_sql_route(
            sql_route_session, llm, "what did we spend?", execute=_always_fails
        )
        _emit_turn(result, message_id="msg-4")

    event = _turn_events(caplog)[0]
    assert event.status == telemetry.TURN_STATUS_ERROR
    assert event.error_type == "RuntimeError"
    assert event.stop_reason == "sql_attempts_exhausted"
    # All three attempts were really burned, which is the shape a Trace has to
    # be able to show and which no per-call event totals for the turn.
    assert event.sql_attempts == 3
    assert "Failed to execute database check" in result["content"]


def test_a_cache_hit_is_flagged_so_it_can_be_excluded_from_per_turn_averages(
    sql_route_session, caplog
):
    """A cached answer is a real turn the user took — a session whose every turn
    was cached would otherwise look like a session that never happened. It is
    tagged `cache_hit` rather than dropped precisely so cost/latency rollups can
    exclude it: no model call was made, so counting it as a fresh turn would
    report free turns and dilute every per-turn average."""
    cached = {
        "content": "Total spend is $12,500.00",
        "generated_sql": "SELECT SUM(grand_total) FROM invoice",
        "citations": [],
        "result_invoice_ids": ["a", "b"],
    }
    llm = _ScriptedSqlLLM("SELECT 1")

    with caplog.at_level(logging.INFO):
        result = _run_sql_route(sql_route_session, llm, "what did we spend?", cached=cached)
        _emit_turn(result, message_id="msg-5")

    event = _turn_events(caplog)[0]
    assert event.status == telemetry.TURN_STATUS_CACHE_HIT
    assert event.llm_call_count == 0
    assert event.tokens_total == 0
    assert event.result_invoice_count == 2
    # `"cached"`, not a guessed original route: the cached payload has never
    # carried one, and guessing from `generated_sql` is wrong for a declined SQL
    # turn (which is cached, with no SQL) and would file it under RAG.
    assert event.route == "cached"
    # Nothing about this turn is written back into Redis. `turn_telemetry` is
    # attached to the dict `get_cached_answer()` hands back, which in production
    # is a fresh `json.loads()` of the stored payload on every hit — the stored
    # value is never re-serialised, so the cache entry keeps exactly the size and
    # shape it had, same property `judge_evidence` relies on.
    assert result["content"] == "Total spend is $12,500.00"
    assert "turn_telemetry" in result


def test_turn_index_and_the_idle_gap_are_measured_across_a_multi_turn_session(
    sql_route_session, caplog
):
    """Gap 303 half (a). `turn_index` counts *assistant* messages, not all
    messages, because on the async queue path the user's row is committed before
    the handler runs and on the synchronous path it is not — counting every row
    would make the same turn the 2nd on one path and the 1st on the other."""
    from datetime import datetime, timedelta

    from models import ChatMessage, ChatSession

    session_id = uuid4()
    sql_route_session.add(ChatSession(id=session_id, tenant_id=MOCK_TENANT_ID, title="T"))
    sql_route_session.commit()

    llm = _ScriptedSqlLLM(f"SELECT id FROM invoice WHERE tenant_id = '{MOCK_TENANT_ID}'")

    first = _run_sql_route(
        sql_route_session, llm, "q1", session_id=session_id, execute=lambda *a, **k: "| id |"
    )
    assert first["turn_telemetry"]["turn_index"] == 1
    # No predecessor, so the field is absent rather than 0 — a 0 would read as
    # "the user sent two messages in the same instant".
    assert first["turn_telemetry"]["seconds_since_prev_turn"] is None

    # The turn the router would have committed, backdated so the idle gap is a
    # real measured number rather than a sub-millisecond one.
    sql_route_session.add(
        ChatMessage(
            id=uuid4(),
            session_id=session_id,
            role="assistant",
            content="answer 1",
            status="completed",
            created_at=datetime.utcnow() - timedelta(minutes=45),
        )
    )
    sql_route_session.commit()

    second = _run_sql_route(
        sql_route_session, llm, "q2", session_id=session_id, execute=lambda *a, **k: "| id |"
    )
    assert second["turn_telemetry"]["turn_index"] == 2
    gap = second["turn_telemetry"]["seconds_since_prev_turn"]
    # 45 minutes — past the 30-minute idle cutoff, i.e. the same session_id
    # really can contain two sittings, which is why the KQL in
    # `infra/monitoring/chat_thread_sessions.kql` re-derives windows with
    # `row_window_session(..., 30m)` instead of trusting session_id alone.
    assert gap is not None and gap > 30 * 60

    with caplog.at_level(logging.INFO):
        _emit_turn(second, message_id="msg-6")
    event = _turn_events(caplog)[0]
    assert event.turn_index == 2
    assert event.seconds_since_prev_turn > 30 * 60


def test_a_first_turn_omits_the_thread_fields_rather_than_sending_zero(caplog):
    """The emitter's half of the same rule, asserted at the boundary: absent
    stays absent. Same reason `track_online_signal` drops a None value — a 0
    there is a measurement, and "there was no previous turn" is not."""
    with caplog.at_level(logging.INFO):
        telemetry.track_chat_turn(route="CHAT", status="success", session_id="s1")

    event = _turn_events(caplog)[0]
    assert not hasattr(event, "turn_index")
    assert not hasattr(event, "seconds_since_prev_turn")


def test_full_content_is_capped_at_the_documented_budgets(caplog):
    """"Full content" must not mean "unbounded content". The two caps are
    deliberately the same budgets `services/agent_eval.py` already uses for the
    judge prompt, so a reader comparing an event against a judge prompt sees the
    same truncation — and the marker is in the value, so "the SQL was this" and
    "the SQL started like this" stay distinguishable."""
    from services.agent_eval import MAX_CONTEXT_CHARS, MAX_QUERY_CHARS

    assert telemetry.MAX_TURN_SQL_CHARS == MAX_QUERY_CHARS
    assert telemetry.MAX_TURN_TOOL_OUTPUT_CHARS == MAX_CONTEXT_CHARS

    huge_sql = "SELECT " + ("x," * 5000)
    huge_output = "row\n" * 8000
    with caplog.at_level(logging.INFO):
        telemetry.track_chat_turn(
            route="SQL", generated_sql=huge_sql, tool_output=huge_output
        )

    event = _turn_events(caplog)[0]
    assert event.generated_sql.startswith(huge_sql[: telemetry.MAX_TURN_SQL_CHARS])
    assert "truncated at 3000 chars" in event.generated_sql
    assert "truncated at 12000 chars" in event.tool_output
    # The pre-truncation size travels separately, so a genuinely short result and
    # a cut one are distinguishable without parsing the marker.
    assert event.tool_output_chars == len(huge_output)


def test_a_broken_turn_emitter_never_breaks_a_completed_turn(monkeypatch, caplog):
    """Same never-raises contract as every other emitter in this module, and it
    matters more here: this fires *after* the user already has their answer and
    after the commit, so anything it raised would turn a delivered answer into a
    500."""
    monkeypatch.setattr(
        telemetry, "_emit_event", MagicMock(side_effect=RuntimeError("exporter down"))
    )
    with caplog.at_level(logging.DEBUG):
        telemetry.track_chat_turn(route="SQL", status="success")  # must not raise
    assert not _turn_events(caplog)


# ── the correlation-ID fix: the background pool inherits no context ───────────


def test_the_queue_path_binds_the_originating_requests_correlation_ids(caplog):
    """The live attribution bug, pinned rather than assumed.

    `routers/chat.py` submits this handler to `_chat_background_pool`, and
    `ThreadPoolExecutor.submit()` copies no contextvars — so before this fix the
    entire queued turn ran with `trace_id_ctx`/`tenant_id_ctx`/`request_id_ctx`
    empty, and every `llm_agent_call` it emitted (plus every judge call it went
    on to submit) landed in `customEvents` with `trace_id=""`.

    Observed from *inside* the work rather than off the event alone, because the
    contextvars are what `tracked_llm_call` reads at every call site — proving
    them bound here proves it for all of them.
    """
    from queue_worker.handlers import handle_process_chat_job
    from utils.logging_config import request_id_ctx, tenant_id_ctx, trace_id_ctx

    seen = {}

    def _fake_agent(**kwargs):
        seen["trace_id"] = trace_id_ctx.get()
        seen["tenant_id"] = tenant_id_ctx.get()
        seen["request_id"] = request_id_ctx.get()
        return {
            "content": "answer",
            "generated_sql": "SELECT 1",
            "citations": [],
            "result_invoice_ids": [],
            "turn_telemetry": {"route": "SQL", "status": "success", "session_id": "s9"},
        }

    session_id, user_msg_id = uuid4(), uuid4()
    with Session(_ZERO_RESULT_ENGINE) as db:
        SQLModel.metadata.create_all(_ZERO_RESULT_ENGINE)
        with caplog.at_level(logging.INFO), \
             patch("agents.query_agent.run_query_agent", side_effect=_fake_agent), \
             patch("services.chat_queue.ChatQueueService.publish_progress"), \
             patch("services.chat_queue.ChatQueueService.complete_job"):
            handle_process_chat_job(
                job_id="job-trace",
                session_id=str(session_id),
                user_msg_id=str(user_msg_id),
                content="what did we spend?",
                tenant_id=str(MOCK_TENANT_ID),
                db_session=db,
                trace_id="0af7651916cd43dd8448eb211c80319c",
                request_id="req-from-the-http-request",
            )

    assert seen["trace_id"] == "0af7651916cd43dd8448eb211c80319c"
    assert seen["request_id"] == "req-from-the-http-request"
    assert seen["tenant_id"] == str(MOCK_TENANT_ID)

    # And the turn event the handler emitted carries them too.
    event = _turn_events(caplog)[0]
    assert event.trace_id == "0af7651916cd43dd8448eb211c80319c"
    assert event.request_id == "req-from-the-http-request"
    assert event.tenant_id == str(MOCK_TENANT_ID)
    assert event.route == "SQL"
    assert event.message_id  # the assistant row's id, resolved after the commit

    # Bound for the duration and released after it: the pool thread goes on to
    # serve another tenant's turn.
    assert trace_id_ctx.get() == ""


def test_a_queued_turn_that_raises_still_emits_an_errored_turn_event(caplog):
    """The outcome that previously produced nothing at all. An error rate cannot
    be computed from events that were never emitted, and the handler's own
    `except` is the only place that sees failures from the commit and the Redis
    publish as well as from the agent."""
    from queue_worker.handlers import handle_process_chat_job

    session_id, user_msg_id = uuid4(), uuid4()
    with Session(_ZERO_RESULT_ENGINE) as db:
        SQLModel.metadata.create_all(_ZERO_RESULT_ENGINE)
        with caplog.at_level(logging.INFO), \
             patch(
                 "agents.query_agent.run_query_agent",
                 side_effect=ValueError("chroma is unreachable"),
             ), \
             patch("services.chat_queue.ChatQueueService.publish_progress"), \
             patch("services.chat_queue.ChatQueueService.complete_job"), \
             patch("services.chat_queue.ChatQueueService.fail_job"):
            res = handle_process_chat_job(
                job_id="job-boom",
                session_id=str(session_id),
                user_msg_id=str(user_msg_id),
                content="what did we spend?",
                tenant_id=str(MOCK_TENANT_ID),
                db_session=db,
                trace_id="trace-boom",
            )

    assert res["status"] == "failed"
    event = _turn_events(caplog)[0]
    assert event.status == telemetry.TURN_STATUS_ERROR
    assert event.error_type == "ValueError"
    assert event.stop_reason == "queue_handler_raised"
    assert event.trace_id == "trace-boom"


def test_the_online_judge_runs_with_the_turns_correlation_ids_bound(caplog):
    """The other half of the same bug, and the one that was already live in
    production code: `eval.combined_soft` and `eval.persona` go through
    `tracked_llm_call()` on the same context-free pool thread, so every judged
    turn was emitting judge events with `trace_id=""`/`tenant_id=""` — scores
    that could not be joined back to the turn they scored, which is the one
    thing `services/online_quality_judge.py` exists to make possible."""
    from services.online_quality_judge import judge_turn
    from utils.logging_config import request_id_ctx, tenant_id_ctx, trace_id_ctx

    seen = {}

    def _fake_combined(question, answer, context, llm, queries):  # noqa: ARG001
        seen["trace_id"] = trace_id_ctx.get()
        seen["tenant_id"] = tenant_id_ctx.get()
        seen["request_id"] = request_id_ctx.get()
        return {"faithfulness": 0.9, "relevance": 0.8}, [], [], 1

    with caplog.at_level(logging.INFO), \
         patch("services.online_quality_judge.score_soft_metrics_combined", _fake_combined), \
         patch("services.online_quality_judge.score_persona", return_value=(None, [], 0)), \
         patch("services.online_quality_judge.score_orchestration", return_value=(1.0, [])), \
         patch("services.online_quality_judge._persist") as persist:
        judge_turn(
            question="what did we spend?",
            answer="Total spend is $12,500.00",
            evidence={"route": "SQL", "context": "rows", "executed_queries": "SELECT 1"},
            tenant_id=str(MOCK_TENANT_ID),
            message_id=str(uuid4()),
            trace_id="trace-from-the-judged-turn",
            request_id="req-from-the-judged-turn",
            llm=MagicMock(),
        )

    assert persist.called
    assert seen["trace_id"] == "trace-from-the-judged-turn"
    assert seen["request_id"] == "req-from-the-judged-turn"
    assert seen["tenant_id"] == str(MOCK_TENANT_ID)
    # Released again — the pool is shared with queued chat jobs, so a leaked
    # tenant id would attribute one tenant's judge call to another's turn.
    assert tenant_id_ctx.get() == ""
