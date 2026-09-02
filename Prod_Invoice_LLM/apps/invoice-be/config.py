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
    # Gap 280: gates the Redis-backed async chat queue in routers/chat.py.
    # Defaults False so POST /message keeps its long-standing synchronous
    # behaviour for every tenant until this is verified live -- as merged,
    # the branch made async the unconditional default with the old behaviour
    # reachable only via an undiscoverable ?sync=true escape hatch, which is
    # a real production-behaviour change to chat with no rollout gate.
    #
    # Gap 365: "once it has real live evidence" was the whole problem -- a gate
    # with no stated bar is a gate nobody can ever satisfy, so the flag sat False
    # over a fully built queue/worker/SSE path. These are the five criteria.
    # ALL FIVE must pass, on ONE run against real Postgres and a real Redis
    # (hard rule 2 -- a SQLite/fakeredis run is not evidence), and passing them
    # flips this in DEV only. Production stays False until a 24h dev soak ends
    # with every `chat_inflight:{tenant}` counter back at zero.
    #   1. LIVE PROGRESS. An SSE transcript from one real turn on
    #      GET /chat/jobs/{id}/stream shows >= 6 DISTINCT `step` values, and a
    #      turn whose SQL needed repair shows each attempt separately. Before
    #      Gap 365 the worker published exactly 2 hardcoded steps.
    #   2. CONCURRENCY CEILING. The 4th simultaneous job for one tenant is
    #      rejected with HTTP 429 + Retry-After while the 3 in flight all
    #      complete. (Enforcement is Gap 364/Track A's
    #      `services/chat_queue.py::enqueue_chat_job` -- cite that run, do not
    #      re-derive it here.)
    #   3. FOLLOW-UP CORRECTNESS UNDER LOAD. A narrowing follow-up sent while
    #      earlier turns are in flight still routes to SQL -- i.e. Gap 237's
    #      deterministic override still sees the previous turn's `generated_sql`.
    #      This is what Gap 365's per-session Redis lock
    #      (`queue_worker/handlers.py::chat_session_lock`) exists to guarantee.
    #   4. NO SLOT LEAK ON FAILURE. A job that FAILS releases its slot:
    #      `chat_inflight:{tenant}` returns to 0 after `fail_job`, not just
    #      after `complete_job`.
    #   5. REDIS-DOWN FALLBACK. With Redis unreachable,
    #      POST /chat/sessions/{id}/message still answers via the synchronous
    #      path and returns no 5xx.
    # Deliberately left False by the change that wrote these criteria: stating
    # the bar and clearing it are two different jobs, and the second one belongs
    # to whoever holds the verification evidence.
    ENABLE_ASYNC_CHAT_QUEUE: bool = False
    # Gap 117: which deployment this process is. Read only by ops scripts that
    # must never touch production data (scripts/grant_test_plan.py), never by
    # request-handling code -- nothing about the product's behaviour should
    # branch on it. Defaults to "production" deliberately, the same fail-closed
    # choice as ALLOW_MOCK_AUTH above: an environment that forgot to declare
    # itself is treated as the one where a destructive script must refuse to
    # run, so the unsafe state is the one you have to opt into explicitly.
    ENVIRONMENT: str = "production"
    DEFAULT_FREE_INVOICES_LIMIT: int = 50
    # Gap 118: how often DEFAULT_FREE_INVOICES_LIMIT refills. The free tier was
    # always described as a monthly allowance but was implemented as a
    # decrement-only lifetime counter, so a free tenant was permanently capped
    # at 50 invoices ever. Deliberately its own knob rather than reusing
    # BILLING_CYCLE_DAYS: that value is "how much time one PayU payment buys",
    # and if a future annual plan pushed it to 365 the free tier would silently
    # become 50 invoices per *year*. Same default (30) today, different meaning.
    FREE_QUOTA_CYCLE_DAYS: int = 30

    # --- Feature 25 (Gap 340): sandbox `inv_test_` keys ---------------------
    #
    # A sandbox key is issued to an ANONYMOUS website visitor with no login, and
    # resolves to a fresh real Tenant row. Every value below is a containment
    # knob, so each has a deliberately conservative default rather than an
    # "unlimited" one -- the whole surface is unauthenticated.
    #
    # Master switch. Default False: a deployment that has not thought about the
    # abuse surface must not be handing out credentials to strangers. Same
    # fail-closed reasoning as ALLOW_MOCK_AUTH above.
    SANDBOX_KEYS_ENABLED: bool = False
    # How long a sandbox key lives. Expiry is enforced live in
    # dependencies.resolve_api_key_context() (the key stops verifying) AND swept
    # by scripts/sweep_sandbox_tenants.py, which deletes the tenant outright --
    # a flag nobody reads is not a TTL.
    SANDBOX_KEY_TTL_HOURS: int = 72
    # Hard ceiling on UNCLAIMED sandbox tenants platform-wide. Issuance past this
    # fails closed with a "temporarily unavailable" 503 rather than creating
    # tenant rows without bound. Counted under an advisory lock at issuance time.
    SANDBOX_MAX_UNCLAIMED_TENANTS: int = 500
    # Per-IP sliding window for issuance, enforced through the SAME limiter the
    # public contact form uses (routers/support.py::_ContactRateLimiter) -- it
    # already solves the which-IP-header-do-we-trust problem for this platform.
    SANDBOX_ISSUE_RATE_LIMIT: int = 3
    SANDBOX_ISSUE_RATE_WINDOW_SECONDS: int = 3600
    # Gap 340 requirement 7: services/billing_quota.py's free-tier charge covers
    # INGESTION only, so without this a sandbox key is an unmetered path to real
    # Azure OpenAI spend. A plain bounded counter on the sandbox row, not a
    # second quota system.
    SANDBOX_CHAT_MESSAGE_LIMIT: int = 25
    # How many invoices a sandbox workspace may ingest. Kept separate from
    # DEFAULT_FREE_INVOICES_LIMIT so tightening the sandbox does not tighten the
    # free tier a paying-adjacent customer is on.
    SANDBOX_INVOICE_LIMIT: int = 5

    AZURE_STORAGE_CONNECTION_STRING: str = ""
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001"
    # Where oauth_callback() redirects the browser back to after a connector
    # OAuth flow completes -- Google hits this backend directly
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
    # Gap 288-series follow-up (2026-08-23): was "llama3:8b" -- the original
    # Llama 3, released before Ollama/LangChain tool-calling support existed.
    # `.with_structured_output()` needs Llama 3.1+ to be reliable. Using
    # llama3.2:latest specifically because it's already pulled on this
    # machine (`ollama list`) -- no new multi-GB download needed, and 3.2 is
    # a later generation than 3.1 with the same tool-calling support carried
    # forward.
    OLLAMA_MODEL: str = "llama3.2:latest"

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
    # Salesforce (SALESFORCE_CLIENT_ID/SECRET/REDIRECT_URI) removed 2026-08-28,
    # Gap 334. The corresponding infra wiring (Key Vault secret, Container App
    # env vars, params files) is deliberately left in place -- separately
    # scoped, and an unused env var is harmless where a deleted Key Vault
    # secret is not trivially reversible.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""

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
    # Feature 14: one platform-wide mailbox (not per-tenant).
    # Tenant + direction are resolved from the sender's registered set.
    EMAIL_APP_DOMAIN: str = "invoiceeq.app"
    EMAIL_APP_ADDRESS: str = "invoices@invoiceeq.app"
    # Gap 125: SendGrid Mail Send. Works with Single Sender Verification for
    # tests (no GoDaddy domain auth required); domain auth improves deliverability.
    SENDGRID_API_KEY: str = ""
    SENDGRID_SENDING_DOMAIN: str = ""
    # Outbound sender address & display name. SENDGRID_FROM_EMAIL takes priority
    # over EMAIL_APP_ADDRESS in outbound_email.py::from_address() so the
    # inbound mailbox (AI receive) and outbound sender (customer notifications)
    # are cleanly separated. Injected from bicep params sendgridFromEmail /
    # sendgridFromName -- must be declared here or Pydantic extra='ignore'
    # silently drops the Container App env vars.
    SENDGRID_FROM_EMAIL: str = ""
    SENDGRID_FROM_NAME: str = "InvoiceLLM"
    # Gap 124 item 5: the shared secret POST /email/mailintegration requires.
    # The name matches the container env var already wired in
    # infra/modules/compute/invoice-be.bicep, which maps it to the Key Vault
    # secret SENDGRID-INBOUND-SECRET -- that secret was provisioned but nothing
    # in the application ever read it, so the webhook was open to anyone who
    # could reach the website relay.
    #
    # SendGrid Inbound Parse lets you configure a Destination URL and nothing
    # else -- no signing key, no signature header -- so the only place the
    # secret can travel is the URL itself. Accepted, in order: an
    # `X-Inbound-Secret` header, a `key`/`secret` query parameter, or the
    # password half of HTTP Basic credentials embedded in the URL. See
    # services/inbound_mail_security.py::presented_inbound_secret.
    #
    # Fail-closed, deliberately, the same choice as ALLOW_MOCK_AUTH above: an
    # empty value does NOT mean "enforcement off", it means every inbound mail
    # POST is rejected, because an empty shared secret cannot authenticate
    # anything. A deployment that has not seeded the Key Vault secret yet is
    # exactly the deployment that must not accept unauthenticated mail. The
    # rejection is recorded (reason `secret_unconfigured`) and visible in the
    # Admin console, so the misconfiguration surfaces instead of silently
    # eating mail.
    INBOUND_PARSE_SHARED_SECRET: str = ""
    # Gap 124 item 7: hard ceiling on a single inbound mail POST, attachments
    # included. 25 MiB matches SendGrid's own documented Inbound Parse limit --
    # anything larger than this was never going to be a legitimate parse POST.
    INBOUND_EMAIL_MAX_BYTES: int = 26_214_400

    # Feature 19 / Feature Website 5: Support Ticket & Inquiry Engine
    # Destination inbox for all support alert emails (contact form submissions,
    # chatbot escalations, and direct app tickets). Defaults to the platform's
    # primary support address; override via env var in Key Vault for alternate
    # environments. NEVER set to empty — that would silently swallow every ticket.
    SUPPORT_NOTIFY_EMAIL: str = "sbanerji@admsofttech.com"

    # Gap 249: the Front Door profile's `frontDoorId` GUID, used only to decide
    # whether the `X-Azure-ClientIP` header on an inbound request can be
    # trusted for rate-limiting (see routers/support.py::_get_client_ip).
    #
    # Empty by default, and empty is the correct value today: Front Door is
    # gated on `customDomainName` in infra/08-apps.bicep, that param is unset,
    # and nothing has been deployed -- so no request currently arrives with a
    # genuine X-Azure-* header. Leaving this empty means those headers are
    # ignored outright, which is the safe state: if we trusted X-Azure-ClientIP
    # unconditionally, any caller could forge it and reset their own limit
    # window, which is the exact bypass this setting exists to prevent.
    #
    # Set it (to the real profile GUID, not a placeholder) only in the same
    # change that actually puts Front Door in front of this app. An inbound
    # X-Azure-FDID is only honoured when it matches this value exactly.
    FRONT_DOOR_ID: str = ""

    # Feature 23 / Gap 304 half (2): score every real production chat turn with
    # the same reference-free judge the golden bank uses
    # (`services/online_quality_judge.py`), writing an `agent_eval_run` row
    # tagged `run_source=production`.
    #
    # This is an on/off switch, not a sampling control -- when it is on, every
    # turn is judged. Default False for the same fail-closed reason as the two
    # flags above, plus one this file has not had before: turning it on adds
    # **two billable LLM calls to every chat turn** (the combined soft judge and
    # the persona judge). That is a real per-tenant cost change, so it is opted
    # into per environment rather than arriving switched on with a merge.
    #
    # Off is inert by construction: the judge is submitted, not called, and the
    # submit helper checks this flag before it hands anything to a thread, so
    # with the flag off nothing extra runs on the turn at all.
    ENABLE_PRODUCTION_QUALITY_JUDGE: bool = False

    # Feature 20 Area 1 (`services/azure_cost.py`): what resource group's real
    # Azure spend to read from the Cost Management API, and how to authenticate.
    #
    # Both of the first two must be set for any cost call to happen at all --
    # `cost_scope()` raises rather than guessing, because a wrong scope returns a
    # perfectly valid-looking response for somebody else's spend. The live dev
    # values are subscription `2ae37d8b-...` / `rg-invoice-llm-dev`; they are not
    # defaulted here because this file is shared with local and prod processes.
    AZURE_SUBSCRIPTION_ID: str = ""
    AZURE_COST_RESOURCE_GROUP: str = ""
    # Empty means "the live budget name", `budget-invoicellm-dev` -- see
    # `services/azure_cost.py::resolve_budget_name()` for why that is hardcoded
    # as the default rather than derived from a naming prefix.
    AZURE_COST_BUDGET_NAME: str = ""
    # An explicitly supplied ARM bearer token. For one-off local checks and for
    # the test suite; never set on a container.
    AZURE_COST_ACCESS_TOKEN: str = ""
    # Allow falling back to `az account get-access-token` when no managed
    # identity is present. Default False, same fail-closed reasoning as
    # ALLOW_MOCK_AUTH: a deployment that lost its managed identity should raise
    # a clear auth error, not silently run as whoever last ran `az login`.
    AZURE_COST_CLI_FALLBACK: bool = False

    # Feature 23 benchmark artifacts (`services/benchmark_artifacts.py`). Where
    # the two tracks' full raw JSON output is kept, so a workbook panel's
    # `extraction_benchmark_run` / `agent_eval_summary` event can be followed
    # back to the per-case (Track 1) / per-turn (Track 2) detail behind it.
    #
    # A separate container from `invoices`, not a prefix inside it: that one
    # holds tenant PDFs, is the target of `delete_pdf_from_storage()`, and would
    # end up under whatever retention/lifecycle policy tenant data eventually
    # gets. Benchmark output is neither tenant data nor subject to that.
    BENCHMARK_ARTIFACT_CONTAINER: str = "benchmark-artifacts"
    # Only consulted when AZURE_STORAGE_CONNECTION_STRING is unset/placeholder --
    # the managed-identity path, which needs the account name because there is no
    # connection string to read it out of. `id-invoicellm-dev` already holds
    # `Storage Blob Data Contributor` on `stinvoicellmdev2` (verified live
    # 2026-08-24), so that path needs no new role assignment.
    AZURE_STORAGE_ACCOUNT: str = ""
    # Off switch for the upload half of the mirror. The telemetry event is still
    # emitted -- it carries no `artifact_blob` and the workbook panel simply has
    # no link to follow. For a local run that should not touch Azure at all.
    BENCHMARK_ARTIFACT_UPLOAD: bool = True

    # Feature 24 (Ops Digest Agent) declared seven OPS_DIGEST_* settings here.
    # The feature was superseded as over-scoped and deleted 2026-08-25 (Gap 311);
    # `extra="ignore"` below means a stale OPS_DIGEST_* line left in someone's
    # local `.env` is silently dropped rather than raising at startup.

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

