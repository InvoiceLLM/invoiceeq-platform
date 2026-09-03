"""Feature 6.1 item A1 — a reasoning budget and a completion cap on SQL generation.

Measured 2026-09-03: generation was 15.6 s of a 27.8 s median chat turn, 8,498
tokens in and 1,688 out, most of the output being thinking rather than SQL.
`reasoning_effort="low"` shrinks that; a completion cap bounds the tail.

Generation stays on the *reasoning* deployment — it is the one call in the turn
that genuinely reasons, and A2 must never touch it. What A1 changes is the budget.

Both settings are inert by default, and that is the point: A1's claim is a latency
claim, and it cannot be checked until B1's `reasoning_tokens` field is live in
Azure. Shipping it off means the switch gets thrown against a measurement rather
than an expectation. **The risk, stated plainly: a cheaper reasoning budget still
returns *a* query — it fails by generating subtly worse SQL, not by failing.** The
golden set is the only control for that, and it has not run yet.
"""
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

import config  # noqa: E402
from agents import query_agent  # noqa: E402


@pytest.fixture
def azure_provider(monkeypatch):
    monkeypatch.setattr(config.settings, "LLM_PROVIDER", "azure", raising=False)


def _set(monkeypatch, effort="", cap=0):
    monkeypatch.setattr(
        config.settings, "AZURE_OPENAI_SQL_REASONING_EFFORT", effort, raising=False
    )
    monkeypatch.setattr(
        config.settings, "AZURE_OPENAI_SQL_MAX_COMPLETION_TOKENS", cap, raising=False
    )


def test_both_settings_unset_changes_nothing(monkeypatch, azure_provider):
    """The default must be bit-identical to life before A1 existed."""
    _set(monkeypatch)
    sentinel = MagicMock(name="default-llm")

    with patch.object(query_agent, "get_llm", return_value=sentinel) as default, \
         patch.object(query_agent, "build_llm") as built:
        assert query_agent._generation_llm() is sentinel

    default.assert_called_once()
    built.assert_not_called()


def test_reasoning_effort_alone_is_passed_through(monkeypatch, azure_provider):
    _set(monkeypatch, effort="low")
    tuned = MagicMock(name="tuned")

    with patch.object(query_agent, "build_llm", return_value=tuned) as built:
        assert query_agent._generation_llm() is tuned

    built.assert_called_once_with("azure", max_tokens=None, reasoning_effort="low")


def test_a_completion_cap_alone_is_passed_through(monkeypatch, azure_provider):
    _set(monkeypatch, cap=900)
    tuned = MagicMock()

    with patch.object(query_agent, "build_llm", return_value=tuned) as built:
        assert query_agent._generation_llm() is tuned

    built.assert_called_once_with("azure", max_tokens=900, reasoning_effort=None)


def test_both_together(monkeypatch, azure_provider):
    _set(monkeypatch, effort="low", cap=900)
    tuned = MagicMock()

    with patch.object(query_agent, "build_llm", return_value=tuned):
        query_agent._generation_llm()


def test_a_zero_or_negative_cap_is_treated_as_unset(monkeypatch, azure_provider):
    for cap in (0, -1):
        _set(monkeypatch, cap=cap)
        sentinel = MagicMock()
        with patch.object(query_agent, "get_llm", return_value=sentinel), \
             patch.object(query_agent, "build_llm") as built:
            assert query_agent._generation_llm() is sentinel
        built.assert_not_called()


def test_a_non_azure_provider_ignores_both(monkeypatch):
    """Mock mode is how the suite runs; it must be unaffected either way."""
    monkeypatch.setattr(config.settings, "LLM_PROVIDER", "mock", raising=False)
    _set(monkeypatch, effort="low", cap=900)
    sentinel = MagicMock()
    with patch.object(query_agent, "get_llm", return_value=sentinel), \
         patch.object(query_agent, "build_llm") as built:
        assert query_agent._generation_llm() is sentinel
    built.assert_not_called()


def test_a_rejected_budget_degrades_instead_of_killing_the_turn(monkeypatch, azure_provider):
    """A deployment that refuses `reasoning_effort` must not cost a chat turn."""
    _set(monkeypatch, effort="ludicrous")
    sentinel = MagicMock(name="default-llm")

    with patch.object(query_agent, "build_llm", side_effect=RuntimeError("bad value")), \
         patch.object(query_agent, "get_llm", return_value=sentinel):
        assert query_agent._generation_llm() is sentinel


def test_build_llm_omits_reasoning_effort_unless_asked():
    """Sending `reasoning_effort` to a non-reasoning deployment is an error, and
    every pre-existing caller omits it — so omission has to remain the default."""
    from utils import llm as llm_module

    captured = {}

    class _FakeAzure:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    with patch.object(llm_module, "AzureChatOpenAI", _FakeAzure), \
         patch.object(config.settings, "AZURE_OPENAI_API_KEY", "real-looking-key"), \
         patch.object(config.settings, "LLM_PROVIDER", "azure"):
        llm_module.build_llm("azure", model="gpt-5-mini")

    assert "reasoning_effort" not in captured

    captured.clear()
    with patch.object(llm_module, "AzureChatOpenAI", _FakeAzure), \
         patch.object(config.settings, "AZURE_OPENAI_API_KEY", "real-looking-key"), \
         patch.object(config.settings, "LLM_PROVIDER", "azure"):
        llm_module.build_llm("azure", model="gpt-5-mini", reasoning_effort="low")

    assert captured.get("reasoning_effort") == "low"


def test_generation_uses_the_reasoning_handle_not_the_fast_one():
    """A1 and A2 must not fight over the same call.

    A2 moves the phrasing calls to a non-reasoning deployment; A1 tunes the
    reasoning budget of the generation call. If generation ever picks up
    `_fast_llm()`, `reasoning_effort` is being sent to a model that has none and
    the two items silently cancel out.
    """
    import inspect

    source = inspect.getsource(query_agent._run_query_agent)

    # Compare whole assignments, not substrings: "fast_llm = _fast_llm()" ends
    # with "llm = _fast_llm()", so a naive `in` check fails on correct code.
    assignments = [
        line.strip().split("#")[0].strip()
        for line in source.splitlines()
        if "_fast_llm()" in line or "_generation_llm()" in line
    ]
    assert "llm = _generation_llm()" in assignments, "generation is not on the A1 handle"
    assert "llm = _fast_llm()" not in assignments, "generation was handed the A2 fast model"
    assert "fast_llm = _fast_llm()" in assignments, "the A2 handle is gone"
