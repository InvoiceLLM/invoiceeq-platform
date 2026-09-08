"""Feature 30 task 30.13 — the correction flywheel and its workbook panels.

Verification plan 30.13: "Thumbs-down writes `chat_correction`;
`promote_to_example()` creates a certified row; workbook KQL dry-runs."

The KQL cannot be executed here (it needs a Log Analytics workspace), so what is
asserted instead is everything that CAN be checked offline and that actually
breaks in practice: the panel is present in the workbook, it is valid JSON of
the right item shape, and every field it parses out of `Properties` is a field
the emitter actually emits. A panel that queries a field nothing writes is the
failure mode this repo has hit before, and it is invisible until someone opens
the workbook.

Real Postgres for the table half. No LLM anywhere.
"""
import json
import os
import re
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from models import CertifiedSqlExample, ChatCorrection  # noqa: E402
from services import chat_corrections as cc  # noqa: E402

WORKBOOK = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "infra", "monitoring", "ai_control_tower_workbook.json",
)


@pytest.fixture(name="pg_session")
def pg_session_fixture():
    psycopg2 = pytest.importorskip("psycopg2")
    from config import get_settings

    url = get_settings().DATABASE_URL
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")
    try:
        psycopg2.connect(url, connect_timeout=5).close()
    except psycopg2.OperationalError as exc:  # pragma: no cover - env dependent
        pytest.skip(f"local Postgres not reachable: {exc}")

    engine = create_engine(url)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="tenants")
def tenants_fixture(pg_session):
    a, b = uuid4(), uuid4()
    yield a, b
    for model in (ChatCorrection, CertifiedSqlExample):
        for row in pg_session.exec(select(model).where(model.tenant_id.in_([a, b]))).all():
            pg_session.delete(row)
        pg_session.commit()


# --- recording -------------------------------------------------------------


def test_a_thumbs_down_writes_a_pending_correction(pg_session, tenants):
    tenant_a, _ = tenants
    row = cc.record_correction(
        tenant_a,
        pg_session,
        card="agreed_vs_billed",
        finding_key="agreed_vs_billed:INV-1",
        reason="wrong_figure",
        corrected_text="the PO was revised to 123200 before the invoice",
        created_by="owner@example.com",
    )
    assert row.status == "PENDING"
    assert row.vote == "down"
    assert row.card == "agreed_vs_billed"


def test_feedback_with_no_explanation_is_still_recorded(pg_session, tenants):
    """The cheapest feedback there is must not be refused."""
    tenant_a, _ = tenants
    row = cc.record_correction(tenant_a, pg_session, card="cash_impact")
    assert row.status == "PENDING"
    assert row.reason is None


def test_an_unknown_reason_is_refused(pg_session, tenants):
    tenant_a, _ = tenants
    with pytest.raises(cc.CorrectionError):
        cc.record_correction(tenant_a, pg_session, reason="because_i_said_so")


# --- promotion -------------------------------------------------------------


def test_promotion_creates_a_certified_example(pg_session, tenants):
    tenant_a, _ = tenants
    correction = cc.record_correction(
        tenant_a,
        pg_session,
        card="agreed_vs_billed",
        reason="wrong_figure",
        corrected_text="what have we been billed against PO-77?",
        corrected_sql="SELECT SUM(grand_total) FROM invoice WHERE po_number = :po",
    )
    example = cc.promote_to_example(
        correction.id, pg_session, tenant_a, certified_by="owner@example.com"
    )
    assert example.certified is True
    assert example.source_correction_id == correction.id

    pg_session.refresh(correction)
    assert correction.status == "PROMOTED"
    assert correction.promoted_example_id == example.id


def test_promotion_is_idempotent(pg_session, tenants):
    tenant_a, _ = tenants
    correction = cc.record_correction(
        tenant_a, pg_session, corrected_text="q?", corrected_sql="SELECT 1"
    )
    first = cc.promote_to_example(correction.id, pg_session, tenant_a)
    second = cc.promote_to_example(correction.id, pg_session, tenant_a)
    assert first.id == second.id
    assert (
        len(pg_session.exec(
            select(CertifiedSqlExample).where(CertifiedSqlExample.tenant_id == tenant_a)
        ).all())
        == 1
    )


def test_promotion_without_sql_is_refused(pg_session, tenants):
    """An example with nothing to learn from still consumes a retrieval slot."""
    tenant_a, _ = tenants
    correction = cc.record_correction(tenant_a, pg_session, corrected_text="q?")
    with pytest.raises(cc.CorrectionError):
        cc.promote_to_example(correction.id, pg_session, tenant_a)


