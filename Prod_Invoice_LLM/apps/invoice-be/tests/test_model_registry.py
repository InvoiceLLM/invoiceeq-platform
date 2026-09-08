"""Gap 465 -- utils/model_registry and the consumers that now read it.

What these pin:

  1. Longest-prefix matching: a deployment named after a model resolves to
     that model's catalog entry, and `gpt-5.6-luna` never collapses onto
     `gpt-5`.
  2. The context limit for the live deployment (`gpt-5-mini`) is the 400k the
     model has, not the 8k default that used to block large invoices.
  3. `check_token_guardrails` reads the registry, so an unknown model gets
     128k and a warning rather than 8k and a silent AUDIT_REQUIRED.
  4. Roles: `fast`/`judge` fall back to `primary` when blank.
  5. `build_llm` drops `reasoning_effort` for a deployment the registry marks
     non-reasoning, and keeps it for one it marks reasoning-capable.
  6. `_run_ocr` passes `DOC_INTEL_MODEL_ID` through; `get_embedding_model`
     loads `EMBEDDING_MODEL_NAME`; the query-embedding cache key carries it.
"""
from unittest.mock import MagicMock, patch

import pytest

from config import get_settings
from utils import model_registry as reg
from utils.token_management import DEFAULT_CONTEXT_LIMIT, check_token_guardrails


# --- 1/2: catalog lookup ----------------------------------------------------

@pytest.mark.parametrize(
    "name, expected_key",
    [
        ("gpt-5-mini", "gpt-5-mini"),
        ("GPT-5-MINI", "gpt-5-mini"),
        ("gpt-5-mini-2025-08-07", "gpt-5-mini"),
        ("gpt-5-mini-eu", "gpt-5-mini"),
        ("gpt-5", "gpt-5"),
        ("gpt-5.6-luna", "gpt-5.6-luna"),
        ("gpt-5.6-terra", "gpt-5.6-terra"),
        ("gpt-5.6-sol", "gpt-5.6-sol"),
        ("gpt-4o", "gpt-4o"),
        ("gpt-4o-mini", "gpt-4o-mini"),
        ("llama3.2:latest", "llama3.2"),
        ("llama3:8b", "llama3"),
        ("openai/gpt-4o", "gpt-4o"),
    ],
)
def test_catalog_longest_prefix_match(name, expected_key):
    assert reg.catalog_entry_for(name) is reg.MODEL_CATALOG[expected_key]


def test_luna_does_not_collapse_onto_gpt5():
    assert reg.catalog_entry_for("gpt-5.6-luna") is not reg.MODEL_CATALOG["gpt-5"]
    # Feature 29 task 29.1: the 5.6 family is 1,050,000 wide, not 400,000. The
    # old value was a copy of the GPT-5 row and would have had the token
    # guardrail refuse prompts the model actually accepts.
    assert reg.context_limit_for("gpt-5.6-luna") == 1_050_000
    assert reg.prices_for("gpt-5.6-luna") == (0.20, 1.20)


def test_the_five_six_family_input_budget_is_smaller_than_its_context():
    """Task 29.1. Total context and usable INPUT budget are different numbers on
    this family (1,050,000 vs 922,000) -- the rest is reserved for reasoning and
    output. A prompt builder that spends the whole context window is the bug this
    field exists to prevent."""
    for name in ("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"):
        assert reg.context_limit_for(name) == 1_050_000
        assert reg.max_input_tokens_for(name) == 922_000

    # Every other family publishes one number; the helper falls back to it, so a
    # caller never has to special-case `None`.
    assert reg.max_input_tokens_for("gpt-5-mini") == reg.context_limit_for("gpt-5-mini")
    assert reg.max_input_tokens_for("never-heard-of-it") == 128_000


