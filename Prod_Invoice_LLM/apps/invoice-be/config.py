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
    # Gap 4: gates the mock/test tenant fallback in dependencies.py.
    # Defaults False so an unconfigured or production deployment enforces real
    # Clerk auth. Set true ONLY for local dev and the test suite -- when true, a
    # request with no Authorization header resolves to a mock Admin context on
    # the all-zero tenant, which is a full auth bypass.
    ALLOW_MOCK_AUTH: bool = False
    DEFAULT_FREE_INVOICES_LIMIT: int = 50
    AZURE_STORAGE_CONNECTION_STRING: str = ""
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001"
    # Where oauth_callback() redirects the browser back to after a connector
    # OAuth flow completes -- Google/Salesforce hit this backend directly
    # (see GOOGLE_REDIRECT_URI), so the backend itself must send the user
    # back into the app rather than leaving them on a bare JSON response.
    # This one targets an *invoice-fe* route (/settings/connectors), so in
    # local dev it is FE's own dev server (:3001 if FE is run directly, :3000
    # only if the website's Multi-Zone proxy is fronting it). Deliberately
    # kept distinct from PUBLIC_APP_URL below -- see that comment.
    FRONTEND_URL: str = "http://localhost:3000"
    # Where routers/billing.py sends a user returning from PayU
    # (/billing/success, /billing/failed). Those two routes live in
    # *invoice-website*, not invoice-fe, because post-Multi-Zone-proxy
    # (website_features_tracker.md Gap 12) invoice-fe's ingress is
    # external: false and a browser coming back from a third party
    # physically cannot reach an invoice-fe URL -- invoice-website is the
    # only public origin. Split out from FRONTEND_URL rather than reusing
    # it so the connectors redirect (an invoice-fe route) and the billing
    # redirect (an invoice-website route) can differ in local dev, where
    # there is no proxy collapsing them onto one origin. In Azure both
    # values point at invoice-website's public FQDN.
    PUBLIC_APP_URL: str = "http://localhost:3000"
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

    # Feature 11: PayU Billing
    PAYU_MERCHANT_KEY: str = ""
    PAYU_MERCHANT_SALT: str = ""
    PAYU_MODE: str = "test"  # "test" or "live"
    # The public origin PayU POSTs surl/furl back to. Despite the name this
    # is NOT invoice-be's own origin: invoice-be's ingress is internal-only
    # (external: false), so PayU -- an external third party -- can never
    # reach it directly. It is invoice-website's public origin, which now
    # carries a verbatim pass-through at the *same* path shape the backend
    # serves (app/api/v1/billing/payu/{success,failure}/route.ts), so the
    # surl/furl strings built below need no special-casing. Mirrors the
    # existing OAuth callback proxy pattern (routers/connectors.py's
    # oauth_callback() / apps/invoice-fe's /api/connectors/callback/[provider]).
    # Default is invoice-website's local dev port (3000), not invoice-be's
    # (8000), so local dev exercises the same pass-through path as Azure.
    BACKEND_PUBLIC_URL: str = "http://localhost:3000"
    # Gap 71: billing lapse enforcement. PayU's classic API has no recurring
    # object, so a paid cycle is tracked by us as a date (Tenant.paid_through)
    # and lapse is inferred from it rather than received as a webhook.
    # BILLING_CYCLE_DAYS is how far a verified payment pushes that date
    # forward; 30 rather than a real calendar month because the prices in
    # routers/billing.py::PLAN_AMOUNTS are flat monthly figures with no
    # proration, so a fixed period is both simpler and never shorter than
    # what was paid for. BILLING_GRACE_PERIOD_DAYS is how long past that date
    # a tenant keeps access before being demoted to 'unpaid' -- deliberately
    # non-zero so a payment that lands a few hours late (or a sweep that runs
    # late) doesn't lock out a paying customer.
    BILLING_CYCLE_DAYS: int = 30
    BILLING_GRACE_PERIOD_DAYS: int = 3
    # FE Gap 81: stuck-invoice reconciliation. An invoice still in a
    # non-terminal status this long after its last enqueue is treated as
    # stalled and re-enqueued. 15 minutes is comfortably above a normal
    # end-to-end run (OCR + up to two LLM extraction passes, observed ~20-60s)
    # including the retry loops in extraction_agent/_run_ocr, so a merely slow
    # invoice is never re-queued underneath a worker that is still working on
    # it. After MAX_REPROCESS_ATTEMPTS re-queues it is marked FAILED instead,
    # so a file the worker genuinely cannot process can't loop forever.
    INVOICE_STUCK_AFTER_MINUTES: int = 15
    INVOICE_MAX_REPROCESS_ATTEMPTS: int = 2

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()