def test_another_tenants_correction_cannot_be_promoted(pg_session, tenants):
    tenant_a, tenant_b = tenants
    correction = cc.record_correction(
        tenant_a, pg_session, corrected_text="q?", corrected_sql="SELECT 1"
    )
    assert cc.promote_to_example(correction.id, pg_session, tenant_b) is None


def test_a_rejected_correction_is_not_promotable(pg_session, tenants):
    tenant_a, _ = tenants
    correction = cc.record_correction(
        tenant_a, pg_session, corrected_text="q?", corrected_sql="SELECT 1"
    )
    cc.reject_correction(correction.id, pg_session, tenant_a, note="the PO was not revised")
    with pytest.raises(cc.CorrectionError):
        cc.promote_to_example(correction.id, pg_session, tenant_a)


def test_nothing_is_learned_until_a_human_promotes(pg_session, tenants):
    """The property that makes this a flywheel and not an autolearner."""
    from services import certified_examples as ce

    tenant_a, _ = tenants
    cc.record_correction(
        tenant_a,
        pg_session,
        corrected_text="what have we been billed against PO-77?",
        corrected_sql="SELECT 1",
    )
    assert (
        pg_session.exec(
            select(CertifiedSqlExample).where(CertifiedSqlExample.tenant_id == tenant_a)
        ).all()
        == []
    )


def test_stats_count_what_the_panel_renders(pg_session, tenants):
    tenant_a, _ = tenants
    cc.record_correction(tenant_a, pg_session, card="agreed_vs_billed", reason="wrong_figure")
    promoted = cc.record_correction(
        tenant_a, pg_session, card="cash_impact", reason="not_relevant",
        corrected_text="q?", corrected_sql="SELECT 1",
    )
    cc.promote_to_example(promoted.id, pg_session, tenant_a)

    stats = cc.correction_stats(tenant_a, pg_session)
    assert stats["total"] == 2
    assert stats["pending"] == 1
    assert stats["promoted"] == 1
    assert stats["by_card"]["agreed_vs_billed"] == 1
    assert stats["by_reason"]["wrong_figure"] == 1


# --- the workbook panels ---------------------------------------------------


def _workbook_items():
    with open(WORKBOOK, "r", encoding="utf-8") as fh:
        return json.load(fh)["items"]


def test_both_panels_are_in_the_workbook():
    names = {item.get("name") for item in _workbook_items()}
    assert {"f30-open-insights", "f30-chat-quality-trend"} <= names


@pytest.mark.parametrize("name", ["f30-open-insights", "f30-chat-quality-trend"])
def test_a_panel_is_a_well_formed_kql_item(name):
    item = next(i for i in _workbook_items() if i.get("name") == name)
    assert item["type"] == 3
    content = item["content"]
    assert content["version"] == "KqlItem/1.0"
    assert content["resourceType"] == "microsoft.operationalinsights/workspaces"
    assert content["title"]
    query = content["query"]
    assert query.startswith("AppEvents")
    # Balanced enough to be a query rather than a fragment.
    assert query.count("(") == query.count(")")
    assert "| summarize" in query


@pytest.mark.parametrize(
    "name,event,emitter",
    [
        ("f30-open-insights", "insight_bubble", "track_insight_bubble"),
        ("f30-chat-quality-trend", "insight_feedback", "track_insight_feedback"),
    ],
)
def test_every_field_a_panel_reads_is_a_field_the_emitter_writes(name, event, emitter):
    """The failure this test exists for: a panel that queries a field nothing
    emits renders an empty chart and looks like "no problems"."""
    import inspect

    import telemetry

    item = next(i for i in _workbook_items() if i.get("name") == name)
    query = item["content"]["query"]
    assert f'Name == "{event}"' in query

    source = inspect.getsource(getattr(telemetry, emitter))
    emitted = set(re.findall(r'"([a-z_]+)":', source))
    read = set(re.findall(r"d\.([a-z_]+)", query))
    assert read, "the panel parses no fields at all"
    assert read <= emitted, f"{name} reads fields nothing emits: {sorted(read - emitted)}"


def test_the_panels_never_read_a_tenants_content():
    """Monitoring events land in a shared workspace; finding text must not."""
    import inspect

    import telemetry

    for emitter in ("track_insight_bubble", "track_insight_feedback"):
        source = inspect.getsource(getattr(telemetry, emitter))
        for forbidden in ("title", "party_name", "vendor_name", "narration", "verdict\"", "finding_key"):
            assert f'"{forbidden}"' not in source, f"{emitter} emits {forbidden}"
