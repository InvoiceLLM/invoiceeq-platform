"""Model registry — the one place the application knows *what* a model is.

Gap 465 (2026-09-05). Before this module, model knowledge was scattered:
`config.py` held the deployment name, `utils/token_management.py` held a
hand-typed context-limit table that had no `gpt-5-*` entry (so every live
extraction was judged against an 8k default and large invoices tripped
`token_limit_exceeded` for nothing), the cost workbook and the eval script each
carried their own price table, `queue_worker/handlers.py` hardcoded the
Document Intelligence model id and `chroma_client.py` the embedding model
name. Swapping one deployment meant editing six files and forgetting one.

Now:

* `MODEL_CATALOG` is the static knowledge about each model *family* — context
  window, tokenizer encoding, whether it accepts `reasoning_effort`, list
  price. Keyed by the Azure model name; an Azure *deployment* is matched to a
  catalog entry by longest-prefix match on its name (`gpt-5-mini-eu` resolves
  to `gpt-5-mini`), so renaming a deployment does not silently lose its spec.
* `ModelSpec` is one resolved model for one role: the deployment name that
  will actually be called, the API version, and the catalog knowledge above.
* `resolve_model(role)` turns a role — `primary`, `fast`, `judge` — into a
  `ModelSpec` from settings. `fast` and `judge` fall back to `primary` when
  their deployment setting is blank, exactly as `_fast_llm()` always has.
* `context_limit_for(name)` / `encoding_for(name)` / `prices_for(name)` are
  the lookups the old per-file tables become.

Everything here is pure: no network, no SDK import, safe at import time. The
catalog is deliberately a plain dict so a test can monkeypatch one entry.

Unknown models get `DEFAULT_SPEC` (128k context, `o200k_base`, no reasoning
knob, zero price) and a single warning — 128k rather than the old 8k because a
guardrail that blocks real work on a guess is worse than one that lets an
oversized prompt reach the model and fail loudly there.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Literal, Optional

logger = logging.getLogger(__name__)

Role = Literal["primary", "fast", "judge"]


@dataclass(frozen=True)
class CatalogEntry:
    """Static knowledge about one model family. Prices are USD per 1M tokens,
    list price on Azure GlobalStandard at the date noted in the catalog."""

    context_limit: int
    encoding: str
    reasoning_capable: bool
    price_in: float
    price_out: float
    # Free-text provenance so the next person knows which sheet these came from.
    note: str = ""


# Verified against `az cognitiveservices account list-models` on the dev
# account 2026-09-05 (gpt-5.6-* version 2026-07-09 offered in-region). Prices
# from the founder's 2026-09-05 brief (GPT-5.6 family) and the existing
# workbook table (gpt-5 / gpt-4o lines). Context windows: the GPT-5 family is
# 400k on Azure; GPT-4o is 128k.
MODEL_CATALOG: Dict[str, CatalogEntry] = {
    # --- GPT-6 (Azure 2026-09-03). Priced per the founder's 2026-09-05 brief; no mini
    # variant; context assumed 400k like the GPT-5 line until measured. In the catalog
    # so a matrix run against it prices correctly -- NOT a recommendation. ---
    "gpt-6-astra": CatalogEntry(400_000, "o200k_base", True, 10.00, 12.50, "founder brief 2026-09-05; agentic focus"),
    # --- GPT-5.6 family (Azure GA 2026-07-09) ---
    "gpt-5.6-luna": CatalogEntry(400_000, "o200k_base", True, 0.20, 1.20, "founder brief 2026-09-05"),
    "gpt-5.6-terra": CatalogEntry(400_000, "o200k_base", True, 2.00, 12.00, "founder brief 2026-09-05"),
    "gpt-5.6-sol": CatalogEntry(400_000, "o200k_base", True, 5.00, 30.00, "founder brief 2026-09-05; promo $4/$20 to 2026-11-30"),
    # --- GPT-5 family (2025-08-07) ---
    "gpt-5-mini": CatalogEntry(400_000, "o200k_base", True, 0.25, 2.00, "live deployment; workbook table"),
    "gpt-5-nano": CatalogEntry(400_000, "o200k_base", True, 0.05, 0.40, "Azure list 2025-08"),
    "gpt-5": CatalogEntry(400_000, "o200k_base", True, 1.25, 10.00, "workbook table"),
    # --- GPT-4o line (retiring; kept so historical events and the gpt-4o deployment still price) ---
    "gpt-4o-mini": CatalogEntry(128_000, "o200k_base", False, 0.15, 0.60, "workbook table"),
    "gpt-4o": CatalogEntry(128_000, "o200k_base", False, 2.50, 10.00, "workbook table"),
    "gpt-3.5-turbo": CatalogEntry(16_385, "cl100k_base", False, 0.50, 1.50, "legacy"),
    # --- local / test ---
    "llama3.2": CatalogEntry(128_000, "cl100k_base", False, 0.0, 0.0, "Ollama"),
    "llama3": CatalogEntry(8_000, "cl100k_base", False, 0.0, 0.0, "Ollama"),
    "mock": CatalogEntry(128_000, "cl100k_base", False, 0.0, 0.0, "MockInvoiceLLM"),
}

DEFAULT_SPEC = CatalogEntry(128_000, "o200k_base", False, 0.0, 0.0, "unknown model — default")

_warned: set[str] = set()


def _clean(name: Optional[str]) -> str:
    return (name or "").strip().lower().split("/")[-1]


def catalog_entry_for(model_or_deployment: Optional[str]) -> CatalogEntry:
    """Longest-prefix match of a deployment/model name against the catalog.

    `gpt-5-mini-2025-08-07`, `gpt-5-mini-eu` and `gpt-5-mini` all resolve to
    the `gpt-5-mini` entry; `gpt-5.6-luna` must not match `gpt-5`, which is why
    the match is on the longest key, not the first.
    """
    name = _clean(model_or_deployment)
    if not name:
        return DEFAULT_SPEC
    best: Optional[str] = None
    for key in MODEL_CATALOG:
        if name == key or name.startswith(key + "-") or name.startswith(key + ":") or name.startswith(key + "."):
            if best is None or len(key) > len(best):
                best = key
    if best is None:
        # Ollama tags like `llama3.2:latest` — try the bare tag before the colon.
        bare = name.split(":")[0]
        if bare in MODEL_CATALOG:
            best = bare
    if best is None:
        if name not in _warned:
            _warned.add(name)
            logger.warning(
                "Model %r is not in utils/model_registry.MODEL_CATALOG; using the default spec "
                "(%d context, %s). Add an entry so context limits and cost are right.",
                name, DEFAULT_SPEC.context_limit, DEFAULT_SPEC.encoding,
            )
        return DEFAULT_SPEC
    return MODEL_CATALOG[best]


def context_limit_for(model_or_deployment: Optional[str]) -> int:
    return catalog_entry_for(model_or_deployment).context_limit


def encoding_for(model_or_deployment: Optional[str]) -> str:
    return catalog_entry_for(model_or_deployment).encoding


def prices_for(model_or_deployment: Optional[str]) -> tuple[float, float]:
    e = catalog_entry_for(model_or_deployment)
    return e.price_in, e.price_out


def cost_usd(model_or_deployment: Optional[str], tokens_in: int, tokens_out: int) -> float:
    pin, pout = prices_for(model_or_deployment)
    return (int(tokens_in or 0) * pin + int(tokens_out or 0) * pout) / 1_000_000


@dataclass(frozen=True)
class ModelSpec:
    """One resolved model for one role."""

    role: str
    provider: str          # azure | ollama | mock
    deployment: str        # Azure deployment name, Ollama tag, or "mock"
    api_version: str       # Azure only; "" otherwise
    context_limit: int
    encoding: str
    reasoning_capable: bool
    price_in: float
    price_out: float

    @property
    def is_azure(self) -> bool:
        return self.provider == "azure"


def resolve_model(role: Role = "primary", settings=None) -> ModelSpec:
    """Resolve a role to the model that will be called, from settings.

    `fast` → `AZURE_OPENAI_FAST_DEPLOYMENT_NAME`, `judge` →
    `AZURE_OPENAI_JUDGE_DEPLOYMENT_NAME`; either blank means "same as primary",
    which keeps an unset environment bit-identical to before those settings
    existed. Non-Azure providers have one model for every role.
    """
    if settings is None:
        from config import get_settings
        settings = get_settings()

    provider = (getattr(settings, "LLM_PROVIDER", "mock") or "mock").strip().lower()
    if provider == "ollama":
        deployment = settings.OLLAMA_MODEL
        api_version = ""
    elif provider == "azure":
        primary = settings.AZURE_OPENAI_DEPLOYMENT_NAME
        if role == "fast":
            deployment = (getattr(settings, "AZURE_OPENAI_FAST_DEPLOYMENT_NAME", "") or "").strip() or primary
        elif role == "judge":
            deployment = (getattr(settings, "AZURE_OPENAI_JUDGE_DEPLOYMENT_NAME", "") or "").strip() or primary
        else:
            deployment = primary
        api_version = settings.AZURE_OPENAI_API_VERSION
    else:
        provider = "mock"
        deployment = "mock"
        api_version = ""

    entry = catalog_entry_for(deployment)
    return ModelSpec(
        role=role,
        provider=provider,
        deployment=deployment,
        api_version=api_version,
        context_limit=entry.context_limit,
        encoding=entry.encoding,
        reasoning_capable=entry.reasoning_capable,
        price_in=entry.price_in,
        price_out=entry.price_out,
    )


def registry_snapshot(settings=None) -> dict:
    """Everything a health endpoint, a benchmark artifact or a log line should
    say about the models in force. JSON-safe."""
    out = {role: resolve_model(role, settings).__dict__ for role in ("primary", "fast", "judge")}
    if settings is None:
        from config import get_settings
        settings = get_settings()
    out["doc_intel_model_id"] = getattr(settings, "DOC_INTEL_MODEL_ID", "")
    out["embedding_model"] = getattr(settings, "EMBEDDING_MODEL_NAME", "")
    return out