def test_recall_is_recorded_separately_from_context_size():
    """Task 29.1. A 1M-token window is not a 1M-token memory, and conflating the
    two is exactly how Luna would end up reading long contracts. The warning is
    on the catalog entry, next to the size, so the two are read together."""
    luna = reg.recall_note_for("gpt-5.6-luna")
    terra = reg.recall_note_for("gpt-5.6-terra")
    assert "41%" in luna and "3/3" in luna
    assert "89%" in terra
    # Not every model carries one; the helper is safe on the ones that do not.
    assert reg.recall_note_for("gpt-5-mini") == ""
    assert reg.recall_note_for("never-heard-of-it") == ""


def test_there_is_no_long_doc_role_after_29_10():
    """Task 29.10 / Gap 489 (2026-09-07). Luna and Terra both scored 3/3 on the
    five long-document golden cases, so the 2-point rule kept Luna for everything,
    Terra's deployment was deleted, and the inert `long_doc` role and its
    `AZURE_OPENAI_LONG_DOC_DEPLOYMENT_NAME` setting were removed rather than left
    as one more variable nobody sets. This pins the removal."""
    from typing import get_args
    from config import Settings

    assert "long_doc" not in get_args(reg.Role)
    assert "AZURE_OPENAI_LONG_DOC_DEPLOYMENT_NAME" not in Settings.model_fields
    assert set(get_args(reg.Role)) == {"primary", "fast", "judge", "chat_summary"}


def test_chat_summary_role_prefers_the_judge_deployment_over_the_primary():
    """Feature 29 decision 2 (task 29.5). Every environment already sets the
    judge to gpt-5-mini, so an environment that never sets the new variable must
    still narrate the full-record route on gpt-5-mini rather than on Luna."""

    class _S:
        LLM_PROVIDER = "azure"
        AZURE_OPENAI_DEPLOYMENT_NAME = "gpt-5.6-luna"
        AZURE_OPENAI_FAST_DEPLOYMENT_NAME = "gpt-5.6-luna"
        AZURE_OPENAI_JUDGE_DEPLOYMENT_NAME = "gpt-5-mini"
        AZURE_OPENAI_CHAT_SUMMARY_DEPLOYMENT_NAME = ""
        AZURE_OPENAI_API_VERSION = "2024-10-21"

    settings = _S()
    assert reg.resolve_model("chat_summary", settings).deployment == "gpt-5-mini"

    settings.AZURE_OPENAI_CHAT_SUMMARY_DEPLOYMENT_NAME = "gpt-5.6-terra"
    assert reg.resolve_model("chat_summary", settings).deployment == "gpt-5.6-terra"


def test_deleted_deployments_keep_their_catalog_entry():
    """Decision 9 deleted `gpt-5.6-sol` and `gpt-6-astra` from the dev account.
    The catalog rows stay: a deleted deployment still has historical telemetry
    and cost rows to price, and a row removed here would silently reprice them at
    zero via `DEFAULT_SPEC`."""
    for name in ("gpt-5.6-sol", "gpt-6-astra"):
        entry = reg.catalog_entry_for(name)
        assert entry is not reg.DEFAULT_SPEC
        assert "DELETED" in entry.note
    assert reg.cost_usd("gpt-6-astra", 1_000_000, 0) == pytest.approx(10.00)


def test_live_primary_has_a_real_context_window():
    assert reg.context_limit_for("gpt-5-mini") == 400_000
    assert reg.encoding_for("gpt-5-mini") == "o200k_base"
    assert reg.catalog_entry_for("gpt-5-mini").reasoning_capable is True


def test_unknown_model_gets_default_spec_and_one_warning(caplog):
    reg._warned.discard("totally-unknown-model")
    with caplog.at_level("WARNING"):
        first = reg.catalog_entry_for("totally-unknown-model")
        second = reg.catalog_entry_for("totally-unknown-model")
    assert first is reg.DEFAULT_SPEC and second is reg.DEFAULT_SPEC
    assert sum("not in utils/model_registry" in r.message for r in caplog.records) == 1


