"""Feature 6.1 B1 — dependency spans for the non-LLM half of a chat turn, and the
two token fields Block A cannot be measured without.

Why this exists. The chat-latency measurement of 2026-09-03 put a median SQL turn
at 27.8 s and could account for only 22.3 s of it — classify 3.1 s, generation
15.6 s, summary 3.6 s. The remaining ~5.5 s is real time inside the turn that no
telemetry described, and none of Block A's config changes touch it. Separately,
`llm_agent_call` recorded prompt and completion counts but neither
`prompt_tokens_details.cached_tokens` nor
`completion_tokens_details.reasoning_tokens` — so A1 (lower `reasoning_effort`)
and A4 (reorder for prefix caching) had no before/after to point at.

Emission is asserted through `caplog`, matching `test_telemetry.py`: the stdout
record and the Application Insights customEvent are the same record, and the
exporter branches on the `microsoft.custom_event.name` attribute asserted here.
"""
import logging
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

import telemetry
from telemetry import (
    DEPENDENCY_EVENT_NAME,
    LLM_CALL_EVENT_NAME,
    track_dependency,
    tracked_dependency,
    tracked_llm_call,
)


def _deps(caplog):
    return [r for r in caplog.records if r.getMessage() == DEPENDENCY_EVENT_NAME]


def _llm_events(caplog):
    return [r for r in caplog.records if r.getMessage() == LLM_CALL_EVENT_NAME]


# ---------------------------------------------------------------------------
# The span/event mechanics
# ---------------------------------------------------------------------------


def test_one_dependency_event_per_tracked_block(caplog):
    with caplog.at_level(logging.INFO):
        with track_dependency("sql.execute", dependency_type="PostgreSQL", tenant_id="t-1"):
            pass

    records = _deps(caplog)
    assert len(records) == 1
    record = records[0]
    assert getattr(record, "microsoft.custom_event.name") == DEPENDENCY_EVENT_NAME
    assert record.dependency_name == "sql.execute"
    assert record.dependency_type == "PostgreSQL"
    assert record.status == "success"
    assert record.tenant_id == "t-1"
    assert isinstance(record.duration_ms, float)
    assert record.duration_ms >= 0.0
    # Feature 19's StructuredJsonFormatter reads exactly this key.
    assert record.extra_fields["dependency_name"] == "sql.execute"


def test_a_failing_dependency_is_recorded_as_error_and_re_raised_unchanged(caplog):
    with caplog.at_level(logging.INFO):
        with pytest.raises(ValueError, match="deadlock"):
            with track_dependency("sql.execute", dependency_type="PostgreSQL"):
                raise ValueError("deadlock")

    record = _deps(caplog)[-1]
    assert record.status == "error"
    assert record.error_type == "ValueError"


def test_a_broken_emitter_never_breaks_the_wrapped_work(monkeypatch):
    """Same contract as `tracked_llm_call`: telemetry failure is not a turn failure."""

    def _explode(*_args, **_kwargs):
        raise RuntimeError("Application Insights is down")

    monkeypatch.setattr(telemetry, "_resolve_event_logger", _explode)

    with track_dependency("rag.vector_query", dependency_type="Chroma"):
        result = "the work still happened"

    assert result == "the work still happened"


def test_the_decorator_preserves_identity_and_return_value(caplog):
    @tracked_dependency("chat.history", "PostgreSQL")
    def load_history(session_id, limit=5):
        """A docstring that must survive."""
        return f"{session_id}:{limit}"

    with caplog.at_level(logging.INFO):
        out = load_history("s-1", limit=9)

    assert out == "s-1:9"
    assert load_history.__name__ == "load_history"
    assert "must survive" in load_history.__doc__
    assert _deps(caplog)[-1].dependency_name == "chat.history"


# ---------------------------------------------------------------------------
# The seven wrapped dependencies actually report themselves
# ---------------------------------------------------------------------------

EXPECTED_DEPENDENCIES = {
    "sql.execute",
    "chat.tenant_stats",
    "chat.history",
    "chat.full_record_block",
    "chat.computed_figures_block",
    "rag.embeddings",
    "rag.vector_query",
}


def test_every_wrapped_function_is_still_wrapped():
    """A rename or a re-edit that drops a decorator must fail here, not in prod."""
    import chroma_client
    from agents import query_agent

    for module, name in [
        (query_agent, "execute_generated_sql"),
        (query_agent, "_get_tenant_stats_summary"),
        (query_agent, "get_chat_history"),
        (query_agent, "_full_record_block_for"),
        (query_agent, "_computed_figures_block_for"),
        (chroma_client, "get_embeddings"),
        (chroma_client, "query_invoice_chunks"),
    ]:
        func = getattr(module, name)
        assert getattr(func, "__wrapped__", None) is not None, (
            f"{module.__name__}.{name} is no longer wrapped as a dependency"
        )


