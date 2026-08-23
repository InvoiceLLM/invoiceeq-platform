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
