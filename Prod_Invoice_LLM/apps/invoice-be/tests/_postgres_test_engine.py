"""BE Gap 685: one Postgres-or-SQLite engine factory for the extraction suites.

CONVENTIONS hard rule 2 -- "Postgres is the only test evidence" -- exists because
the SQLite/Postgres fidelity gap has been the root cause of 4+ incidents. SQLite
has no JSONB type or containment operators (`@>`, `->`), enforces nullability and
types differently, and diverges on UUID handling and case-sensitive matching, so
a green SQLite run is evidence about an engine the product does not use.

**BE Gap 525** fixed this for the audit suites (`tests/test_audit.py`,
`tests/test_outbound_audit.py`). **BE Gap 570** is the same port for the chat
suites. The three extraction suites -- `test_extraction.py`,
`test_extraction_quality_rollup.py`, `test_generic_extraction.py` -- had no
entry, and that absence was BE Gap 685.

This module exists so the guard has **one** definition instead of a third and
fourth copy. The guard itself is lifted verbatim from `tests/test_audit.py:15-37`
rather than redesigned: it is the only thing standing between a test run and a
dropped development database, and these fixtures call `drop_all` after every
test.

── Two caveats a reader must not miss ────────────────────────────────────────

1. **Nothing sets `TEST_DATABASE_URL` automatically.** A repo-wide grep across
   all four GitHub workflows returns zero hits. Every automated run therefore
   still takes the SQLite branch below. Porting a suite gives it the *capability*
   to run against Postgres; it does not make that happen. A "verified on
   Postgres" claim for these suites means someone exported the variable and ran
   them, and cited that run. This is equally true of the already-ported Gap 525
   and Gap 570 suites.

2. **BE Gap 642 is open and applies here.** These fixtures build the schema with
   `SQLModel.metadata.create_all`, which neither owns nor tolerates an
   Alembic-built schema: running against a database that has had
   `alembic upgrade head` applied produced `61 failed, 559 passed, 308 errors` on
   the chat suites, against `50 passed` on a virgin database. So
   `TEST_DATABASE_URL` must name an **empty, throwaway** database. The deeper
   consequence is Gap 642's, not this module's: the schema these suites test is
   the one `create_all` builds, never the one the migrations build.

Usage::

    from tests._postgres_test_engine import make_test_engine
    engine = make_test_engine()
"""

import os
from urllib.parse import urlparse

from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

__all__ = ["make_test_engine", "is_postgres_run", "SQLITE_MEMORY_URL"]

SQLITE_MEMORY_URL = "sqlite:///:memory:"


def _guarded_postgres_url() -> str | None:
    """Return a validated `TEST_DATABASE_URL`, or None to fall back to SQLite.

    The two assertions are the Gap 525 security guard, copied verbatim. They are
    assertions rather than a soft skip on purpose: a misconfigured URL should
    stop the run loudly, because the fixtures that call this drop every table
    after each test.
    """
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        return None

    parsed = urlparse(url)
    assert parsed.hostname in ("localhost", "127.0.0.1"), (
        "Gap 525 security guard: TEST_DATABASE_URL must point to localhost or "
        "127.0.0.1 to avoid accidental data loss."
    )
    assert "test" in (parsed.path or "").lower(), (
        "Gap 525 security guard: TEST_DATABASE_URL must name a throwaway database "
        "whose name contains 'test' (these fixtures drop every table after each test)."
    )
    return url


def is_postgres_run() -> bool:
    """True when this process will exercise Postgres rather than SQLite.

    Tests that assert engine-specific behaviour (JSONB containment, NOT NULL
    enforcement the models do not declare) should gate on this rather than
    silently proving nothing on the SQLite branch.
    """
    return _guarded_postgres_url() is not None


def make_test_engine():
    """An engine against `TEST_DATABASE_URL` if set and valid, else in-memory SQLite.

    The SQLite branch keeps `StaticPool` and `check_same_thread=False` so a
    single in-memory database is shared across connections; neither argument is
    valid for psycopg, so the Postgres branch passes neither.
    """
    url = _guarded_postgres_url()
    if url:
        return create_engine(url)
    return create_engine(
        SQLITE_MEMORY_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
