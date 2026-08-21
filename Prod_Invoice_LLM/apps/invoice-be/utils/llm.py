import re
import logging
from langchain_openai import AzureChatOpenAI
from langchain_ollama import ChatOllama
from config import get_settings

logger = logging.getLogger(__name__)


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


def get_llm(max_tokens: int | None = None):
    """
    Get the LLM (Mock, Azure, or Ollama) based on configuration.
    """
    setting = get_settings()
    provider = getattr(setting, "LLM_PROVIDER", "mock").lower()

    if provider == "mock":
        return MockInvoiceLLM(max_tokens=max_tokens)
    elif provider == "ollama":
        print(f"[LLM] initialising local Ollama: {setting.OLLAMA_MODEL} using {setting.OLLAMA_BASE_URL}")
        kwargs = {
            "base_url": setting.OLLAMA_BASE_URL,
            "model": setting.OLLAMA_MODEL,
        }
        if max_tokens is not None:
            kwargs["num_predict"] = max_tokens
        return ChatOllama(**kwargs)
    elif provider == "azure":
        # Fail-safe fallback to MockInvoiceLLM if Azure credentials or network are unavailable in local dev
        if not setting.AZURE_OPENAI_API_KEY or "your_" in setting.AZURE_OPENAI_API_KEY:
            print("[LLM] Azure OpenAI key not configured; using local MockInvoiceLLM.")
            return MockInvoiceLLM(max_tokens=max_tokens)
        try:
            print(f"[LLM] initialising Azure OpenAI: {setting.AZURE_OPENAI_DEPLOYMENT_NAME} on {setting.AZURE_OPENAI_ENDPOINT}")
            kwargs = {
                "azure_endpoint": setting.AZURE_OPENAI_ENDPOINT,
                "api_key": setting.AZURE_OPENAI_API_KEY,
                "api_version": setting.AZURE_OPENAI_API_VERSION,
                "azure_deployment": setting.AZURE_OPENAI_DEPLOYMENT_NAME,
            }
            if max_tokens is not None:
                kwargs["max_tokens"] = max_tokens
            return AzureChatOpenAI(**kwargs)
        except Exception as e:
            logger.warning("Could not initialize Azure OpenAI (%s); falling back to MockInvoiceLLM", e)
            return MockInvoiceLLM(max_tokens=max_tokens)
    
    return MockInvoiceLLM(max_tokens=max_tokens)

