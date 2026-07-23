from sqlmodel import create_engine, Session
from config import settings

# Configure connection arguments if using SQLite (useful for testing)
connect_args = {}
pool_kwargs = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    # Gap 41/42 (Jul 2026): explicitly sized to match main_worker.py's
    # MAX_WORKERS=10 concurrent threads per queue-worker replica (previously
    # relied on SQLAlchemy's untuned defaults, pool_size=5/max_overflow=10).
    # 20 max connections/replica x up to 10 replicas = 200 potential,
    # comfortably under Postgres's live max_connections=429 (confirmed Jul
    # 23, 2026 - psql-invoice-llm-dev, Standard_B2s), leaving headroom for
    # the backend API's own pool and future replica-count growth.
    pool_kwargs = {"pool_size": 10, "max_overflow": 10}

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, **pool_kwargs)

def get_session():
    with Session(engine) as session:
        yield session
