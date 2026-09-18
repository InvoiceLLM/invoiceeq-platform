"""BE Gap 642: the schema the suites test vs the schema the migrations build.

Every ported suite builds its tables with `SQLModel.metadata.create_all` and drops
them afterwards, so no test ever exercises `alembic upgrade head`. A migration that
drifts from the models -- a missed `nullable`, a column a migration forgot, a type
that differs -- passes every test and fails in production. That is the failure class
this file catches, in the cheap form the gap proposed: build both schemas in turn on
the same throwaway database and compare them.

Guarded like the Gap 525/570 fixtures: `TEST_DATABASE_URL` must name a local,
throwaway database with "test" in its name, because this file drops every table.
"""
import os
from urllib.parse import urlparse

import pytest
from sqlalchemy import text
from sqlmodel import SQLModel, create_engine

import models  # noqa: F401  -- registers every table on SQLModel.metadata

PG_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not PG_URL, reason="needs TEST_DATABASE_URL (Postgres) -- CONVENTIONS hard rule 2"
)


def _guard(url: str) -> None:
    parsed = urlparse(url)
    assert parsed.hostname in ("localhost", "127.0.0.1"), (
        "Gap 525 guard: TEST_DATABASE_URL must point to localhost or 127.0.0.1."
    )
    assert "test" in (parsed.path or "").lower(), (
        "Gap 525 guard: TEST_DATABASE_URL must name a throwaway database whose name contains 'test'."
    )


def _snapshot(engine) -> dict:
    """{table: {column: (data_type, is_nullable)}} for the public schema."""
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT table_name, column_name, data_type, is_nullable "
            "FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name <> 'alembic_version'"
        )).all()
    out: dict = {}
    for table, column, dtype, nullable in rows:
        out.setdefault(table, {})[column] = (dtype, nullable)
    return out


def _wipe(engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
        conn.commit()


@pytest.fixture(scope="module")
def schemas():
    _guard(PG_URL)
    engine = create_engine(PG_URL)

    _wipe(engine)
    from alembic import command
    from alembic.config import Config
    from config import settings as app_settings

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", PG_URL)
    # `alembic/env.py` resolves the URL from `settings.DATABASE_URL`, not from the
    # Config object, so pointing only `sqlalchemy.url` at the throwaway database
    # would migrate the developer's real one instead.
    previous = app_settings.DATABASE_URL
    app_settings.DATABASE_URL = PG_URL
    try:
        # 12 heads live in `alembic/versions/`, so "heads" rather than "head".
        command.upgrade(cfg, "heads")
    finally:
        app_settings.DATABASE_URL = previous
    migrated = _snapshot(engine)

    _wipe(engine)
    SQLModel.metadata.create_all(engine)
    declared = _snapshot(engine)

    _wipe(engine)
    engine.dispose()
    return migrated, declared


def test_every_model_table_exists_in_the_migrated_schema(schemas):
    migrated, declared = schemas
    missing = sorted(set(declared) - set(migrated))
    assert not missing, (
        f"{len(missing)} table(s) the models declare that no migration builds: {missing}. "
        "Every suite would pass and production would not have these."
    )


def test_every_model_column_exists_in_the_migrated_schema(schemas):
    migrated, declared = schemas
    gaps = {
        t: sorted(set(cols) - set(migrated.get(t, {})))
        for t, cols in declared.items()
        if t in migrated and set(cols) - set(migrated.get(t, {}))
    }
    assert not gaps, f"columns the models declare that no migration adds: {gaps}"


def test_nullability_agrees_between_the_two_schemas(schemas):
    migrated, declared = schemas
    disagreements = {}
    for t, cols in declared.items():
        for c, (_dtype, nullable) in cols.items():
            other = migrated.get(t, {}).get(c)
            if other and other[1] != nullable:
                disagreements[f"{t}.{c}"] = {"migrated": other[1], "models": nullable}
    assert not disagreements, f"nullability drift: {disagreements}"
