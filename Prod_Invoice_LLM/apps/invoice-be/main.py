# pyrefly: ignore [missing-import]
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import get_settings
from routers import auth, invoices, chat, audit, dashboard, connectors, trainer, email_ingestion
from routers import settings as settings_router

logger = logging.getLogger(__name__)

app = FastAPI(title="Invoice AI", version="1.0")

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

@app.get("/")
def read_root():
    return {"message": "Welcome to the Invoice AI API!"}

@app.get("/health")
async def health():
    return {"status": "ok"}
