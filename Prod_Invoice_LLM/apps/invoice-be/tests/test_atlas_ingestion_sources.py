"""Feature 34 (ATLAS) tasks 34.13 and 34.3c — many ingestion sources, and the
Loader's per-source lines.

Spec: `docs/feature_34_atlas.md` §2.3, §13.1 · decision D43.

**This file requires migration `a1b2c34d13e5` to have run.** Every test in it
touches `tenant_autopilot_logs.source_config_id` or writes two
`tenant_autopilot_configs` rows for one tenant, and neither is possible until
the migration drops `uq_autopilot_config_tenant` and adds the column.

**It is separated from `test_atlas_skills.py` for exactly that reason and it
fails loudly rather than skipping** (BE Gap 697's rule: a test that hides itself
is worse than a test that is red). On the dev machine this build ran on, the
migration could not be applied -- `alembic upgrade head` fails because the
database's `alembic_version` names revision `a1b2c3f33003`, which exists in no
branch of this repo. That is **BE Gap 698**, filed in the tracker, and this file
is the thing that turns green when it is resolved.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

from models import Tenant, TenantAutopilotConfig, TenantAutopilotLog
from services.atlas_capabilities import AtlasCapability
from services.atlas_skills import SkillContext, loader_lines
from services.autopilot_sync import list_ingestion_sources
from tests.atlas_pg import open_session, postgres_only, unique_tag

NOW = datetime(2026, 9, 17, 12, 0, 0)


@pytest.fixture(scope="module")
def pg_session():
    session = open_session()
    exists = session.exec(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'tenant_autopilot_logs' "
            "AND column_name = 'source_config_id'"
        )
    ).first()
    if not exists:
        session.close()
        pytest.fail(
            "task 34.13's migration a1b2c34d13e5 has not been applied to this "
            "database: tenant_autopilot_logs.source_config_id is missing. "
            "`alembic upgrade head` currently fails because alembic_version names "
            "revision a1b2c3f33003, which is in no branch — BE Gap 698. This is a "
            "failure and not a skip on purpose: the code under test is written "
            "against the migrated schema."
        )
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def pg(pg_session):
    tag = unique_tag()
    tenant = Tenant(name=f"atlas-sources-{tag}", domain=f"atlas-sources-{tag}.test")
    pg_session.add(tenant)
    pg_session.commit()
    pg_session.refresh(tenant)
    written: list = []
    try:
        yield pg_session, tenant, written
    finally:
        pg_session.rollback()
        for row in written:
            pg_session.delete(row)
        pg_session.commit()
        pg_session.delete(tenant)
        pg_session.commit()


def _source(session, written, tenant, *, ref: str | None = None, created=None):
    config = TenantAutopilotConfig(
        tenant_id=tenant.id,
        source_type="gdrive",
        source_ref=ref or f"folder-{unique_tag()}",
        trigger_mode="interval",
        trigger_value="60",
        created_at=created or datetime(2026, 8, 1, 9, 0, 0),
    )
    session.add(config)
    session.commit()
    session.refresh(config)
    written.append(config)
    return config


def _log(session, written, tenant, config, *, status, ingested_at, **fields):
    log = TenantAutopilotLog(
        tenant_id=tenant.id,
        source_type=config.source_type,
        source_config_id=config.id,
        source_file_id=fields.get("file_id", uuid4().hex),
        source_file_name=fields.get("file_name"),
        content_hash=fields.get("content_hash", ""),
        status=status,
        error_detail=fields.get("error_detail"),
        ingested_at=ingested_at,
    )
    session.add(log)
    session.commit()
    session.refresh(log)
    written.append(log)
    return log


def _ctx(tenant) -> SkillContext:
    return SkillContext(tenant_id=tenant.id, today=NOW.date(), now=NOW)


# ═════════════════════════════════════════════════════════════════════════════
# 34.13 — the schema change itself (D43)
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_a_tenant_may_have_more_than_one_ingestion_source(pg):
    """The whole of D43: this insert used to raise on `uq_autopilot_config_tenant`."""
    session, tenant, written = pg
    drive = _source(session, written, tenant, ref="folder-ap")
    mailbox = _source(session, written, tenant, ref="folder-ar")
    sources = list_ingestion_sources(session, tenant.id)
    assert [s.id for s in sources] == [drive.id, mailbox.id]


@postgres_only
def test_the_same_source_cannot_be_registered_twice(pg):
    """What replaces the dropped constraint, and why it was worth replacing.

    Registering the same folder twice would double-ingest every file in it. The
    old UNIQUE was preventing that by accident; the new one does it on purpose.
    """
    session, tenant, written = pg
    _source(session, written, tenant, ref="folder-same")
    with pytest.raises(Exception) as exc:
        _source(session, written, tenant, ref="folder-same")
    assert "uq_autopilot_config_tenant_source" in str(exc.value)
    session.rollback()


@postgres_only
def test_every_log_row_names_the_source_that_wrote_it(pg):
    session, tenant, written = pg
    a = _source(session, written, tenant, ref="folder-a")
    b = _source(session, written, tenant, ref="folder-b")
    log_a = _log(session, written, tenant, a, status="SUCCESS", ingested_at=NOW)
    log_b = _log(session, written, tenant, b, status="FAILED", ingested_at=NOW)
    assert log_a.source_config_id == a.id
    assert log_b.source_config_id == b.id


# ═════════════════════════════════════════════════════════════════════════════
# 34.3c — the Loader's lines, per source (§2.3, D22, D43)
# ═════════════════════════════════════════════════════════════════════════════

@postgres_only
def test_a_quiet_source_produces_its_own_line_and_names_itself(pg):
    """Absence as a query, run on open (D38) — and about **one** source (D43)."""
    session, tenant, written = pg
    busy = _source(session, written, tenant, ref="folder-busy")
    quiet = _source(session, written, tenant, ref="folder-quiet")
    _log(session, written, tenant, busy, status="SUCCESS", ingested_at=NOW - timedelta(hours=2))
    _log(
        session, written, tenant, quiet, status="SUCCESS",
        ingested_at=NOW - timedelta(days=40),
    )

    quiet_lines = [
        line for line in loader_lines(session, _ctx(tenant))
        if line.skill == "ingestion_source_has_gone_quiet"
    ]
    assert len(quiet_lines) == 1, "a healthy source must not vouch for a dead one"
    line = quiet_lines[0]
    assert line.capability is AtlasCapability.LOAD
    assert line.what.entity_kind == "ingestion_source"
    assert line.what.entity_id == str(quiet.id)
    assert quiet.source_ref in line.what.headline
    assert line.action.params["source_config_id"] == str(quiet.id)


@postgres_only
def test_a_failed_file_line_carries_the_fix_not_the_fault(pg):
    """§2.3/D22: "why it failed **and the fix**, not the fault"."""
    session, tenant, written = pg
    source = _source(session, written, tenant, ref="folder-fail")
    _log(session, written, tenant, source, status="SUCCESS", ingested_at=NOW - timedelta(hours=1))
    _log(
        session, written, tenant, source, status="FAILED",
        ingested_at=NOW - timedelta(minutes=30),
        file_name="scan.heic",
        error_detail="Unsupported upload type: image/heic",
    )
    lines = [
        line for line in loader_lines(session, _ctx(tenant))
        if line.skill == "ingestion_failures_by_source"
    ]
    assert len(lines) == 1
    line = lines[0]
    assert line.what.entity_id == str(source.id)
    assert "Re-save it as a PDF" in line.why.text
    assert "scan.heic" in line.why.text


@postgres_only
def test_one_source_failing_does_not_silence_the_others(pg):
    """The per-source guarantee, stated as the thing that would go wrong without it."""
    session, tenant, written = pg
    good = _source(session, written, tenant, ref="folder-good")
    bad = _source(session, written, tenant, ref="folder-bad")
    _log(session, written, tenant, good, status="SUCCESS", ingested_at=NOW - timedelta(hours=1))
    _log(
        session, written, tenant, bad, status="FAILED",
        ingested_at=NOW - timedelta(hours=1),
        file_name="broken.pdf", error_detail="permission denied on folder",
    )
    failures = [
        line for line in loader_lines(session, _ctx(tenant))
        if line.skill == "ingestion_failures_by_source"
    ]
    assert [line.what.entity_id for line in failures] == [str(bad.id)]
    assert "Share the folder" in failures[0].why.text
