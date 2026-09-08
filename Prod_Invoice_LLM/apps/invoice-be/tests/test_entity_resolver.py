"""Feature 29 task 29.11 (phase-2 P2.1, Gap 490) -- `agents/entity_resolver.py`.

Real Postgres (`DATABASE_URL`, hard rule 2) for every lookup that touches the
`invoice` table; the attachment and session-reference resolvers take plain
objects and need no database. Nothing here calls a model: the resolver is
deterministic by design (hard rule 3), and every assertion is about a binding it
either makes exactly or refuses to make.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import Invoice  # noqa: E402
from agents import entity_resolver as er  # noqa: E402
from agents.entity_resolver import resolve_entities  # noqa: E402


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


@pytest.fixture(name="tenant")
def tenant_fixture(pg_session):
    tenant_id = uuid4()
    yield tenant_id
    for inv in pg_session.exec(select(Invoice).where(Invoice.tenant_id == tenant_id)).all():
        pg_session.delete(inv)
    pg_session.commit()


def _seed(pg_session, tenant_id, number, vendor="Rajesh Steel Traders"):
    inv = Invoice(
        id=uuid4(), tenant_id=tenant_id, file_path="f29/resolver.pdf", flow_direction="INBOUND",
        status="COMPLETED", invoice_number=number, vendor_name=vendor, currency="INR",
        subtotal=1000.0, tax_amount=180.0, grand_total=1180.0,
    )
    pg_session.add(inv)
    pg_session.commit()
    return inv


@dataclass
class _Att:
    id: str
    doc_type: str
    filename: str


# ---------------------------------------------------------------------------
# Invoice numbers
# ---------------------------------------------------------------------------


def test_exact_invoice_number_binds_case_and_whitespace_insensitively(pg_session, tenant):
    inv = _seed(pg_session, tenant, "INV-2026-0042")
    r = resolve_entities("what is the total on inv-2026-0042 ?", str(tenant), pg_session)
    assert r.invoice_ids == [str(inv.id)]
    assert not r.needs_clarification


def test_a_typo_is_a_suggestion_not_a_binding(pg_session, tenant):
    inv = _seed(pg_session, tenant, "INV-2026-0042")
    r = resolve_entities("show me INV-2026-0043", str(tenant), pg_session)
    assert r.invoice_ids == []
    [e] = r.entities
    assert e.status == "suggested"
    assert [c.id for c in e.candidates] == [str(inv.id)]
    assert "Did you mean INV-2026-0042" in r.clarify_message()


def test_an_unknown_number_resolves_to_none_and_clarifies(pg_session, tenant):
    _seed(pg_session, tenant, "INV-2026-0042")
    r = resolve_entities("what about PO-9999-77?", str(tenant), pg_session)
    assert r.needs_clarification
    assert r.entities[0].status == "none"
    assert "could not find" in r.clarify_message()


def test_another_tenants_invoice_is_never_bound(pg_session, tenant):
    other = uuid4()
    try:
        _seed(pg_session, other, "INV-2026-0042")
        r = resolve_entities("total on INV-2026-0042", str(tenant), pg_session)
        assert r.invoice_ids == []
        assert r.entities[0].status == "none"
    finally:
        for inv in pg_session.exec(select(Invoice).where(Invoice.tenant_id == other)).all():
            pg_session.delete(inv)
        pg_session.commit()


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------


def test_a_shortened_vendor_name_binds_by_substring(pg_session, tenant):
    _seed(pg_session, tenant, "INV-2026-0001", vendor="Cascade Manufacturing Co")
    r = resolve_entities("How much did we buy from Cascade Manufacturing last month?", str(tenant), pg_session)
    assert r.vendor_names == ["Cascade Manufacturing Co"]
    assert not r.needs_clarification


def test_a_misspelt_vendor_binds_only_above_the_fuzzy_threshold(pg_session, tenant):
    _seed(pg_session, tenant, "INV-2026-0001", vendor="Harbor Technologies")
    r = resolve_entities("invoices from Harbour Technologies", str(tenant), pg_session)
    assert r.vendor_names == ["Harbor Technologies"]
    r2 = resolve_entities("invoices from Harbinger Tech", str(tenant), pg_session)
    assert r2.vendor_names == []
    assert r2.entities[0].status == "none"


def test_two_vendors_sharing_a_word_are_ambiguous_and_listed(pg_session, tenant):
    _seed(pg_session, tenant, "INV-2026-0001", vendor="Metro Office Supplies")
    _seed(pg_session, tenant, "INV-2026-0002", vendor="Metro Logistics")
    r = resolve_entities("What do Metro's invoices add up to?", str(tenant), pg_session)
    [e] = r.entities
    assert e.status == "ambiguous"
    assert {c.label for c in e.candidates} == {"Metro Office Supplies", "Metro Logistics"}
    assert "Which vendor do you mean" in r.clarify_message()


def test_an_invoice_number_after_from_is_not_a_vendor(pg_session, tenant):
    inv = _seed(pg_session, tenant, "INV-2026-0042")
    r = resolve_entities("the tax from INV-2026-0042", str(tenant), pg_session)
    assert [e.kind for e in r.entities] == ["invoice"]
    assert r.invoice_ids == [str(inv.id)]


# ---------------------------------------------------------------------------
# Attachments and session references (no database)
# ---------------------------------------------------------------------------


def test_the_attached_binds_when_there_is_exactly_one_attachment():
    att = _Att("a1", "PURCHASE_ORDER", "po.pdf")
    r = resolve_entities("does the attached match my invoice", "t", None, attachments=[att])
    assert r.attachment_ids == ["a1"]


def test_this_document_with_two_attachments_is_ambiguous():
    atts = [_Att("a1", "PURCHASE_ORDER", "po.pdf"), _Att("a2", "CONTRACT", "msa.pdf")]
    r = resolve_entities("summarise this document", "t", None, attachments=atts)
    [e] = r.entities
    assert e.status == "ambiguous" and len(e.candidates) == 2


def test_the_contract_binds_by_document_type_and_the_second_po_by_ordinal():
    atts = [_Att("a1", "PURCHASE_ORDER", "po1.pdf"), _Att("a2", "CONTRACT", "msa.pdf"), _Att("a3", "PURCHASE_ORDER", "po2.pdf")]
    r = resolve_entities("what does the contract say about late fees", "t", None, attachments=atts)
    assert r.attachment_ids == ["a2"]
    r2 = resolve_entities("compare the second po to the invoice", "t", None, attachments=atts)
    assert r2.attachment_ids == ["a3"]


def test_the_second_one_binds_against_the_previous_turns_invoices():
    ids = [str(uuid4()), str(uuid4()), str(uuid4())]
    r = resolve_entities("explain the second one in detail", "t", None, recent_invoice_ids=ids)
    assert r.invoice_ids == [ids[1]]
    r2 = resolve_entities("and the last invoice?", "t", None, recent_invoice_ids=ids)
    assert r2.invoice_ids == [ids[2]]


def test_that_one_with_nothing_to_refer_to_clarifies():
    r = resolve_entities("what is the due date on that one", "t", None, recent_invoice_ids=[])
    assert r.needs_clarification and r.entities[0].status == "none"


# ---------------------------------------------------------------------------
# Fail-soft and the flag
# ---------------------------------------------------------------------------


def test_a_broken_session_resolves_nothing_rather_than_raising():
    class _Broken:
        def execute(self, *a, **k):
            raise RuntimeError("db down")

        def rollback(self):
            pass

    r = resolve_entities("total on INV-2026-0042 from Acme Corp", "t", _Broken())
    assert r.invoice_ids == [] and r.vendor_names == []


def test_the_flag_defaults_off_so_the_resolver_is_inert():
    from config import Settings

    assert Settings.model_fields["ENABLE_ENTITY_RESOLVER"].default is False
    assert er.INVOICE_SUGGEST_RATIO >= 0.8 and er.VENDOR_FUZZY_RATIO >= 0.85


# ---------------------------------------------------------------------------
# The wiring in `_run_query_agent`, flag ON, on real Postgres
# ---------------------------------------------------------------------------


def _run_turn(pg_session, tenant, message, monkeypatch):
    from contextlib import ExitStack
    from unittest.mock import MagicMock, patch

    from agents import query_agent as qa
    from config import get_settings

    monkeypatch.setattr(get_settings(), "ENABLE_ENTITY_RESOLVER", True, raising=False)
    llm = MagicMock()
    llm.invoke.return_value = MagicMock(content="ok")
    turn = MagicMock()
    with ExitStack() as stack:
        for target in (
            patch.object(qa, "get_llm", return_value=llm),
            patch.object(qa, "build_llm", return_value=llm),
            patch.object(qa, "classify_query", return_value="CHAT"),
            patch.object(qa, "query_invoice_chunks", return_value=[]),
            patch.object(qa, "get_cached_answer", return_value=None),
            patch.object(qa, "set_cached_answer"),
            patch.object(qa, "_get_tenant_stats_summary", return_value=""),
            patch.object(qa, "chat_rules_version", return_value="none"),
            patch.object(qa, "get_chat_history", return_value=""),
            patch.object(qa, "update_session_focus"),
        ):
            stack.enter_context(target)
        return qa._run_query_agent(
            session_id=str(uuid4()), user_message=message, tenant_id=str(tenant),
            db_session=pg_session, turn=turn,
        ), llm, turn


def test_with_the_flag_on_an_unknown_invoice_stops_the_turn_with_a_clarify_card(pg_session, tenant, monkeypatch):
    _seed(pg_session, tenant, "INV-2026-0042")
    result, llm, turn = _run_turn(pg_session, tenant, "what is due on INV-2026-0043", monkeypatch)
    assert result["entity_clarification"]["entities"][0]["status"] == "suggested"
    assert "Did you mean INV-2026-0042" in result["content"]
    assert result["result_invoice_ids"] == []
    assert turn.stop_reason == "awaiting_entity_clarification"
    llm.invoke.assert_not_called()  # no model was consulted (hard rule 3)


def test_with_the_flag_on_a_bound_invoice_goes_through_to_the_route(pg_session, tenant, monkeypatch):
    inv = _seed(pg_session, tenant, "INV-2026-0042")
    result, llm, turn = _run_turn(pg_session, tenant, "what is due on INV-2026-0042", monkeypatch)
    assert "entity_clarification" not in result
    assert str(inv.id) in result["result_invoice_ids"]
