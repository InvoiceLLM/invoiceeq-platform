"""Feature 30 task 30.8 — certified examples and the suggested-questions card.

Verification plan 30.8: "Uncertified row never retrieved; three questions
returned, all tagged for the doc type."

Real Postgres: `certified_sql_example` is a real table with a real nullable
`tenant_id` (global examples), and the retrieval query is an OR over that
nullability — the exact shape SQLite would let pass while behaving differently.
"""
import os
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

os.environ.setdefault("MOCK_EMBEDDINGS", "true")

from models import CertifiedSqlExample  # noqa: E402
from services import certified_examples as ce  # noqa: E402


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


@pytest.fixture(name="flag_on")
def flag_on_fixture(monkeypatch):
    from config import get_settings

    monkeypatch.setattr(get_settings(), "ENABLE_CERTIFIED_EXAMPLES", True, raising=False)
    yield


@pytest.fixture(name="tenants")
def tenants_fixture(pg_session):
    a, b = uuid4(), uuid4()
    written: list = []
    yield a, b, written
    for row in pg_session.exec(
        select(CertifiedSqlExample).where(CertifiedSqlExample.tenant_id.in_([a, b]))
    ).all():
        pg_session.delete(row)
    for row_id in written:
        row = pg_session.get(CertifiedSqlExample, row_id)
        if row is not None:
            pg_session.delete(row)
    pg_session.commit()


# --- the certification gate ------------------------------------------------


def test_an_uncertified_row_is_never_retrieved(pg_session, tenants, flag_on):
    tenant_a, _, written = tenants
    proposed = ce.certify_example(
        "what did we spend with Shree Packaging?",
        "SELECT 1",
        pg_session,
        tenant_id=tenant_a,
        certified=False,
    )
    written.append(proposed.id)
    assert proposed.certified is False
    assert proposed.certified_at is None

    assert ce.retrieve_examples("what did we spend with Shree Packaging?", pg_session, tenant_a) == []


def test_certifying_makes_it_retrievable(pg_session, tenants, flag_on):
    tenant_a, _, written = tenants
    row = ce.certify_example(
        "what did we spend with Shree Packaging?",
        "SELECT SUM(grand_total) FROM invoice WHERE vendor_name = :v",
        pg_session,
        tenant_id=tenant_a,
        certified_by="owner@example.com",
    )
    written.append(row.id)
    found = ce.retrieve_examples("what did we spend with Shree Packaging?", pg_session, tenant_a)
    assert len(found) == 1
    assert found[0]["scope"] == "tenant"
    assert found[0]["sql"].startswith("SELECT SUM")


def test_nothing_is_retrieved_with_the_flag_off(pg_session, tenants):
    tenant_a, _, written = tenants
    written.append(ce.certify_example("q", "SELECT 1", pg_session, tenant_id=tenant_a).id)
    assert ce.retrieve_examples("q", pg_session, tenant_a) == []


def test_an_example_needs_both_halves(pg_session, tenants):
    with pytest.raises(ValueError):
        ce.certify_example("", "SELECT 1", pg_session)
    with pytest.raises(ValueError):
        ce.certify_example("question", "  ", pg_session)


# --- scoping ---------------------------------------------------------------


def test_a_global_example_is_visible_to_every_tenant(pg_session, tenants, flag_on):
    _, tenant_b, written = tenants
    row = ce.certify_example(
        "what is overdue?", "SELECT * FROM v_overdue", pg_session, tenant_id=None
    )
    written.append(row.id)
    found = ce.retrieve_examples("what is overdue?", pg_session, tenant_b)
    assert [f["scope"] for f in found] == ["global"]


def test_one_tenants_example_is_invisible_to_another(pg_session, tenants, flag_on):
    tenant_a, tenant_b, written = tenants
    written.append(
        ce.certify_example("our own private question", "SELECT 1", pg_session, tenant_id=tenant_a).id
    )
    assert ce.retrieve_examples("our own private question", pg_session, tenant_b) == []


