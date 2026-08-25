"""Per-tool unit tests for `agents/query_tools.py`.

Scope narrowed by Gap 316 (2026-08-25), which deleted `agents/sage_orchestrator.py`
and the four tools only it called (`identify_invoices`, `search_invoices`,
`aggregate`, `ask_clarifying_question`) along with their tests. What is left
covers the two functions Feature 6's chat route genuinely depends on:
`get_full_record` (Gap 310) and `compute` (Gap 315).

Neither contains an LLM call, so these tests are exhaustive over the behaviour
that matters rather than indicative — which is the point of moving "fetch the
whole row" and "add these numbers" out of prose and into functions.

Question phrasings below are the real historical ones from this repo's own
tracker, not invented: rule 6d's Rajesh Steel CGST case (Gaps 263/264) and the
5000 x 0.08 = 420.00 false equation (Gap 269).
"""
import os
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

os.environ["MOCK_EMBEDDINGS"] = "true"

from dependencies import MOCK_TENANT_ID
from models import Invoice
from agents.query_tools import (
    FULL_RECORD_EXCLUDED_COLUMNS,
    MAX_FULL_RECORD_CHUNK_CHARS,
    bound_document_pages,
    compute,
    get_full_record,
)

sqlite_url = "sqlite:///:memory:"
engine = create_engine(sqlite_url, connect_args={"check_same_thread": False}, poolclass=StaticPool)


@pytest.fixture(name="db_session")
def db_session_fixture():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


def _seed_invoice(db_session, **kwargs):
    defaults = dict(
        id=uuid4(),
        tenant_id=MOCK_TENANT_ID,
        file_path="mock/inv.pdf",
        flow_direction="INBOUND",
        status="COMPLETED",
        currency="USD",
    )
    defaults.update(kwargs)
    inv = Invoice(**defaults)
    db_session.add(inv)
    db_session.commit()
    return inv



# ── get_full_record ─────────────────────────────────────────────────────────


def test_full_record_returns_every_business_field_including_the_tax_breakdown(db_session):
    """Gaps 263/264/285 in one test. Nothing curates this row, so the itemized
    `taxes` breakdown, the GSTIN in `tax_ids` and the IRN in
    `compliance_metadata` are all present without any prompt having mentioned
    them."""
    invoice = _seed_invoice(
        db_session,
        vendor_name="Rajesh Steel",
        currency="INR",
        grand_total=118000.0,
        tax_amount=18000.0,
        taxes=[
            {"type": "CGST", "rate": 9, "amount": 9000.0},
            {"type": "SGST", "rate": 9, "amount": 9000.0},
        ],
        tax_ids=[{"type": "GSTIN", "value": "29ABCDE1234F1Z5"}],
        compliance_metadata=[{"type": "IRN", "value": "abc123"}],
        payment_instructions=[{"bank": "HDFC", "account": "0001"}],
        references=[{"type": "PO", "value": "PO-88"}],
    )
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=[]):
        result = get_full_record(str(invoice.id), str(MOCK_TENANT_ID), db_session)

    assert result.status == "ok"
    record = result.record
    assert record["taxes"] == [
        {"type": "CGST", "rate": 9, "amount": 9000.0},
        {"type": "SGST", "rate": 9, "amount": 9000.0},
    ]
    assert record["tax_ids"][0]["value"] == "29ABCDE1234F1Z5"
    assert record["compliance_metadata"][0]["value"] == "abc123"
    assert record["payment_instructions"] and record["references"]
    # And the rest of the row, uncurated.
    for column in ("subtotal", "discount_amount", "deductions", "addresses", "due_date",
                   "status", "flow_direction", "deleted_at"):
        assert column in record


def test_full_record_omits_only_storage_plumbing_and_says_which(db_session):
    """A five-column deviation from the doc's "every column, no curation", made
    visible on every result rather than hidden: none of them is business data,
    and `file_path` is a blob URI that leaked into a chat answer once."""
    invoice = _seed_invoice(db_session, vendor_name="Harbor Tech")
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=[]):
        result = get_full_record(str(invoice.id), str(MOCK_TENANT_ID), db_session)

    for omitted in FULL_RECORD_EXCLUDED_COLUMNS:
        assert omitted not in result.record
    assert result.columns_omitted == list(FULL_RECORD_EXCLUDED_COLUMNS)
    assert "file_path" in result.columns_omitted


def test_full_record_is_json_serializable(db_session):
    """The record goes into a prompt and into a `ToolMessage`; a raw UUID or date
    in it is a crash at the JSON boundary, not a formatting nit."""
    import json
    from datetime import date

    invoice = _seed_invoice(db_session, vendor_name="Harbor Tech", invoice_date=date(2026, 7, 2))
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=[]):
        result = get_full_record(str(invoice.id), str(MOCK_TENANT_ID), db_session)

    payload = json.dumps(result.to_dict())
    assert "2026-07-02" in payload
    assert str(invoice.id) in payload


