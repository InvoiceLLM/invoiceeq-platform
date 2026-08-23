# pyrefly: ignore [missing-import]
import os
import logging
import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, text
from database import engine
from config import get_settings
from routers import auth, invoices, chat, audit, dashboard, connectors, trainer, email_ingestion, outbound_invoices, outbound_audit, outbound_dashboard, webhooks, billing, admin, webhook_docs, autopilot, support
from routers import settings as settings_router
from utils.logging_config import TracingAndLoggingMiddleware, setup_structured_logging

logger = logging.getLogger(__name__)

# Feature 19 (Task 19.3): Initialize structured JSON logging
setup_structured_logging(service_name="invoice-be")

# Feature 19 (Task 19.2): OpenTelemetry auto-instrumentation for Azure Monitor Application Insights
appinsights_conn_str = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
azure_monitor_configured = False
if appinsights_conn_str:
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        configure_azure_monitor(
            connection_string=appinsights_conn_str,
            logger_name="invoice_be_telemetry"
        )
        azure_monitor_configured = True
        logger.info("Azure Monitor OpenTelemetry successfully configured.")
    except Exception as e:
        logger.warning(f"Could not configure Azure Monitor OpenTelemetry: {e}")

def _start_rag_warmup() -> threading.Thread | None:
    """
    Gap 278: kick off `chroma_client.warm_rag_dependencies()` at process start.

    Deliberately a **daemon thread, not an awaited startup step.** The work it
    does (connect to Chroma, load `BAAI/bge-m3`, which makes live round-trips to
    huggingface.co on a cold layer cache) has no useful upper bound, while the
    Container App startup probe budget is 65s total (`initialDelaySeconds: 5` +
    `periodSeconds: 5` x `failureThreshold: 12`, see
    infra/modules/compute/invoice-be.bicep). Blocking the ASGI startup on it
    would risk turning a slow warm-up into a probe failure and a restart loop --
    i.e. trading an intermittently slow first chat turn for an outage.

    Running it concurrently is still the whole fix: in the normal case the
    warm-up finishes long before the first user request, and in the worst case
    a request that arrives mid-warm-up simply waits on the same singleton it
    would have had to build itself anyway (`_chroma_lock` / `_embedding_lock`),
    so it is never slower than the pre-fix behaviour.

    Set `DISABLE_RAG_WARMUP=true` to skip it (local runs that never touch chat,
    or a process deliberately kept off Chroma).
    """
    if os.getenv("DISABLE_RAG_WARMUP", "").strip().lower() in {"1", "true", "yes"}:
        logger.info("RAG warm-up skipped (DISABLE_RAG_WARMUP set).")
        return None

    def _warm():
        try:
            # Imported here, not at module scope, so a warm-up-only dependency
            # can never fail the app's import.
            from chroma_client import warm_rag_dependencies
            warm_rag_dependencies()
        except Exception as e:
            logger.warning(f"RAG warm-up thread failed: {e}")

    thread = threading.Thread(target=_warm, name="rag-warmup", daemon=True)
    thread.start()
    return thread


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Process-lifetime hooks. Startup work must not block readiness -- see
    `_start_rag_warmup()`."""
    _start_rag_warmup()
    yield


app = FastAPI(
    title="Invoice AI",
    version="1.0",
    lifespan=lifespan,
    # Gap 184: the Security → API Docs tab in invoice-fe renders this same
    # schema, so the description is the one place both the standalone Swagger UI
    # and the in-app Docs Hub read their "how do I authenticate" answer from.
    description=(
        "Programmatic REST API for the Invoice AI platform.\n\n"
        "**Authentication.** Browser sessions authenticate with a Clerk session JWT "
        "(`Authorization: Bearer <jwt>`). Server-to-server integrations authenticate "
        "with a tenant API key, sent as `X-API-Key: <key>` or "
        "`Authorization: Bearer <key>`; keys start with `inv_live_`, are issued and "
        "rotated from Settings → Security (`POST /api/v1/settings/security/api-key/rotate`), "
        "and are shown exactly once at rotation time. Check a key with "
        "`GET /api/v1/settings/security/api-key/verify`.\n\n"
        "**Webhooks.** The Webhooks section below documents the payloads this platform "
        "POSTs to subscriber URLs registered via `/api/v1/webhooks`."
    ),
)

settings = get_settings()

app.add_middleware(TracingAndLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Feature 20 (Gap 292): explicitly instrument THIS app object for HTTP request
# telemetry. Without this, App Insights' `AppRequests` table is empty for every
# route, at every time window -- which is exactly what was observed live on
# `ca-invoice-be-dev` despite APPLICATIONINSIGHTS_CONNECTION_STRING being
# correctly wired into the container.
#
# Root cause is a Python import-order trap, not missing config.
# `configure_azure_monitor()` above auto-instruments FastAPI by *rebinding the
# module attribute* -- `FastAPIInstrumentor._instrument()` literally does
# `fastapi.FastAPI = _InstrumentedFastAPI`. That only affects app objects
# constructed from `fastapi.FastAPI` **after** the swap. This module did
# `from fastapi import FastAPI` at line 6, which copied the *original* class
# into this module's namespace before the swap ever happened, so `app = FastAPI(...)`
# below kept building a pristine, un-instrumented app. Every other instrumentor
# the distro enables (psycopg2, requests, urllib/urllib3) patches at the call
# site rather than swapping a class, which is why dependency telemetry worked
# and only server-side request telemetry silently went missing.
#
# `instrument_app()` is the ordering-independent API: it wraps this specific
# instance's `build_middleware_stack`, so the OTel ASGI middleware ends up
# outermost regardless of when it is called relative to the import. It is
# idempotent (guards on `_is_instrumented_by_opentelemetry`), so it stays safe
# even if a future distro version starts catching this app some other way.
#
# `/health*` is excluded deliberately: ACA startup/liveness/readiness probes poll
# it every ~5s per replica, which would dominate request volume and skew the
# latency/error-rate panels this telemetry exists to feed. Probe health is
# already covered by ACA replica state and the container metric alerts. This
# mirrors the same exclusion `TracingAndLoggingMiddleware` applies to access logs.
if azure_monitor_configured:
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor.instrument_app(app, excluded_urls="/health")
        logger.info("FastAPI HTTP request instrumentation enabled (AppRequests).")
    except Exception as e:
        logger.warning(f"Could not instrument FastAPI app for request telemetry: {e}")


app.include_router(auth.router)
app.include_router(invoices.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(connectors.router, prefix="/api/v1")
app.include_router(trainer.router, prefix="/api/v1")
app.include_router(settings_router.router, prefix="/api/v1")
app.include_router(email_ingestion.router, prefix="/api/v1")
app.include_router(outbound_invoices.router, prefix="/api/v1")
app.include_router(outbound_audit.router, prefix="/api/v1")
app.include_router(outbound_dashboard.router, prefix="/api/v1")
app.include_router(webhooks.router, prefix="/api/v1")
app.include_router(billing.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(autopilot.router, prefix="/api/v1")  # Feature 13: Tenant Autopilot
app.include_router(support.router, prefix="/api/v1")   # Feature 19 / Website Feature 5: Support Tickets & Contact Inquiries

# Gap 184: documentation-only. `app.webhooks` contributes an OpenAPI 3.1
# "webhooks" section describing the events this platform SENDS -- nothing is
# mounted and no path becomes callable. FastAPI's built-in Swagger UI at /docs
# was already enabled (never disabled via docs_url=None); this is what makes the
# outbound event payloads visible there next to the inbound REST routes, which
# is the whole point of the in-app Docs Hub.
app.webhooks.routes.extend(webhook_docs.router.routes)

@app.get("/")
def read_root():
    return {"message": "Welcome to the Invoice AI API!"}

# Feature 19 (Task 19.1 & 19.2): Health Probes for Container Lifecycle & ACA Self-Healing
@app.get("/health")
def health():
    """Basic health probe endpoint for general availability and ACA Startup/Liveness probes."""
    return {"status": "ok"}

@app.get("/health/liveness")
def health_liveness():
    """Liveness probe to ensure ASGI worker process is responsive."""
    return {"status": "alive"}

@app.get("/health/readiness")
def health_readiness():
    """Readiness probe checking database connectivity and Redis availability before routing traffic."""
    checks = {}
    is_healthy = True

    # 1. PostgreSQL Database connectivity check
    try:
        with Session(engine) as session:
            session.exec(text("SELECT 1")).first()
        checks["database"] = "ok"
    except Exception as e:
        logger.error(f"Readiness probe database check failed: {e}")
        checks["database"] = f"unhealthy: {str(e)}"
        is_healthy = False

    # 2. Redis availability check (non-fatal, degrades gracefully)
    current_settings = get_settings()
    if current_settings.REDIS_URL:
        try:
            import redis
            r = redis.Redis.from_url(current_settings.REDIS_URL, decode_responses=True)
            r.ping()
            checks["redis"] = "ok"
        except Exception as e:
            logger.warning(f"Readiness probe Redis check warning: {e}")
            checks["redis"] = f"degraded: {str(e)}"
    else:
        checks["redis"] = "disabled"

    if not is_healthy:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "checks": checks}
        )

    return {"status": "ready", "checks": checks}

