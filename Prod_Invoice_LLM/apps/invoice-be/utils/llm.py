import re
import logging
from langchain_openai import AzureChatOpenAI
from langchain_ollama import ChatOllama
from config import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Feature 26 Part 2, task H1 (E-8 as replaced by amendment B5).
#
# CONTRACT FOR WHOEVER BUILDS H5 — read this before writing the content-branch
# prompt in `agents/query_agent.py::_run_attached_document_turn()`:
#
#   The content-branch system prompt MUST open with (or otherwise contain,
#   verbatim) the string below. `MockInvoiceLLM.invoke()` keys its canned
#   document-content answer on it, and nothing else in the prompt identifies the
#   branch. Import this constant rather than retyping the sentence — a
#   re-typed variant that drifts by one word silently falls through to the SAGE
#   greeting again, which is the exact failure H1 exists to remove.
#
#       from utils.llm import CONTENT_BRANCH_PROMPT_MARKER
#
# It is deliberately apostrophe-free and punctuation-free so no smart-quote or
# comma edit in the prompt can break the match, and it is matched
# case-insensitively (the whole `invoke()` body lowercases the prompt first).
# ---------------------------------------------------------------------------
CONTENT_BRANCH_PROMPT_MARKER = (
    "You are answering a question about the content of an attached document"
)


