"""Postgres engine fixture for the extraction-audit gap tests (BE Gaps 670-680).

CONVENTIONS hard rule 2: a persistence claim needs a run against real Postgres. The
guard is the one `tests/test_audit.py` uses (BE Gap 525): the URL must be on
localhost AND name a throwaway database containing "test", because every test drops
all tables afterwards. Without `TEST_DATABASE_URL` the tests marked `pg_only` are
skipped with that reason -- they never silently fall back to SQLite.

Not collected by pytest (the file name does not match `test_*.py`); import from it.
"""
import os
from urllib.parse import urlparse

import pytest
from sqlalchemy import text
from sqlmodel import SQLModel, create_engine

PG_URL = os.getenv("TEST_DATABASE_URL")

pg_only = pytest.mark.skipif(not PG_URL, reason="needs TEST_DATABASE_URL (Postgres) -- CONVENTIONS hard rule 2")


def make_pg_engine():
    parsed = urlparse(PG_URL)
    assert parsed.hostname in ("localhost", "127.0.0.1"), (
        "Gap 525 guard: TEST_DATABASE_URL must point to localhost or 127.0.0.1."
    )
    assert "test" in (parsed.path or "").lower(), (
        "Gap 525 guard: TEST_DATABASE_URL must name a throwaway database whose name contains 'test'."
    )
    return create_engine(PG_URL)


def _clean_database(engine):
    try:
        with engine.connect() as conn:
            conn.execute(text("DROP VIEW IF EXISTS v_vendor_spend, v_overdue, v_tax_summary, v_3way_match CASCADE;"))
            conn.commit()
    except Exception:
        pass
    SQLModel.metadata.drop_all(engine)


@pytest.fixture
def pg_engine():
    engine = make_pg_engine()
    _clean_database(engine)
    SQLModel.metadata.create_all(engine)
    yield engine
    _clean_database(engine)
    engine.dispose()