def test_full_record_pulls_every_page_by_metadata_filter_not_by_search(db_session):
    """Once the invoice is identified, "the page with the tax table didn't rank
    high enough" is silent data loss, not a relevance decision -- so this is a
    direct `invoice_id` filter and every page comes back."""
    invoice = _seed_invoice(db_session, vendor_name="Harbor Tech")
    pages = [
        {"id": f"{invoice.id}_page_{n}", "document": f"page {n} text",
         "metadata": {"invoice_id": str(invoice.id), "page": n, "vendor_name": "Harbor Tech"},
         "matched_by": "invoice_id"}
        for n in (1, 2, 3)
    ]
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=pages) as fetch:
        result = get_full_record(str(invoice.id), str(MOCK_TENANT_ID), db_session)

    fetch.assert_called_once_with(str(invoice.id), str(MOCK_TENANT_ID))
    assert [chunk["page"] for chunk in result.chunks] == [1, 2, 3]
    assert all(chunk["matched_by"] == "invoice_id" for chunk in result.chunks)


def _long_pages(invoice_id, count: int, chars: int = 3_200) -> list[dict]:
    """`count` page chunks of roughly real size (a rendered A4 invoice page of
    line items measured ~3,200 characters, live run 2026-08-21)."""
    return [
        {
            "id": f"{invoice_id}_page_{n}",
            "document": f"[Page {n}]\n" + f"line {n} " * (chars // 8),
            "metadata": {"invoice_id": str(invoice_id), "page": n, "vendor_name": "Meridian"},
            "matched_by": "invoice_id",
        }
        for n in range(1, count + 1)
    ]


def test_a_short_document_is_never_touched_by_the_page_cap(db_session):
    """The cap exists for pathological documents. An ordinary invoice must come
    back whole, with `pages_omitted` empty -- otherwise every answer would carry
    a truncation disclaimer that is not true."""
    invoice = _seed_invoice(db_session, vendor_name="Harbor Tech")
    pages = _long_pages(invoice.id, 3)
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=pages):
        result = get_full_record(str(invoice.id), str(MOCK_TENANT_ID), db_session)

    assert [chunk["page"] for chunk in result.chunks] == [1, 2, 3]
    assert result.pages_omitted == []
    assert result.total_document_pages == 3


def test_a_long_document_is_capped_keeping_the_first_and_last_page(db_session):
    """Measured 2026-08-21: an 11-page invoice's page dump is 16,010 tokens and
    grows linearly, so past `MAX_FULL_RECORD_CHUNK_CHARS` pages are held back.
    The LAST page is kept on purpose -- totals, payment terms and the signature
    block live there, so a plain "first N pages" cap would drop the page most
    detail questions actually need."""
    invoice = _seed_invoice(db_session, vendor_name="Meridian Industrial Supply")
    pages = _long_pages(invoice.id, 11)
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=pages):
        result = get_full_record(str(invoice.id), str(MOCK_TENANT_ID), db_session)

    shown = [chunk["page"] for chunk in result.chunks]
    assert shown == sorted(shown)
    assert shown[0] == 1 and shown[-1] == 11
    assert result.total_document_pages == 11
    assert result.pages_omitted, "an 11-page document of this size must hit the cap"
    assert set(shown) & set(result.pages_omitted) == set()
    assert len(shown) + len(result.pages_omitted) == 11
    total_chars = sum(len(chunk["document"]) for chunk in result.chunks)
    assert total_chars <= MAX_FULL_RECORD_CHUNK_CHARS


def test_the_page_cap_never_empties_a_two_page_document(db_session):
    """Both anchor pages survive even when they alone exceed the budget: an empty
    document block is a worse answer than a long one."""
    invoice = _seed_invoice(db_session, vendor_name="Meridian Industrial Supply")
    pages = _long_pages(invoice.id, 2, chars=MAX_FULL_RECORD_CHUNK_CHARS)
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=pages):
        result = get_full_record(str(invoice.id), str(MOCK_TENANT_ID), db_session)

    assert [chunk["page"] for chunk in result.chunks] == [1, 2]
    assert result.pages_omitted == []


def test_bound_document_pages_orders_by_page_and_tolerates_an_unlabelled_page():
    """Chunks arrive from Chroma in whatever order `collection.get()` returns
    them; page order is imposed here, and a chunk with no page number sorts last
    rather than crashing the comparison."""
    pages = [
        {"page": 3, "document": "c"},
        {"page": None, "document": "d"},
        {"page": 1, "document": "a"},
    ]
    kept, omitted = bound_document_pages(pages)
    assert [chunk["document"] for chunk in kept] == ["a", "c", "d"]
    assert omitted == []