class MockInvoiceLLM:
    """High-fidelity Mock LLM engine for local development, automated testing,
    and Gap 280 architecture verification without external cloud dependencies."""

    def __init__(self, max_tokens: int | None = None):
        self.max_tokens = max_tokens

    def with_structured_output(self, schema_cls):
        parent = self

        class StructuredWrapper:
            def invoke(self, prompt: str, **kwargs):
                return parent._generate_structured(prompt, schema_cls)

        return StructuredWrapper()

    def _generate_structured(self, prompt: str, schema_cls):
        schema_name = getattr(schema_cls, "__name__", str(schema_cls)).lower()
        p_lower = prompt.lower()

        # 1. Routing classification
        if "routing" in schema_name:
            if any(w in p_lower for w in ["total", "spend", "spent", "sum", "how many", "count", "vendor", "invoice", "show", "list", "status", "audit", "flag"]):
                return schema_cls(route="SQL", reasoning="Query relates to structured invoice, spend, or vendor data.")
            if any(w in p_lower for w in ["hello", "hi", "hey", "who are you", "what can you do", "help"]):
                return schema_cls(route="CHAT", reasoning="Conversational greeting and feature inquiry.")
            return schema_cls(route="RAG", reasoning="Semantic document lookup across invoice text.")

        # 2. SQL Query Generation
        if "sql" in schema_name:
            m = re.search(r"tenant_id\s*=\s*'([a-f0-9\-]+)'", prompt, re.IGNORECASE)
            tenant_id_str = m.group(1) if m else "00000000-0000-0000-0000-000000000000"

            if any(w in p_lower for w in ["audit", "flag", "flagged", "review"]):
                sql = f"SELECT id, invoice_number, vendor_name, grand_total, currency, status, invoice_date FROM invoice WHERE tenant_id = '{tenant_id_str}' AND status = 'AUDIT_REQUIRED' ORDER BY grand_total DESC"
                return schema_cls(sql=sql, explanation_or_error="Invoices flagged for audit review.")

            if any(w in p_lower for w in ["vendor", "who", "highest", "most", "top"]):
                sql = f"SELECT vendor_name, currency, SUM(grand_total) AS total_spend, COUNT(id) AS invoice_count FROM invoice WHERE tenant_id = '{tenant_id_str}' GROUP BY vendor_name, currency ORDER BY total_spend DESC LIMIT 5"
                return schema_cls(sql=sql, explanation_or_error="Top vendors ranked by total expenditure.")

            if any(w in p_lower for w in ["total", "sum", "spent", "spend", "how much"]):
                sql = f"SELECT currency, SUM(grand_total) AS total_spend, COUNT(id) AS total_invoices FROM invoice WHERE tenant_id = '{tenant_id_str}' GROUP BY currency"
                return schema_cls(sql=sql, explanation_or_error="Total expenditure aggregated by currency.")

            # Default: list all invoices
            sql = f"SELECT id, invoice_number, vendor_name, grand_total, currency, status, invoice_date FROM invoice WHERE tenant_id = '{tenant_id_str}' ORDER BY invoice_date DESC LIMIT 10"
            return schema_cls(sql=sql, explanation_or_error="List of recent invoices from database.")

        try:
            return schema_cls()
        except Exception:
            return schema_cls.model_construct()

    def invoke(self, prompt: str, **kwargs):
        class MockResponse:
            def __init__(self, content: str):
                self.content = content

        p_lower = prompt.lower()

        # Attached-document CONTENT branch (Feature 26 Part 2, H1).
        #
        # Checked FIRST, deliberately: the RAG branch below matches the bare
        # substring "rag", which occurs inside ordinary English words
        # ("storage", "average", "fragrance", "paragraph"). The content-branch
        # prompt interpolates verbatim spans of a user-uploaded document, so it
        # is a matter of time before one of those words appears and a document
        # answer gets served the invoice-RAG canned text. Ordering, not a
        # tightening of the RAG marker, because that marker is load-bearing for
        # existing tests and is not this task's to change.
        if CONTENT_BRANCH_PROMPT_MARKER.lower() in p_lower:
            content = (
                "### 📎 Attached Document — What It Says\n\n"
                "Reading the document you attached to this conversation:\n\n"
                "- **Payment terms**: Net 30 days from the date of issue.\n"
                "- **Delivery**: Within 14 working days of order acceptance.\n"
                "- **Validity**: The quoted prices hold for 30 days.\n\n"
                "I can tell you what this document says. To check it against your "
                "invoices, ask me to compare them.\n\n"
                "The quoted passages below show where each point comes from in the document."
            )
            return MockResponse(content=content)

        # SQL summary / synthesis
        if any(marker in p_lower for marker in ["database query results", "columns returned", "sql query results", "query result:"]):
            content = (
                "### 📊 Invoice Data Analysis\n\n"
                "I queried your database and retrieved the following summary:\n\n"
                "- **Status**: Live query executed successfully.\n"
                "- **Results**: Data retrieved and verified across your workspace.\n\n"
                "You can inspect the exact SQL query executed in the **SQL Audit Drawer** above."
            )
            return MockResponse(content=content)

        # RAG / document context
        if any(marker in p_lower for marker in ["context chunks", "relevant invoice excerpts", "rag"]):
            content = (
                "### 📄 Document Content Insights\n\n"
                "Based on the analyzed invoice documents:\n\n"
                "- **Payment Terms**: Standard Net 30 terms apply.\n"
                "- **Categories**: Invoices cover hardware purchases, cloud infrastructure, and consulting.\n\n"
                "Click on the citation pills below to view the source invoices."
            )
            return MockResponse(content=content)

        # Casual conversational chat
        content = (
            "Hello! I am **SAGE**, your AI Invoice Processing Assistant. 🧠✨\n\n"
            "I can help you explore your invoices and financial metrics:\n\n"
            "- 💰 **Spend Summaries**: *'What is my total spend across all invoices?'*\n"
            "- 🏢 **Vendor Analytics**: *'Which vendor do I spend the most with?'*\n"
            "- 📋 **Audit Queue**: *'Show me all invoices flagged for review'*\n"
            "- 📑 **All Invoices**: *'Show me all invoices'* \n\n"
            "How can I help you today?"
        )
        return MockResponse(content=content)


class LlmConfigurationError(RuntimeError):
    """An explicitly-requested provider/model could not be constructed.

    Only ever raised when ``allow_mock_fallback=False`` — i.e. by a caller that
    named a provider on purpose (the eval harness's ``--provider``/``--model``
    override) and for which silently getting `MockInvoiceLLM` instead would
    produce a *result* rather than an error: a benchmark table reporting mock
    output under a candidate model's name. `get_llm()` never raises this; its
    fail-safe fallback behaviour is unchanged.
    """


SUPPORTED_LLM_PROVIDERS = ("azure", "ollama", "mock")