def test_cost_is_priced_per_million():
    assert reg.cost_usd("gpt-5-mini", 1_000_000, 1_000_000) == pytest.approx(2.25)
    assert reg.cost_usd("gpt-5.6-terra", 500_000, 0) == pytest.approx(1.00)
    assert reg.cost_usd("mock", 10, 10) == 0.0


# --- 3: token guardrail reads the registry ----------------------------------

def test_guardrail_uses_registry_limit_for_gpt5_mini():
    ok, tokens, limit = check_token_guardrails("word " * 5000, [], "t", model_name="gpt-5-mini", estimated_output=16384)
    assert limit == 400_000
    assert ok is True


def test_guardrail_default_is_no_longer_8k():
    assert DEFAULT_CONTEXT_LIMIT == reg.DEFAULT_SPEC.context_limit == 128_000
    ok, _, limit = check_token_guardrails("word " * 5000, [], "t", model_name="never-heard-of-it")
    assert limit == 128_000 and ok is True


def test_guardrail_still_blocks_a_genuinely_oversized_prompt():
    with patch.dict(reg.MODEL_CATALOG, {"tiny-model": reg.CatalogEntry(1_000, "cl100k_base", False, 0, 0)}):
        ok, tokens, limit = check_token_guardrails("word " * 2000, [], "t", model_name="tiny-model", estimated_output=100)
    assert limit == 1_000 and ok is False and tokens > 1_000


# --- 4: roles -----------------------------------------------------------------

def test_roles_fall_back_to_primary_when_blank(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "LLM_PROVIDER", "azure")
    monkeypatch.setattr(s, "AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-5-mini")
    monkeypatch.setattr(s, "AZURE_OPENAI_FAST_DEPLOYMENT_NAME", "")
    monkeypatch.setattr(s, "AZURE_OPENAI_JUDGE_DEPLOYMENT_NAME", "")
    monkeypatch.setattr(s, "AZURE_OPENAI_API_VERSION", "2024-10-21")
    p, f, j = (reg.resolve_model(r) for r in ("primary", "fast", "judge"))
    assert p.deployment == f.deployment == j.deployment == "gpt-5-mini"
    assert p.api_version == "2024-10-21" and p.is_azure


def test_roles_resolve_their_own_deployment_when_set(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "LLM_PROVIDER", "azure")
    monkeypatch.setattr(s, "AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-5-mini")
    monkeypatch.setattr(s, "AZURE_OPENAI_FAST_DEPLOYMENT_NAME", "gpt-5.6-luna")
    monkeypatch.setattr(s, "AZURE_OPENAI_JUDGE_DEPLOYMENT_NAME", "gpt-5.6-terra")
    assert reg.resolve_model("fast").deployment == "gpt-5.6-luna"
    assert reg.resolve_model("fast").price_out == 1.20
    assert reg.resolve_model("judge").deployment == "gpt-5.6-terra"
    snap = reg.registry_snapshot()
    assert snap["fast"]["deployment"] == "gpt-5.6-luna"
    assert snap["doc_intel_model_id"] == s.DOC_INTEL_MODEL_ID
    assert snap["embedding_model"] == s.EMBEDDING_MODEL_NAME