def test_full_record_surfaces_an_audit_flag_as_its_own_signal(db_session):
    """An answer about an amount on a duplicate-flagged invoice should say so
    rather than treating the figure as clean, so the flag is a field on the
    result and not something a reader has to notice inside the record."""
    invoice = _seed_invoice(
        db_session, vendor_name="Harbor Tech", status="AUDIT_REQUIRED",
        sa_alerts=[{"type": "DUPLICATE", "detail": "matches US-20260722-001"}],
    )
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=[]):
        result = get_full_record(str(invoice.id), str(MOCK_TENANT_ID), db_session)

    assert result.has_alerts is True
    assert result.record["sa_alerts"][0]["type"] == "DUPLICATE"


def test_full_record_refuses_another_tenants_invoice_as_not_found(db_session):
    """Not as a distinct error: a caller must not be able to learn that an id
    exists under another tenant."""
    other = _seed_invoice(db_session, tenant_id=uuid4(), vendor_name="Someone Else")
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=[]):
        result = get_full_record(str(other.id), str(MOCK_TENANT_ID), db_session)

    assert result.status == "not_found"
    assert result.record == {}
    assert "Someone Else" not in (result.message or "")


def test_full_record_rejects_a_malformed_id_without_touching_the_database(db_session):
    result = get_full_record("not-a-uuid", str(MOCK_TENANT_ID), db_session)
    assert result.status == "error"
    assert "not a valid invoice id" in result.message


def test_full_record_survives_an_unreachable_document_index(db_session):
    """A Chroma outage degrades the answer to "structured record only"; it does
    not take the turn down."""
    invoice = _seed_invoice(db_session, vendor_name="Harbor Tech")
    with patch("agents.query_tools.get_all_invoice_chunks", return_value=[]):
        result = get_full_record(str(invoice.id), str(MOCK_TENANT_ID), db_session)

    assert result.status == "ok"
    assert result.chunks == []


# ── compute: per-currency arithmetic ────────────────────────────────────────


def test_compute_sums_amounts_within_one_currency():
    result = compute("sum_by_currency", [
        {"amount": 1200.00, "currency": "USD"},
        {"amount": 250.00, "currency": "USD"},
        {"amount": 2000.00, "currency": "USD"},
    ])

    assert result.status == "ok"
    assert result.by_currency == {"USD": 3450.00}
    assert result.counts == {"USD": 3}
    assert result.formatted == ["USD 3,450.00"]


def test_compute_never_combines_different_currencies():
    """The same rule the SQL summary prompt states in prose ('never one total
    added across different currencies -- no exchange rate is available'), made
    structural: there is no field on the result that could hold a combined
    total, so no caller can produce one by mistake."""
    result = compute("sum_by_currency", [
        {"amount": 100.00, "currency": "USD"},
        {"amount": 5000.00, "currency": "INR"},
        {"amount": 40.00, "currency": "EUR"},
        {"amount": 25.00, "currency": "usd"},  # casing must not fork the bucket
    ])

    assert result.status == "ok"
    assert result.by_currency == {"EUR": 40.00, "INR": 5000.00, "USD": 125.00}
    assert 5165.00 not in result.by_currency.values()
    assert "no exchange rate is available" in result.note
    assert not hasattr(result, "total")


def test_compute_puts_an_unlabelled_amount_in_its_own_bucket_not_usd():
    """A missing currency is a fact about the data, not an invitation to assume
    dollars -- assuming it is exactly the kind of confident wrong financial claim
    this feature exists to make harder."""
    result = compute("sum_by_currency", [
        {"amount": 10.00, "currency": "USD"},
        {"amount": 90.00, "currency": None},
        {"amount": 5.00},
    ])

    assert result.by_currency == {"UNKNOWN": 95.00, "USD": 10.00}


def test_compute_accepts_plain_amount_currency_pairs():
    result = compute("sum_by_currency", [(732.57, "USD"), (29302.94, "USD")])
    assert result.by_currency == {"USD": 30035.51}


def test_compute_does_not_reintroduce_float_noise():
    """Gaps 266/272 were both this symptom rendered into chat (7.249887640449439,
    5436.3099999999995). Decimal-via-str arithmetic, quantized to this
    codebase's existing 2dp currency precision."""
    result = compute("sum_by_currency", [
        {"amount": 0.1, "currency": "USD"},
        {"amount": 0.2, "currency": "USD"},
        {"amount": 5436.3099999999995, "currency": "USD"},
    ])

    assert result.by_currency == {"USD": 5436.61}
    assert result.formatted == ["USD 5,436.61"]


