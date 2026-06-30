from langchain_openai import AzureChatOpenAI

from langchain_ollama import ChatOllama
from config import get_settings


def get_llm(temperature:float = 0.0, max_tokens: int | None = None):
    """
    Get the LLM (Azure or Ollama) based on the configuration.
    """
    setting = get_settings()
    if setting.LLM_PROVIDER.lower() == "ollama":
        print(f"[LLM] initialising local Ollama: {setting.OLLAMA_MODEL} using {setting.OLLAMA_BASE_URL}")
        kwargs = {
            "base_url": setting.OLLAMA_BASE_URL,
            "model": setting.OLLAMA_MODEL,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["num_predict"] = max_tokens
        return ChatOllama(**kwargs)
    elif setting.LLM_PROVIDER.lower() == "azure":
        print(f"[LLM] initialising Azure OpenAI: {setting.AZURE_OPENAI_DEPLOYMENT_NAME} on {setting.AZURE_OPENAI_ENDPOINT}")
        kwargs = {
            "azure_endpoint": setting.AZURE_OPENAI_ENDPOINT,
            "api_key": setting.AZURE_OPENAI_API_KEY,
            "api_version": setting.AZURE_OPENAI_API_VERSION,
            "temperature": temperature,
            "azure_deployment": setting.AZURE_OPENAI_DEPLOYMENT_NAME,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return AzureChatOpenAI(**kwargs)