def test_non_azure_provider_has_one_model_for_every_role(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(s, "OLLAMA_MODEL", "llama3.2:latest")
    assert reg.resolve_model("fast").deployment == "llama3.2:latest"
    assert reg.resolve_model("judge").provider == "ollama"


# --- 5: build_llm honours reasoning_capable ------------------------------------

def _azure_ready(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "AZURE_OPENAI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(s, "AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setattr(s, "AZURE_OPENAI_API_VERSION", "2024-10-21")
    return s


def test_build_llm_drops_reasoning_effort_for_non_reasoning_deployment(monkeypatch, caplog):
    from utils import llm as llm_module

    _azure_ready(monkeypatch)
    captured = {}

    class _Fake:
        def __init__(self, **kw):
            captured.update(kw)

    with patch.object(llm_module, "AzureChatOpenAI", _Fake), caplog.at_level("WARNING"):
        llm_module.build_llm("azure", model="gpt-4o", reasoning_effort="low")
    assert "reasoning_effort" not in captured
    assert any("registry marks non-reasoning" in r.message for r in caplog.records)


def test_build_llm_keeps_reasoning_effort_for_reasoning_deployment(monkeypatch):
    from utils import llm as llm_module

    _azure_ready(monkeypatch)
    captured = {}

    class _Fake:
        def __init__(self, **kw):
            captured.update(kw)

    with patch.object(llm_module, "AzureChatOpenAI", _Fake):
        llm_module.build_llm("azure", model="gpt-5.6-luna", reasoning_effort="low")
    assert captured["reasoning_effort"] == "low"
    assert captured["azure_deployment"] == "gpt-5.6-luna"
    assert captured["api_version"] == "2024-10-21"


def test_get_llm_for_role_uses_the_role_deployment(monkeypatch):
    from utils import llm as llm_module

    s = _azure_ready(monkeypatch)
    monkeypatch.setattr(s, "LLM_PROVIDER", "azure")
    monkeypatch.setattr(s, "AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-5-mini")
    monkeypatch.setattr(s, "AZURE_OPENAI_JUDGE_DEPLOYMENT_NAME", "gpt-5.6-terra")
    captured = {}

    class _Fake:
        def __init__(self, **kw):
            captured.update(kw)

    with patch.object(llm_module, "AzureChatOpenAI", _Fake):
        llm_module.get_llm_for_role("judge", max_tokens=123)
    assert captured["azure_deployment"] == "gpt-5.6-terra"
    assert captured["max_tokens"] == 123


# --- 6: non-LLM consumers -----------------------------------------------------

def test_run_ocr_passes_doc_intel_model_id_from_settings(monkeypatch):
    from queue_worker import handlers

    s = get_settings()
    monkeypatch.setattr(s, "LLM_PROVIDER", "azure")
    monkeypatch.setattr(s, "AZURE_DOC_INTEL_ENDPOINT", "https://di.example.com/")
    monkeypatch.setattr(s, "AZURE_DOC_INTEL_KEY", "k")
    monkeypatch.setattr(s, "DOC_INTEL_MODEL_ID", "prebuilt-layout")

    fake_result = MagicMock(content="hello", pages=[], documents=[])
    fake_client = MagicMock()
    fake_client.begin_analyze_document.return_value.result.return_value = fake_result

    with patch("queue_worker.handlers.download_pdf_from_storage", return_value=b"%PDF"), \
         patch("azure.ai.documentintelligence.DocumentIntelligenceClient", return_value=fake_client):
        out = handlers._run_ocr("x.pdf", s)
    assert out["content"] == "hello"
    assert fake_client.begin_analyze_document.call_args.kwargs["model_id"] == "prebuilt-layout"


def test_embedding_model_name_and_cache_prefix_come_from_settings(monkeypatch):
    import chroma_client

    s = get_settings()
    monkeypatch.setattr(s, "MOCK_EMBEDDINGS", False)
    monkeypatch.setattr(s, "EMBEDDING_MODEL_NAME", "BAAI/bge-m3")
    monkeypatch.setattr(chroma_client, "_embedding_model", None)
    with patch.object(chroma_client, "SentenceTransformer") as st:
        chroma_client.get_embedding_model()
    st.assert_called_once_with("BAAI/bge-m3")
    assert chroma_client._query_embedding_prefix() == "query_embedding:bge-m3:v1:"
    monkeypatch.setattr(s, "EMBEDDING_MODEL_NAME", "intfloat/multilingual-e5-large")
    assert chroma_client._query_embedding_prefix() == "query_embedding:multilingual-e5-large:v1:"