def build_llm(
    provider: str,
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    reasoning_effort: str | None = None,
    api_version: str | None = None,
    allow_mock_fallback: bool = True,
):
    """Construct an LLM client for an *explicitly named* provider/model.

    This is the construction logic `get_llm()` has always had, parameterised on
    the provider/model instead of reading both off the global settings object.
    `get_llm()` now calls it with the settings-resolved values, so there is one
    construction path, not two that can drift.

    Everything the caller does not name still comes from settings — for Azure
    that is the endpoint, key and (unless overridden) API version, because a
    candidate model is a new *deployment under the same resource*, not a new
    resource (see `feature_23_ai_control_tower.md`'s candidates table). `model`
    maps to the Azure **deployment name** and to Ollama's model tag.

    `api_version` exists because it is not purely cosmetic on Azure: strict
    structured-output compliance is only guaranteed from GPT-4o/4o-mini onward
    **and** API version `2024-08-01-preview`+, so comparing GPT-4o against the
    baseline can legitimately need a different version for that run only.
    """
    setting = get_settings()
    provider = (provider or "mock").lower()

    if provider == "mock":
        return MockInvoiceLLM(max_tokens=max_tokens)
    elif provider == "ollama":
        model_name = model or setting.OLLAMA_MODEL
        print(f"[LLM] initialising local Ollama: {model_name} using {setting.OLLAMA_BASE_URL}")
        kwargs = {
            "base_url": setting.OLLAMA_BASE_URL,
            "model": model_name,
        }
        if max_tokens is not None:
            kwargs["num_predict"] = max_tokens
        return ChatOllama(**kwargs)
    elif provider == "azure":
        deployment = model or setting.AZURE_OPENAI_DEPLOYMENT_NAME
        # Fail-safe fallback to MockInvoiceLLM if Azure credentials or network are unavailable in local dev
        if not setting.AZURE_OPENAI_API_KEY or "your_" in setting.AZURE_OPENAI_API_KEY:
            if not allow_mock_fallback:
                raise LlmConfigurationError(
                    f"Azure OpenAI requested (deployment {deployment!r}) but AZURE_OPENAI_API_KEY "
                    "is not configured; refusing to fall back to MockInvoiceLLM."
                )
            print("[LLM] Azure OpenAI key not configured; using local MockInvoiceLLM.")
            return MockInvoiceLLM(max_tokens=max_tokens)
        try:
            print(f"[LLM] initialising Azure OpenAI: {deployment} on {setting.AZURE_OPENAI_ENDPOINT}")
            kwargs = {
                "azure_endpoint": setting.AZURE_OPENAI_ENDPOINT,
                "api_key": setting.AZURE_OPENAI_API_KEY,
                "api_version": api_version or setting.AZURE_OPENAI_API_VERSION,
                "azure_deployment": deployment,
            }
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            # Feature 6.1 A1. Only passed when a caller actually asked for it:
            # sending `reasoning_effort` to a non-reasoning deployment is an error,
            # and every existing caller omits it, so omission has to stay the
            # default. langchain-openai maps `max_tokens` to
            # `max_completion_tokens` for reasoning deployments itself.
            if reasoning_effort:
                # Gap 465: the registry knows whether this deployment accepts the
                # knob. A non-reasoning deployment (gpt-4o) rejects the parameter
                # outright, so drop it with a warning rather than kill the call.
                from utils.model_registry import catalog_entry_for
                if catalog_entry_for(deployment).reasoning_capable:
                    kwargs["reasoning_effort"] = reasoning_effort
                else:
                    logger.warning(
                        "reasoning_effort=%r requested for deployment %r, which the model "
                        "registry marks non-reasoning; parameter dropped.",
                        reasoning_effort, deployment,
                    )
            # Feature 6.1 A3: with streaming, Azure only reports token usage if
            # asked to put it on the final chunk. Without this, every streamed
            # call would log tokens_in=0 and B1's cached/reasoning counts would
            # go dark on exactly the calls A1/A2/A4 are measured by. Harmless
            # for `.invoke()`.
            kwargs["stream_usage"] = True
            return AzureChatOpenAI(**kwargs)
        except Exception as e:
            if not allow_mock_fallback:
                raise LlmConfigurationError(
                    f"Could not initialize Azure OpenAI deployment {deployment!r}: {e}"
                ) from e
            logger.warning("Could not initialize Azure OpenAI (%s); falling back to MockInvoiceLLM", e)
            return MockInvoiceLLM(max_tokens=max_tokens)

    if not allow_mock_fallback:
        raise LlmConfigurationError(
            f"Unknown LLM provider {provider!r}; expected one of {', '.join(SUPPORTED_LLM_PROVIDERS)}."
        )
    return MockInvoiceLLM(max_tokens=max_tokens)


