# pyrefly: ignore [missing-import]
from fastapi import FastAPI
from config import get_settings
from routers import auth, invoices, chat, audit, dashboard, connectors

app = FastAPI(title="Invoice AI", version="1.0")
settings = get_settings()

app.include_router(auth.router)
app.include_router(invoices.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(connectors.router, prefix="/api/v1")

@app.get("/")
def read_root():
    return {"message": "Welcome to the Invoice AI API!"}

@app.get("/health")
async def health():
    return {"status": "ok"}