def test_a_wrapped_call_reports_its_own_dependency_name(caplog):
    from agents.query_agent import _computed_figures_block_for

    with caplog.at_level(logging.INFO):
        _computed_figures_block_for(None)

    names = {r.dependency_name for r in _deps(caplog)}
    assert "chat.computed_figures_block" in names
    assert names <= EXPECTED_DEPENDENCIES


def test_a_failing_wrapped_call_still_raises_its_own_exception(caplog):
    """The wrapper must be invisible to the caller's error handling."""
    from agents.query_agent import execute_generated_sql

    with caplog.at_level(logging.INFO):
        with pytest.raises(ValueError, match="Mutating SQL"):
            execute_generated_sql("DELETE FROM invoice", "t-1", MagicMock())

    record = _deps(caplog)[-1]
    assert record.dependency_name == "sql.execute"
    assert record.status == "error"
    assert record.error_type == "ValueError"


# ---------------------------------------------------------------------------
# The two token fields
# ---------------------------------------------------------------------------


def test_cached_and_reasoning_tokens_are_read_from_the_azure_shape():
    usage = telemetry.LlmUsage()
    response = MagicMock()
    response.llm_output = {
        "token_usage": {
            "prompt_tokens": 8498,
            "completion_tokens": 1688,
            "prompt_tokens_details": {"cached_tokens": 7040},
            "completion_tokens_details": {"reasoning_tokens": 1216},
        }
    }

    telemetry._record_llm_result(usage, response)

    assert usage.tokens_in == 8498
    assert usage.tokens_out == 1688
    assert usage.cached_tokens == 7040
    assert usage.reasoning_tokens == 1216


def test_cached_and_reasoning_tokens_are_read_from_the_langchain_shape():
    """LangChain spells the same two counts `cache_read` and `reasoning`."""
    model = GenericFakeChatModel(
        messages=iter(
            [
                AIMessage(
                    content="ok",
                    usage_metadata={
                        "input_tokens": 1024,
                        "output_tokens": 200,
                        "total_tokens": 1224,
                        "input_token_details": {"cache_read": 896},
                        "output_token_details": {"reasoning": 64},
                    },
                )
            ]
        )
    )

    with tracked_llm_call("unit.reasoning", llm=model) as usage:
        model.invoke("hello")

    assert usage.cached_tokens == 896
    assert usage.reasoning_tokens == 64


def test_absent_token_details_read_as_zero_never_as_an_error():
    """A non-reasoning deployment sends no details; a short prompt caches nothing."""
    usage = telemetry.LlmUsage()
    response = MagicMock()
    response.llm_output = {"token_usage": {"prompt_tokens": 12, "completion_tokens": 3}}

    telemetry._record_llm_result(usage, response)

    assert (usage.cached_tokens, usage.reasoning_tokens) == (0, 0)
    assert (usage.tokens_in, usage.tokens_out) == (12, 3)


def test_malformed_token_details_do_not_break_the_call():
    usage = telemetry.LlmUsage()
    response = MagicMock()
    response.llm_output = {
        "token_usage": {
            "prompt_tokens": 5,
            "completion_tokens": 1,
            "prompt_tokens_details": "not-a-dict",
            "completion_tokens_details": None,
        }
    }

    telemetry._record_llm_result(usage, response)

    assert (usage.cached_tokens, usage.reasoning_tokens) == (0, 0)


def test_both_counts_reach_the_llm_agent_call_event(caplog):
    """A4 and A1 are unmeasurable until these two land in customDimensions."""
    model = GenericFakeChatModel(
        messages=iter(
            [
                AIMessage(
                    content="ok",
                    usage_metadata={
                        "input_tokens": 2048,
                        "output_tokens": 100,
                        "total_tokens": 2148,
                        "input_token_details": {"cache_read": 1024},
                        "output_token_details": {"reasoning": 32},
                    },
                )
            ]
        )
    )

    with caplog.at_level(logging.INFO):
        with tracked_llm_call("unit.cached", llm=model, tenant_id="t-9"):
            model.invoke("hello")

    record = _llm_events(caplog)[-1]
    assert record.cached_tokens == 1024
    assert record.reasoning_tokens == 32
    assert record.extra_fields["cached_tokens"] == 1024


def test_the_existing_token_fields_are_untouched(caplog):
    """Regression witness for Feature 23's cost KQL, which reads these names."""
    with caplog.at_level(logging.INFO):
        telemetry.track_agent_call(
            "unit.agent", "gpt-5-mini", 120, 34, 512.5, "success", "tenant-1", "req-1"
        )

    record = _llm_events(caplog)[-1]
    assert (record.tokens_in, record.tokens_out, record.tokens_total) == (120, 34, 154)
