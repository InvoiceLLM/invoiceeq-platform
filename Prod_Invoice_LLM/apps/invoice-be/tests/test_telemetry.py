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
