# pyrefly: ignore [missing-import]
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import get_settings
from routers import auth, invoices, chat, audit, dashboard, connectors, trainer, email_ingestion, outbound_invoices, outbound_audit, outbound_dashboard, webhooks, billing, admin, webhook_docs
from routers import settings as settings_router

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Invoice AI",
    version="1.0",
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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

@app.get("/health")
async def health():
    return {"status": "ok"}
