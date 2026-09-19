"""BE Gap 685: the shared Postgres-or-SQLite engine factory, and its guard.

The guard is the only thing standing between a test run and a dropped
development database -- the fixtures that use this factory call
`SQLModel.metadata.drop_all` after every test, so a `TEST_DATABASE_URL` pointing
at `invoice_db` on a shared host would destroy it. Gap 525 wrote that guard;
this file pins it, which Gap 525 never did.

No database is required: the guard runs entirely on the URL string, and
`create_engine` does not connect eagerly, so every case here is offline.
"""

import pytest
from sqlalchemy.pool import StaticPool

from tests._postgres_test_engine import (
    SQLITE_MEMORY_URL,
    is_postgres_run,
    make_test_engine,
)


# ───────────────────────────── the SQLite fallback ───────────────────────────

def test_unset_falls_back_to_in_memory_sqlite(monkeypatch):
    """Every unattended run takes this branch -- nothing in CI sets the variable."""
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    engine = make_test_engine()
    assert engine.url.drivername.startswith("sqlite")
    assert is_postgres_run() is False


def test_empty_string_falls_back_to_sqlite(monkeypatch):
    """An exported-but-empty variable must not be read as a Postgres URL."""
    monkeypatch.setenv("TEST_DATABASE_URL", "")
    engine = make_test_engine()
    assert engine.url.drivername.startswith("sqlite")


def test_sqlite_branch_keeps_shared_in_memory_pooling(monkeypatch):
    """`StaticPool` + `check_same_thread=False` is what makes one in-memory
    database visible across connections. Losing either silently gives each
    connection its own empty database."""
    monkeypatch.delenv("TEST_DATABASE_URL", raising=False)
    engine = make_test_engine()
    assert isinstance(engine.pool, StaticPool)
    assert str(engine.url) == SQLITE_MEMORY_URL


# ───────────────────────────── the Gap 525 guard ─────────────────────────────

@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@db.example.com:5432/invoice_test",
        "postgresql://u:p@10.0.0.5:5432/invoice_test",
        "postgresql://u:p@prod-db:5432/invoice_test",
    ],
)
def test_non_local_host_is_refused(monkeypatch, url):
    """A remote host is refused even when the database name says "test"."""
    monkeypatch.setenv("TEST_DATABASE_URL", url)
    with pytest.raises(AssertionError, match="localhost or"):
        make_test_engine()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@localhost:5433/invoice_db",
        "postgresql://u:p@127.0.0.1:5433/postgres",
        "postgresql://u:p@localhost:5433/",
    ],
)
def test_database_name_without_test_is_refused(monkeypatch, url):
    """The dev database `invoice_db` on localhost:5433 is deliberately refused --
    these fixtures drop every table after each test."""
    monkeypatch.setenv("TEST_DATABASE_URL", url)
    with pytest.raises(AssertionError, match="throwaway database"):
        make_test_engine()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://u:p@localhost:5433/invoice_test",
        "postgresql://u:p@127.0.0.1:5433/extraction_test",
        "postgresql://u:p@localhost:5433/TEST_invoice",
    ],
)
def test_guarded_local_test_database_is_accepted(monkeypatch, url):
    """A local, throwaway-named database is accepted and used verbatim.

    `create_engine` does not connect, so this asserts the routing decision
    without needing a live server.
    """
    monkeypatch.setenv("TEST_DATABASE_URL", url)
    engine = make_test_engine()
    assert engine.url.drivername.startswith("postgresql")
    assert engine.url.database.lower().find("test") >= 0
    assert is_postgres_run() is True


def test_postgres_branch_passes_no_sqlite_only_arguments(monkeypatch):
    """`check_same_thread` and `StaticPool` are SQLite-only; handing either to
    psycopg fails at connect time, which would look like an environment problem
    rather than a wiring bug."""
    monkeypatch.setenv("TEST_DATABASE_URL", "postgresql://u:p@localhost:5433/invoice_test")
    engine = make_test_engine()
    assert not isinstance(engine.pool, StaticPool)
    assert "check_same_thread" not in (engine.dialect.create_connect_args(engine.url)[1] or {})
