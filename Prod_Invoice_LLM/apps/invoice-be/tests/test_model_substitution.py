"""Feature 23 Phase 4 — the candidate-model override, and the routing enum.

Two related pieces of the 2026-08-23 "Model comparison" work in
`docs/feature_23_ai_control_tower.md`:

  1. `utils/llm.build_llm()` + `scripts/run_agent_eval.py`'s
     `--provider`/`--model` — running the same fixed case set against a
     candidate model without touching the application's configured default.
  2. `agents/query_agent.QueryRoutingSchema.route` as a real `Literal`, i.e. a
     JSON-schema `enum` rather than a plain string whose description merely asks
     for one of three values.

Scope note, in the same spirit as `test_agent_eval.py`'s: nothing here calls a
model. These prove the *mechanics* the comparison rests on — that the override
substitutes exactly the chat-path modules and nothing else, that it mutates no
setting, that it cannot reach the judge, that a candidate's rows are labelled,
and that the routing field now rejects an out-of-vocabulary value while keeping
the case-tolerance the plain `str` field had. What a candidate model actually
scores is a run of `scripts/run_agent_eval.py`, and its output is data, not a
test assertion.
"""
import os
from typing import Literal, get_args, get_origin
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlmodel import Session, create_engine, select

import agents.query_agent as query_agent
import agents.query_tools as query_tools
import agents.sage_orchestrator as sage_orchestrator
import utils.llm as llm_module
from agents.query_agent import QueryRoutingSchema
from config import get_settings
from models import AgentEvalRun
from scripts.run_agent_eval import (
    CANDIDATE_LLM_PATCH_TARGETS,
    _candidate_model,
    default_output_path,
    describe_model_under_test,
    persist,
)
# Moved out of tests/ to benchmarks/ on 2026-08-23 -- see benchmarks/__init__.py.
from benchmarks.agent_eval_golden_sample import GoldenCase
from utils.llm import LlmConfigurationError, MockInvoiceLLM, build_llm, get_llm

_CHAT_PATH_MODULES = (query_agent, query_tools, sage_orchestrator)


def _settings_snapshot() -> dict:
    settings = get_settings()
    return {
        name: getattr(settings, name, None)
        for name in (
            "LLM_PROVIDER",
            "AZURE_OPENAI_DEPLOYMENT_NAME",
            "AZURE_OPENAI_API_VERSION",
            "OLLAMA_MODEL",
            "OLLAMA_BASE_URL",
        )
    }


# ---------------------------------------------------------------------------
# build_llm — the construction logic, parameterised instead of config-driven
# ---------------------------------------------------------------------------


def test_build_llm_uses_the_named_model_not_the_configured_one(monkeypatch):
    """The whole point: the model comes from the argument, the rest from config."""
    settings = get_settings()
    monkeypatch.setattr(settings, "OLLAMA_MODEL", "llama3:8b", raising=False)

    client = build_llm("ollama", model="llama3.2:latest")

    assert client.model == "llama3.2:latest"
    # Everything the caller did NOT name still comes from settings.
    assert client.base_url == settings.OLLAMA_BASE_URL
    # And the setting itself is untouched -- this is a per-call argument, not a
    # reconfiguration.
    assert settings.OLLAMA_MODEL == "llama3:8b"


def test_build_llm_falls_back_to_the_configured_model_when_only_a_provider_is_named(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "OLLAMA_MODEL", "llama3.2:latest", raising=False)

    assert build_llm("ollama").model == "llama3.2:latest"


