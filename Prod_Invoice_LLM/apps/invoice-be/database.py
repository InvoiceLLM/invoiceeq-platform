from sqlmodel import create_engine, Session
from config import settings

# Configure connection arguments if using SQLite (useful for testing)
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)

def get_session():
    with Session(engine) as session:
        yield session
