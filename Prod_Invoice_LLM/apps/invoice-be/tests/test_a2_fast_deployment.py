"""Feature 6.1 item A2 — the non-reasoning half of a chat turn on a fast deployment.

Four call sites in a turn do not reason: `chat.classify` picks a label,
`chat.sql_summary` phrases rows deterministic code already computed,
`chat.rag_answer` answers from retrieved text, and Feature 26's narration
describes a diff table that `compare_reference_to_invoices()` built. Paying a
reasoning model's thinking tokens for those costs seconds and buys nothing —
measured 2026-09-03, classify 3.1 s and summary 3.6 s of a 27.8 s median turn.

The one call that *does* reason is SQL generation, and it must not move: item A1
tunes its `reasoning_effort` separately. The last test in this file is the guard
against exactly that mistake.
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


def test_an_unset_deployment_name_changes_nothing(monkeypatch, azure_provider):
    """The default must be bit-identical to life before A2 existed."""
    monkeypatch.setattr(config.settings, "AZURE_OPENAI_FAST_DEPLOYMENT_NAME", "", raising=False)
    sentinel = MagicMock(name="default-llm")

    with patch.object(query_agent, "get_llm", return_value=sentinel) as default, \
         patch.object(query_agent, "build_llm") as built:
        assert query_agent._fast_llm() is sentinel

    default.assert_called_once()
    built.assert_not_called()


def test_a_set_deployment_name_is_used(monkeypatch, azure_provider):
    monkeypatch.setattr(
        config.settings, "AZURE_OPENAI_FAST_DEPLOYMENT_NAME", "gpt-4o", raising=False
    )
    fast = MagicMock(name="fast-llm")

    with patch.object(query_agent, "build_llm", return_value=fast) as built, \
         patch.object(query_agent, "get_llm") as default:
        assert query_agent._fast_llm() is fast

    built.assert_called_once_with("azure", model="gpt-4o")
    default.assert_not_called()


def test_whitespace_only_is_treated_as_unset(monkeypatch, azure_provider):
    monkeypatch.setattr(
        config.settings, "AZURE_OPENAI_FAST_DEPLOYMENT_NAME", "   ", raising=False
    )
    sentinel = MagicMock()
    with patch.object(query_agent, "get_llm", return_value=sentinel), \
         patch.object(query_agent, "build_llm") as built:
        assert query_agent._fast_llm() is sentinel
    built.assert_not_called()


def test_a_non_azure_provider_ignores_the_setting(monkeypatch):
    """Mock mode is how the whole suite runs; it must be unaffected either way."""
    monkeypatch.setattr(config.settings, "LLM_PROVIDER", "mock", raising=False)
    monkeypatch.setattr(
        config.settings, "AZURE_OPENAI_FAST_DEPLOYMENT_NAME", "gpt-4o", raising=False
    )
    sentinel = MagicMock()
    with patch.object(query_agent, "get_llm", return_value=sentinel), \
         patch.object(query_agent, "build_llm") as built:
        assert query_agent._fast_llm() is sentinel
    built.assert_not_called()


def test_a_bad_deployment_name_degrades_instead_of_killing_the_turn(monkeypatch, azure_provider):
    """A routing call that raises is a dead chat turn; a slower one is not."""
    monkeypatch.setattr(
        config.settings, "AZURE_OPENAI_FAST_DEPLOYMENT_NAME", "does-not-exist", raising=False
    )
    sentinel = MagicMock(name="default-llm")

    with patch.object(query_agent, "build_llm", side_effect=RuntimeError("no such deployment")), \
         patch.object(query_agent, "get_llm", return_value=sentinel):
        assert query_agent._fast_llm() is sentinel


def test_sql_generation_is_never_handed_the_fast_model():
    """The trap A2 is one careless edit away from.

    `_run_query_agent` holds one reasoning `llm` that `run_sql_generation_loop`
    uses, plus a separate `fast_llm` for summary and RAG. Generation is the only
    call in the turn that genuinely reasons -- schema, joins, the three-attempt
    repair loop -- and A1 tunes its `reasoning_effort`. If a future edit passes
    `fast_llm` to the generation loop, the two items silently fight and the golden
    set is the only thing left to notice. Assert it at the source, where it is
    unambiguous.
    """
    import inspect

    source = inspect.getsource(query_agent._run_query_agent)

    assert "fast_llm = _fast_llm()" in source, "the A2 handle is gone"
    # Item A1 later replaced the bare `get_llm()` here with `_generation_llm()`,
    # which returns exactly `get_llm()` unless a reasoning budget is configured.
    # Either spelling means "the reasoning handle is still separate"; neither
    # being present means A2 swallowed generation.
    assert (
        "llm = _generation_llm()" in source or "llm = get_llm()" in source
    ), "the reasoning handle is gone"

    # Every generation-loop call in this function must receive the reasoning handle.
    for call in ("run_sql_generation_loop(", "build_sql_system_prompt("):
        idx = 0
        while True:
            idx = source.find(call, idx)
            if idx == -1:
                break
            window = source[idx : idx + 400]
            assert "llm=fast_llm" not in window, (
                f"{call} was handed the fast model -- A2 must never touch SQL generation"
            )
            idx += len(call)


def test_the_two_narration_sites_use_the_fast_model():
    import inspect

    for func in (
        query_agent._run_attached_document_turn,
        query_agent._run_attachment_content_branch,
    ):
        source = inspect.getsource(func)
        assert "_fast_llm()" in source, f"{func.__name__} is not on the fast deployment"
        assert "llm = get_llm()" not in source, f"{func.__name__} still builds the default"