def test_build_llm_maps_model_onto_the_azure_deployment_name(monkeypatch):
    """A candidate on Azure is a new *deployment under the same resource*, so
    only the deployment name moves -- endpoint and key stay as configured."""
    settings = get_settings()
    monkeypatch.setattr(settings, "AZURE_OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(settings, "AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setattr(settings, "AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-5-mini")
    monkeypatch.setattr(settings, "AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

    client = build_llm("azure", model="gpt-4o", api_version="2024-08-01-preview")

    assert client.deployment_name == "gpt-4o"
    assert client.openai_api_version == "2024-08-01-preview"
    # The configured default is unchanged: this run only.
    assert settings.AZURE_OPENAI_DEPLOYMENT_NAME == "gpt-5-mini"
    assert settings.AZURE_OPENAI_API_VERSION == "2024-02-15-preview"


def test_an_explicitly_named_provider_refuses_to_become_the_mock(monkeypatch):
    """A benchmark table saying "gpt-4o" over MockInvoiceLLM's canned output is
    worse than no table. A named provider that cannot be built has to raise."""
    monkeypatch.setattr(get_settings(), "AZURE_OPENAI_API_KEY", "")

    with pytest.raises(LlmConfigurationError):
        build_llm("azure", model="gpt-4o", allow_mock_fallback=False)


def test_an_unknown_provider_raises_rather_than_silently_mocking():
    with pytest.raises(LlmConfigurationError):
        build_llm("anthropic", model="claude", allow_mock_fallback=False)


def test_get_llms_own_fail_safe_fallback_is_unchanged(monkeypatch):
    """`get_llm()` keeps its local-dev behaviour exactly: no key means the mock,
    not an exception. Only an *explicit* caller opts out of that."""
    monkeypatch.setattr(get_settings(), "LLM_PROVIDER", "azure")
    monkeypatch.setattr(get_settings(), "AZURE_OPENAI_API_KEY", "your_key_here")

    assert isinstance(get_llm(), MockInvoiceLLM)


def test_get_llm_still_resolves_provider_and_model_from_settings(monkeypatch):
    monkeypatch.setattr(get_settings(), "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(get_settings(), "OLLAMA_MODEL", "llama3.2:latest", raising=False)

    assert get_llm().model == "llama3.2:latest"


def test_an_unknown_provider_still_mocks_for_get_llm(monkeypatch):
    monkeypatch.setattr(get_settings(), "LLM_PROVIDER", "not-a-provider")

    assert isinstance(get_llm(), MockInvoiceLLM)


# ---------------------------------------------------------------------------
# The --provider/--model override — test-time only, by construction
# ---------------------------------------------------------------------------


def test_no_flags_means_no_patching_at_all():
    """The baseline run's code path has to be what it was before this existed."""
    originals = [module.get_llm for module in _CHAT_PATH_MODULES]

    with _candidate_model(None, None) as label:
        assert label is None
        assert [module.get_llm for module in _CHAT_PATH_MODULES] == originals


def test_the_override_substitutes_every_chat_path_module(monkeypatch):
    monkeypatch.setattr(get_settings(), "LLM_PROVIDER", "azure")
    originals = [module.get_llm for module in _CHAT_PATH_MODULES]

    with _candidate_model("mock", None) as label:
        assert label == "mock:mock"
        for module in _CHAT_PATH_MODULES:
            # The real call sites call `get_llm(max_tokens=...)`; the override
            # has to be callable the same way.
            assert isinstance(module.get_llm(), MockInvoiceLLM)
            assert isinstance(module.get_llm(max_tokens=512), MockInvoiceLLM)

    assert [module.get_llm for module in _CHAT_PATH_MODULES] == originals


def test_the_patch_targets_are_the_modules_that_actually_resolve_get_llm():
    """Drift guard. Each named module does `from utils.llm import get_llm`, so
    the module attribute is the binding that must be replaced -- if one of them
    stops importing it that way, or a new chat-path module starts, this fails
    rather than the override silently covering less than it claims."""
    for target in CANDIDATE_LLM_PATCH_TARGETS:
        module_name, attribute = target.rsplit(".", 1)
        module = __import__(module_name, fromlist=[attribute])
        assert getattr(module, attribute) is llm_module.get_llm


def test_the_override_mutates_no_setting_and_no_environment_variable():
    """Property 1 of the module docstring: this can never affect the running
    application's default provider, because it writes nothing."""
    before_settings = _settings_snapshot()
    before_env = dict(os.environ)

    with _candidate_model("mock", "some-candidate-model"):
        assert _settings_snapshot() == before_settings
        assert dict(os.environ) == before_env

    assert _settings_snapshot() == before_settings
    assert dict(os.environ) == before_env


def test_the_override_cannot_reach_the_judge():
    """Property 2: comparability. `services/agent_eval.py` resolves its default
    judge through `utils.llm.get_llm` directly, which is deliberately not in the
    patch list -- so a candidate run is graded by the same grader as the
    baseline it is compared against."""
    assert "services.agent_eval.get_llm" not in CANDIDATE_LLM_PATCH_TARGETS
    assert "utils.llm.get_llm" not in CANDIDATE_LLM_PATCH_TARGETS

    with _candidate_model("mock", None):
        # The judge's own resolution path is untouched inside the block.
        assert llm_module.get_llm is not query_agent.get_llm


def test_a_broken_candidate_fails_before_any_case_runs(monkeypatch):
    """A paid run should not get 20 turns in before discovering the candidate
    was never constructible."""
    monkeypatch.setattr(get_settings(), "AZURE_OPENAI_API_KEY", "")

    with pytest.raises(LlmConfigurationError):
        with _candidate_model("azure", "gpt-4o"):
            pytest.fail("the block must not be entered")


def test_the_override_is_unwound_even_when_the_run_raises():
    originals = [module.get_llm for module in _CHAT_PATH_MODULES]

    with pytest.raises(RuntimeError):
        with _candidate_model("mock", None):
            raise RuntimeError("a turn blew up")

    assert [module.get_llm for module in _CHAT_PATH_MODULES] == originals


# ---------------------------------------------------------------------------
# Labelling — a candidate's numbers must never read as the baseline's
# ---------------------------------------------------------------------------


def test_a_baseline_run_is_labelled_none_not_a_string():
    """None means "the application's own configured model" everywhere in the
    runner; a literal "default" would leave a comparison table with a row that
    does not name its model."""
    assert describe_model_under_test(None, None) is None


def test_a_provider_alone_resolves_that_providers_configured_model(monkeypatch):
    monkeypatch.setattr(get_settings(), "OLLAMA_MODEL", "llama3.2:latest", raising=False)
    monkeypatch.setattr(get_settings(), "AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-5-mini")

    assert describe_model_under_test("ollama", None) == "ollama:llama3.2:latest"
    assert describe_model_under_test("azure", None) == "azure:gpt-5-mini"


def test_a_model_alone_is_read_against_the_configured_provider(monkeypatch):
    monkeypatch.setattr(get_settings(), "LLM_PROVIDER", "azure")

    assert describe_model_under_test(None, "gpt-4o") == "azure:gpt-4o"


def test_a_candidate_run_does_not_overwrite_the_baseline_output_file():
    baseline = default_output_path(None)
    candidate = default_output_path("azure:gpt-4o")

    assert baseline.endswith("agent_eval_output.json")
    assert candidate != baseline
    assert candidate.endswith("agent_eval_output_azure_gpt_4o.json")


def test_persisted_candidate_rows_carry_the_model_under_test(tmp_path):
    """If a candidate run is persisted at all (`--persist-candidate`), every row
    says so, so the baseline trend can exclude it."""
    url = f"sqlite:///{tmp_path / 'eval.db'}"
    case = GoldenCase(
        case_id="c1", question="q?", expected_answer="a", source="test", why_on_file="test"
    )
    turns = [
        {
            "case_id": "c1",
            "agent_name": "chat.default_path",
            "question": "q?",
            "answer": "a",
            "model_under_test": "azure:gpt-4o",
            "latency_ms": 1.0,
            "llm_call_count": 1,
        },
        {
            "case_id": "c1",
            "agent_name": "chat.default_path",
            "question": "q?",
            "answer": "a",
            "model_under_test": None,
            "latency_ms": 1.0,
            "llm_call_count": 1,
        },
    ]

    assert persist(turns, {"c1": case}, url) == 2

    engine = create_engine(url)
    with Session(engine) as session:
        notes = [row.notes for row in session.exec(select(AgentEvalRun)).all()]
    engine.dispose()

    assert any("model_under_test=azure:gpt-4o" in n for n in notes)
    # A baseline row carries no such marker -- absence is what makes it baseline.
    assert any("model_under_test" not in n for n in notes)


# ---------------------------------------------------------------------------
# QueryRoutingSchema.route — a real enum, not a description that asks nicely
# ---------------------------------------------------------------------------


def test_the_route_field_is_a_literal_of_exactly_the_three_routes():
    annotation = QueryRoutingSchema.model_fields["route"].annotation

    assert get_origin(annotation) is Literal
    assert set(get_args(annotation)) == {"RAG", "SQL", "CHAT"}


def test_the_generated_json_schema_carries_a_real_enum():
    """This is the whole mechanism: a provider constrains generation against
    `enum`, and ignores a description that merely asks for the same thing."""
    schema = QueryRoutingSchema.model_json_schema()

    assert schema["properties"]["route"]["enum"] == ["RAG", "SQL", "CHAT"]
    assert schema["properties"]["route"]["type"] == "string"
    # Gap-era strict-mode requirement, unchanged by this: `extra="forbid"`.
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize("raw", ["SQL", "sql", " sql ", "Sql", "'RAG'", '"chat"'])
def test_case_and_quoting_tolerance_is_preserved(raw):
    """`classify_query()` has always done `result.route.upper()`, so a model
    answering "sql" routed correctly before the Literal. Normalising before
    validation keeps that exactly -- the enum tightens the vocabulary, not the
    formatting."""
    assert QueryRoutingSchema(route=raw, reasoning="r").route in {"RAG", "SQL", "CHAT"}


@pytest.mark.parametrize("raw", ["DATABASE", "sql_query", "", "RAGG", None, 7])
def test_an_out_of_vocabulary_route_is_now_rejected(raw):
    """The behaviour this buys. `run_query_agent()` dispatches
    `if SQL / elif RAG / else: CHAT`, so before this an invented route fell
    through to the conversational branch: a chatty answer, no retrieval, no
    signal that routing had failed. Now it raises, and `classify_query()`'s
    existing except-block falls back to RAG, which does retrieve."""
    with pytest.raises(ValidationError):
        QueryRoutingSchema(route=raw, reasoning="r")


def test_a_rejected_route_falls_back_to_rag_rather_than_propagating(monkeypatch, caplog):
    """End to end through the real function: an invalid value from the model is
    a logged fallback, not a 500 and not a silent CHAT."""

    class _HallucinatingLLM:
        def with_structured_output(self, schema):
            class _Wrapper:
                def invoke(self, prompt, **kwargs):
                    return schema(route="DATABASE_LOOKUP", reasoning="invented")

            return _Wrapper()

    monkeypatch.setattr(query_agent, "get_llm", lambda *a, **k: _HallucinatingLLM())

    # A question that matches neither keyword list, so the LLM path is reached.
    assert query_agent.classify_query("does any document mention a delivery note") == "RAG"


def test_the_mock_llms_own_routes_are_all_valid_under_the_enum():
    """`MockInvoiceLLM` is the local-dev and test-suite router; every branch of
    its routing arm has to still construct."""
    mock = MockInvoiceLLM()
    structured = mock.with_structured_output(QueryRoutingSchema)

    for prompt, expected in (
        ("what is my total spend", "SQL"),
        ("hello there", "CHAT"),
        ("what do the documents say about warranties", "RAG"),
    ):
        assert structured.invoke(prompt).route == expected


def test_a_valid_route_still_round_trips_through_the_session_id_free_path():
    """Guard against the normaliser accidentally mangling an already-correct
    value (the overwhelmingly common case on Azure: 30/30 live gpt-5-mini
    classifications returned exactly one of the three)."""
    assert QueryRoutingSchema(route="SQL", reasoning=str(uuid4())).route == "SQL"