def test_a_tenant_example_outranks_a_global_one_on_a_tie(pg_session, tenants, flag_on):
    tenant_a, _, written = tenants
    question = "what is overdue with this supplier?"
    written.append(ce.certify_example(question, "SELECT 'global'", pg_session, tenant_id=None).id)
    written.append(
        ce.certify_example(question, "SELECT 'tenant'", pg_session, tenant_id=tenant_a).id
    )
    found = ce.retrieve_examples(question, pg_session, tenant_a)
    assert found[0]["scope"] == "tenant"


def test_an_unrelated_question_is_not_returned(pg_session, tenants, flag_on):
    tenant_a, _, written = tenants
    written.append(
        ce.certify_example(
            "how much did we spend on packaging last year?", "SELECT 1", pg_session, tenant_id=tenant_a
        ).id
    )
    assert ce.retrieve_examples("who signed the contract?", pg_session, tenant_a) == []


# --- suggested questions ---------------------------------------------------


def test_three_starters_are_offered_for_every_supported_doc_type(pg_session, tenants):
    from services.attachment_insights import INSIGHT_DOC_TYPES

    tenant_a, _, _ = tenants
    for doc_type in INSIGHT_DOC_TYPES:
        questions = ce.suggested_questions(doc_type, pg_session, tenant_a)
        assert len(questions) == 3, doc_type
        assert all(q["doc_type"] == doc_type for q in questions), doc_type
        assert all(q["question"].endswith("?") for q in questions), doc_type


def test_certified_questions_replace_the_starters_for_that_type(pg_session, tenants, flag_on):
    tenant_a, _, written = tenants
    for i in range(3):
        written.append(
            ce.certify_example(
                f"tenant question {i} about this order?",
                "SELECT 1",
                pg_session,
                tenant_id=tenant_a,
                doc_type="PURCHASE_ORDER",
            ).id
        )
    questions = ce.suggested_questions("PURCHASE_ORDER", pg_session, tenant_a)
    assert [q["source"] for q in questions] == ["certified"] * 3


def test_an_uncertified_question_is_never_suggested(pg_session, tenants, flag_on):
    tenant_a, _, written = tenants
    written.append(
        ce.certify_example(
            "an unapproved question?",
            "SELECT 1",
            pg_session,
            tenant_id=tenant_a,
            doc_type="QUOTATION",
            certified=False,
        ).id
    )
    questions = ce.suggested_questions("QUOTATION", pg_session, tenant_a)
    assert all(q["source"] == "starter" for q in questions)


def test_the_bubble_carries_the_questions(pg_session, tenants, monkeypatch):
    """30.8's other half: the card is in every document type's list."""
    from datetime import date

    from config import get_settings
    from models import ChatAttachment, ChatSession
    from services import attachment_insights as ai

    monkeypatch.setattr(get_settings(), "ENABLE_ATTACHMENT_INSIGHTS", True, raising=False)
    tenant_a, _, _ = tenants

    chat = ChatSession(tenant_id=tenant_a, title="F30 questions")
    pg_session.add(chat)
    pg_session.commit()
    pg_session.refresh(chat)
    att = ChatAttachment(
        tenant_id=tenant_a, session_id=chat.id, filename="po.pdf", blob_path="",
        doc_type="PURCHASE_ORDER", extraction_status="EXTRACTED", party_name="Shree Packaging",
        doc_date=date(2026, 2, 20), currency="INR", grand_total=1000.0, extracted_json={},
    )
    pg_session.add(att)
    pg_session.commit()
    pg_session.refresh(att)

    try:
        block = ai.build_insight_block(att, pg_session, tenant_a, stage="sync")
        card = next(c for c in block["cards"] if c["card"] == "suggested_questions")
        assert card["status"] == "ok"
        assert len(card["evidence"]["questions"]) == 3
        # A question is not a finding: it must not open work on the dashboard.
        assert all(f["card"] != "suggested_questions" for f in block["findings"])
    finally:
        pg_session.delete(att)
        pg_session.delete(chat)
        pg_session.commit()
