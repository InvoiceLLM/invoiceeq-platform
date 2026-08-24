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
