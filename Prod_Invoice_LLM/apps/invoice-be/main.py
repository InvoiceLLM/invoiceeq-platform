# pyrefly: ignore [missing-import]
import threading
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from config import get_settings
from routers import auth, invoices, chat, audit, dashboard, connectors, trainer

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the Azure Queue worker in a background daemon thread on startup."""
    try:
        from queue_worker.main_worker import poll_queue
        worker_thread = threading.Thread(target=poll_queue, daemon=True, name="queue-worker")
        worker_thread.start()
        logger.info("Queue worker thread started.")
    except Exception as e:
        logger.error("Failed to start queue worker: %s", e)
    yield

app = FastAPI(title="Invoice AI", version="1.0", lifespan=lifespan)

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

@app.get("/")
def read_root():
    return {"message": "Welcome to the Invoice AI API!"}

@app.get("/health")
async def health():
    return {"status": "ok"}