def test_compute_reads_amounts_as_rendered_in_a_results_table():
    result = compute("sum_by_currency", [
        {"amount": "1,200.50", "currency": "USD"},
        {"amount": "$99.50", "currency": "USD"},
    ])
    assert result.by_currency == {"USD": 1300.00}


def test_compute_errors_rather_than_silently_dropping_a_bad_amount():
    result = compute("sum_by_currency", [
        {"amount": 100.00, "currency": "USD"},
        {"amount": "not a number", "currency": "USD"},
    ])

    assert result.status == "error"
    assert "index 1" in result.message
    assert result.by_currency == {}


def test_compute_rejects_an_unknown_operation():
    result = compute("average_by_vendor", [{"amount": 1, "currency": "USD"}])
    assert result.status == "error"
    assert "sum_by_currency" in result.message


# ── compute: the reconciliation-mismatch shape ──────────────────────────────


def test_compute_flags_the_historical_false_equation_case():
    """Gap 269 (US tenant test, Q4 and Q10): the reply stated '5000.00 units x
    USD 0.08 = USD 420.00' -- false, since 5000 x 0.08 is 400.00. The summary
    prompt's 'EXCEPTION -- reconciliation/mismatch questions' paragraph asks the
    model not to do that. Here the equation simply cannot be produced: both
    figures come back separately, with the mismatch named."""
    result = compute("reconcile_line_items", [
        {
            "description": "Steel bolts",
            "quantity": 5000.00,
            "unit_price": 0.08,
            "amount": 420.00,
            "currency": "USD",
        }
    ])

    assert result.status == "ok"
    row = result.rows[0]
    assert row["computed_amount"] == 400.00
    assert row["stated_amount"] == 420.00
    assert row["matches"] is False
    assert row["difference"] == 20.00
    assert result.all_match is False
    assert result.mismatches == [row]
    assert "mismatch" in result.formatted[0]
    assert "= USD 420.00" not in result.formatted[0]  # the false equation is unrenderable


def test_compute_uses_the_plain_equation_when_a_line_actually_reconciles():
    result = compute("reconcile_line_items", [
        {
            "description": "Training & Onboarding",
            "quantity": 40,
            "unit_price": 732.57,
            "amount": 29302.80,
            "currency": "USD",
        }
    ])

    row = result.rows[0]
    assert row["matches"] is True
    assert row["difference"] == 0.0
    assert result.all_match is True
    assert result.mismatches == []
    assert result.formatted[0] == "Training & Onboarding: 40 x USD 732.57 = USD 29,302.80"


def test_compute_reconciles_a_mixed_batch_and_keeps_each_rows_own_currency():
    result = compute("reconcile_line_items", [
        {"description": "Onboarding pack", "quantity": 2, "unit_price": 50.00, "amount": 100.00, "currency": "INR"},
        {"description": "Steel bolts", "quantity": 5000, "unit_price": 0.08, "amount": 420.00, "currency": "USD"},
    ])

    assert result.all_match is False
    assert [row["currency"] for row in result.rows] == ["INR", "USD"]
    assert [row["matches"] for row in result.rows] == [True, False]
    assert len(result.mismatches) == 1


def test_compute_reconcile_errors_on_a_missing_field():
    result = compute("reconcile_line_items", [{"description": "Steel bolts", "quantity": 5000}])
    assert result.status == "error"
    assert "index 0" in result.message


# ── the Feature 6 boundary ──────────────────────────────────────────────────


def test_the_default_chat_route_reuses_these_two_functions():
    """Reuse, asserted — not a second copy beside the caller.

    Before Gap 316 this test policed a flag boundary: the six tools were reachable
    only through `ENABLE_AGENTIC_SAGE`, with `get_full_record` (Gap 310) and then
    `compute` (Gap 315) narrowed out as deliberate exceptions on one criterion —
    no LLM call, no SQL generation, no orchestration decision. The flag and the
    other four tools are gone; what the exceptions were protecting is not. Two
    copies of one tenant check is how a bypass path gets built by accident, and
    two copies of one summation is how an arithmetic rule drifts, so this fails if
    either call site is ever quietly reimplemented in `query_agent`.
    """
    import ast
    import inspect

    from agents import query_agent

    tree = ast.parse(inspect.getsource(query_agent))
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)

    assert "get_full_record" in called
    assert "compute" in called
    # And nothing that plans, generates SQL or loops came back with them.
    for gone in ("identify_invoices", "search_invoices", "aggregate",
                 "ask_clarifying_question", "run_agentic_sage"):
        assert gone not in called, f"{gone} was deleted by Gap 316 but is called again"