@lru_cache()
def get_settings() -> Settings:
    return Settings()

settings = get_settings()

# Gap 359: ALLOW_MOCK_AUTH is a full authentication bypass (Gap 4's docstring
# above). It defaults False and is confirmed off in every real deployment
# today, but nothing previously stopped a future deployment from setting it
# true by accident -- there was no startup check tying it to a non-production
# environment, only the default itself. This mirrors NON_PRODUCTION_ENVIRONMENTS
# in scripts/grant_test_plan.py (same set, same fail-closed reasoning) rather
# than importing it from there -- that module is a standalone ops script, not
# meant to be imported into the running app.
NON_PRODUCTION_ENVIRONMENTS = {"dev", "development", "local", "test", "testing", "qa", "staging"}


def _enforce_mock_auth_not_in_production(s: Settings) -> None:
    """Raises if `s` describes a full auth bypass outside a non-production
    environment. A plain function, not an inline `if`, so a test can call it
    directly against a constructed `Settings` without reloading this module."""
    if s.ALLOW_MOCK_AUTH and s.ENVIRONMENT not in NON_PRODUCTION_ENVIRONMENTS:
        raise RuntimeError(
            "ALLOW_MOCK_AUTH=true is a full authentication bypass and is refused "
            "outside a recognized non-production ENVIRONMENT "
            f"({', '.join(sorted(NON_PRODUCTION_ENVIRONMENTS))}); "
            f"got ENVIRONMENT={s.ENVIRONMENT!r}. Set ALLOW_MOCK_AUTH=false, "
            "or set ENVIRONMENT to a recognized non-production value."
        )


# Runs at import time, not inside main.py's lifespan hook, so a misconfigured
# process fails before it ever binds a port rather than merely failing its
# readiness probe -- the strongest fail-closed point available.
_enforce_mock_auth_not_in_production(settings)