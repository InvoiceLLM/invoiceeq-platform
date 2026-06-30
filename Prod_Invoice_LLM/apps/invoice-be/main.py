# pyrefly: ignore [missing-import]
from fastapi import FastAPI
from config import get_settings
from routers import auth

app = FastAPI(title="Invoice AI", version="1.0")
settings = get_settings()

app.include_router(auth.router)

@app.get("/")
def read_root():
    return {"message": "Welcome to the Invoice AI API!"}

@app.get("/health")
async def health():
    return {"status": "ok"}