def get_llm(max_tokens: int | None = None):
    """
    Get the LLM (Mock, Azure, or Ollama) based on configuration.

    The application's single, config-driven entry point: provider from
    `LLM_PROVIDER`, model from `AZURE_OPENAI_DEPLOYMENT_NAME`/`OLLAMA_MODEL`.
    A caller that needs a *specific* provider/model for one run (the eval
    harness's candidate-model override) calls `build_llm()` directly rather
    than mutating any of those settings.
    """
    setting = get_settings()
    provider = getattr(setting, "LLM_PROVIDER", "mock").lower()
    return build_llm(provider, max_tokens=max_tokens)


def get_llm_for_role(role: str, max_tokens: int | None = None):
    """Gap 465: build the LLM for a registry role -- `primary`, `fast`, `judge`.

    Resolves the deployment through `utils/model_registry.resolve_model`, so a
    role whose deployment setting is blank gets the primary, exactly as
    `_fast_llm()` in `agents/query_agent.py` has always behaved. Mock/Ollama
    providers ignore the role (one model for everything).
    """
    from utils.model_registry import resolve_model

    spec = resolve_model(role)  # type: ignore[arg-type]
    if spec.provider != "azure":
        return build_llm(spec.provider, max_tokens=max_tokens)
    return build_llm("azure", model=spec.deployment, api_version=spec.api_version, max_tokens=max_tokens)



def get_chat_summary_llm(max_tokens: int | None = None):
    """Feature 29 task 29.5 — the model that narrates a FULL-RECORD chat turn.

    Spec §11 decision 2 (founder, 2026-09-06) split the chat summary model by
    route: **gpt-5-mini narrates the full-record route, Luna narrates the
    attachment branches.** The split is measured, not stylistic — on the 36-case
    golden set with full records in the prompt, gpt-5-mini went 22.2% → 52.8%
    while Luna went 27.8% → 37.1% (spec §2.3), and on the 16-turn attachment
    probe Luna scored 16/16 (§2.4 re-run).

    Resolution order is `AZURE_OPENAI_CHAT_SUMMARY_DEPLOYMENT_NAME` → the judge
    deployment → the primary. The judge rung is deliberate: every environment
    already sets the judge to gpt-5-mini, so an environment that has never heard
    of the new variable still behaves the way decision 2 requires.

    Fail-soft like `_fast_llm()`: any construction failure falls back to
    `get_llm()`, because a narration call that raises is a dead chat turn.
    """
    try:
        return get_llm_for_role("chat_summary", max_tokens=max_tokens)
    except Exception:  # pragma: no cover - never fail a turn over a deployment name
        logger.warning(
            "Could not build the chat-summary deployment; falling back to the default.",
            exc_info=True,
        )
        return get_llm(max_tokens=max_tokens)


def get_long_doc_llm(max_tokens: int | None = None):
    """Feature 29 task 29.1 — the model a LONG attached document is read on.

    Resolution order is `AZURE_OPENAI_LONG_DOC_DEPLOYMENT_NAME` → the **fast**
    deployment → the primary, so with the variable unset this returns exactly
    what `_fast_llm()` returns and the role costs nothing until it is chosen.

    The role exists because context size and context recall are different
    properties (`CatalogEntry.recall_note`): the GPT-5.6 family is 1,050,000
    tokens wide, and Luna still loses a clause in the middle of a long contract
    where Terra does not (MRCR ~41% vs 89%+). Task 29.10 decides it on
    `tests/golden_long_doc.json` by the founder's 2-point rule; until then this
    is a named seam, not a behaviour change.

    Fail-soft like `_fast_llm()`: a narration call that raises is a dead chat
    turn.
    """
    try:
        return get_llm_for_role("long_doc", max_tokens=max_tokens)
    except Exception:  # pragma: no cover - never fail a turn over a deployment name
        logger.warning(
            "Could not build the long-doc deployment; falling back to the default.",
            exc_info=True,
        )
        return get_llm(max_tokens=max_tokens)
