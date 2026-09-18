"""Feature 34 (ATLAS) Slice B — the shared Postgres guard for the ATLAS tests.

Not a test module (no `test_` prefix, so pytest does not collect it). It exists
so the four Slice B test files share **one** Postgres guard rather than four
copies of it -- BE Gap 697 is precisely what happens when a fixture shape is
copied into 31 files and then has to be fixed in 31 places.

The rules it encodes, both of which are hard rules, not preferences:

* **CONVENTIONS hard rule 2** -- a SQLite run is not evidence. A `DATABASE_URL`
  that is not Postgres is a legitimate skip: that developer asked for SQLite and
  their run proves nothing either way.
* **BE Gap 697** -- a Postgres URL that will not connect is a **failure**, not a
  skip, after one retry for the transient `::1` reset documented in that gap.
  A test that hides itself is worse than a test that is red.
* **BE Gap 666** -- every guard reads `get_settings()`, never a bare env var. A
  guard on a variable the app never exports hid 23 tests behind a green report.
"""

from __future__ import annotations

import time
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine

from config import get_settings

_SETTINGS = get_settings()

postgres_only = pytest.mark.skipif(
    not str(_SETTINGS.DATABASE_URL or "").startswith("postgresql"),
    reason=(
        "Hard rule 2: only a Postgres run is evidence. Set DATABASE_URL to the dev "
        "Postgres (127.0.0.1:5433/invoice_db -- 127.0.0.1, not localhost, per BE "
        "Gap 697) and re-run. Read through get_settings(), never a bare env var."
    ),
)


def open_session() -> Session:
    """A session on the real dev Postgres, or a clear skip / failure.

    Yields nothing and manages nothing: the caller owns the session's lifetime,
    because every ATLAS test cleans up the exact rows it wrote and a
    module-scoped auto-rollback would hide a write that did not land.
    """
    psycopg2 = pytest.importorskip("psycopg2")
    url = get_settings().DATABASE_URL
    if not str(url).startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL - see .claude/skills/verify-postgres")

    last: Exception | None = None
    for _ in range(2):
        try:
            psycopg2.connect(url).close()
            last = None
            break
        except psycopg2.OperationalError as exc:  # BE Gap 697: retry once, then fail
            last = exc
            time.sleep(1)
    if last is not None:
        pytest.fail(
            f"DATABASE_URL points at Postgres but it did not connect after 2 attempts: {last}"
        )

    engine = create_engine(str(url))
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def unique_tag() -> str:
    """A short unique suffix, so two runs of a file never collide on a domain."""
    return uuid4().hex[:12]
