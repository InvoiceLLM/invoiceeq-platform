from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    CHROMA_HOST: str
    CHROMA_PORT: int
    # ChromaDB's Container App ingress is HTTPS-only when reached over its
    # external hostname (needed since its internal-only ingress rejected the
    # client's plain-HTTP calls outright) -- local/dev Chroma over docker-compose
    # has no TLS, so this defaults off and is only set true for that deployment.
    CHROMA_USE_SSL: bool = False
    CLERK_SECRET_KEY: str
    TOKEN_ENCRYPTION_KEY: str
    CLERK_JWT_ISSUER: str = ""
    CLERK_JWKS_URL: str = ""
    DEFAULT_FREE_INVOICES_LIMIT: int = 50
    AZURE_STORAGE_CONNECTION_STRING: str = ""
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001"
    # Where oauth_callback() redirects the browser back to after a connector
    # OAuth flow completes -- Google/Salesforce hit this backend directly
    # (see GOOGLE_REDIRECT_URI), so the backend itself must send the user
    # back into the app rather than leaving them on a bare JSON response.
    FRONTEND_URL: str = "http://localhost:3000"
    MOCK_EMBEDDINGS: bool = False
    # Gap 12: directory watcher only accepts paths under this base dir (path-traversal
    # guard against arbitrary server filesystem reads). Empty = feature disabled.
    WATCHER_ALLOWED_BASE_DIR: str = ""


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