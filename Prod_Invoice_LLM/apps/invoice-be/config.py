from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    CHROMA_HOST: str
    CHROMA_PORT: int
    CLERK_SECRET_KEY: str
    TOKEN_ENCRYPTION_KEY: str
    CLERK_JWT_ISSUER: str = ""
    CLERK_JWKS_URL: str = ""
    DEFAULT_FREE_INVOICES_LIMIT: int = 50
    AZURE_STORAGE_CONNECTION_STRING: str = ""
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"
    MOCK_EMBEDDINGS: bool = False


    # --- ADD THESE THREE LINES ---
    LLM_PROVIDER: str = "azure"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3:8b"

    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_API_VERSION: str = "2024-02-15-preview"
    AZURE_OPENAI_DEPLOYMENT_NAME: str = "gpt-4o-mini"  # Azure uses deployment name instead of model name
    AZURE_DOC_INTEL_ENDPOINT: str = ""
    AZURE_DOC_INTEL_KEY: str = ""
    # Optional additional Doc Intelligence resources for horizontal scale-out
    # (Gap 41/42, Jul 2026) - each S0 resource has its own independent rate
    # limit (no shared regional quota pool like Azure OpenAI has), so
    # round-robining across several is the effective scaling lever.
    # Two ways to configure (utils/doc_intel_client.py merges both):
    # (1) comma-separated AZURE_DOC_INTEL_ENDPOINTS/KEYS - convenient for
    #     local .env; (2) numbered AZURE_DOC_INTEL_ENDPOINT_2/_KEY_2,
    #     _3/_3, ... - required in Container Apps, since each Key Vault
    #     secret maps to its own env var (can't join multiple secretRefs
    #     into one comma-separated value declaratively in bicep).
    AZURE_DOC_INTEL_ENDPOINTS: str = ""
    AZURE_DOC_INTEL_KEYS: str = ""
    AZURE_DOC_INTEL_ENDPOINT_2: str = ""
    AZURE_DOC_INTEL_KEY_2: str = ""
    AZURE_DOC_INTEL_ENDPOINT_3: str = ""
    AZURE_DOC_INTEL_KEY_3: str = ""

    # OAuth Credentials
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""
    SALESFORCE_CLIENT_ID: str = ""
    SALESFORCE_CLIENT_SECRET: str = ""
    SALESFORCE_REDIRECT_URI: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()