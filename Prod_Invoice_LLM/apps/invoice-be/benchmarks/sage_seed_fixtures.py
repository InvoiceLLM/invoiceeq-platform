"""SQLite seed data shared by the chat-eval harness and its manual live-run CLI.

Extracted from `tests/run_agentic_sage_live.py` on 2026-08-23 so it ships inside
the deployed image (see `benchmarks/__init__.py`). `tests/run_agentic_sage_live.py`
keeps its own `QUESTIONS`/`run_once()`/`main()` — the manual exploratory CLI that
is not needed by the scheduled job — and imports `TENANT_ID`/`_TENANT_STATS`/
`_ROWS`/`_CHUNKS`/`_seed` back from here so both callers stay on one copy of the
fixture data, not two that can drift.

Only `_seed` and its inputs are what `scripts/run_agent_eval.py` and
`benchmarks/agent_eval_golden_sample.py` actually import.
"""
from __future__ import annotations

import json
from uuid import uuid4

from sqlmodel import text

TENANT_ID = "00000000-0000-0000-0000-000000000000"

_TENANT_STATS = (
    "Tenant Data Snapshot (orientation only - always run a live query for exact figures): "
    "7 total invoices, total spend per currency: USD 96,420.00; INR 118,000.00 "
    "(never add or compare amounts across different currencies - no exchange rate is "
    "available; always state the currency alongside any amount), 7 distinct vendors, "
    "dates 2026-06-01 to 2026-07-22, status breakdown: COMPLETED: 6, AUDIT_REQUIRED: 1."
)

# Every row is a real counterparty from this repo's own incident history.
_ROWS = [
    # Gap 270: a real INBOUND vendor the pipeline reported as "not found" after
    # guessing OUTBOUND and filtering customer_name.
    dict(
        vendor_name="Titan Steel Distributors", customer_name=None, flow_direction="INBOUND",
        invoice_number="TSD-620458", grand_total=18450.00, tax_amount=1476.00, currency="USD",
        invoice_date="2026-07-02", due_date="2026-08-01", status="COMPLETED", items="[]",
    ),
    dict(
        vendor_name="Redwood Facilities Group", customer_name=None, flow_direction="INBOUND",
        invoice_number="RFG-2026-114", grand_total=7325.50, tax_amount=586.04, currency="USD",
        invoice_date="2026-06-18", due_date="2026-07-18", status="COMPLETED", items="[]",
    ),
    # Gaps 263/264: the CGST question. One combined tax_amount, no breakdown.
    dict(
        vendor_name="Rajesh Steel", customer_name=None, flow_direction="INBOUND",
        invoice_number="INDIA-20260722-003", grand_total=118000.00, tax_amount=18000.00,
        currency="INR", invoice_date="2026-07-22", due_date="2026-08-21", status="COMPLETED",
        items="[]",
    ),
    # Gap 268: the LIMIT 1 comparison that silently truncated the loser.
    dict(
        vendor_name="DataPipe Solutions", customer_name=None, flow_direction="INBOUND",
        invoice_number="DPS-9981", grand_total=42300.00, tax_amount=3384.00, currency="USD",
        invoice_date="2026-06-30", due_date="2026-07-30", status="COMPLETED", items="[]",
    ),
    dict(
        vendor_name="StratEdge Partners", customer_name=None, flow_direction="INBOUND",
        invoice_number="SEP-4410", grand_total=27950.00, tax_amount=2236.00, currency="USD",
        invoice_date="2026-06-27", due_date="2026-07-27", status="COMPLETED", items="[]",
    ),
    # Gap 271: freight per vendor -- the whole-invoice-total answer that came
    # back 10-40x too large.
    dict(
        vendor_name="Blue Ridge Logistics", customer_name=None, flow_direction="INBOUND",
        invoice_number="BRL-7702", grand_total=6120.00, tax_amount=489.60, currency="USD",
        invoice_date="2026-07-05", due_date="2026-08-04", status="COMPLETED",
        items=json.dumps(
            [
                {"description": "Freight and handling", "quantity": 4, "unit_price": 280.00, "amount": 1120.00},
                {"description": "Warehouse storage", "quantity": 1, "unit_price": 5000.00, "amount": 5000.00},
            ]
        ),
    ),
    # Gap 269: the false equation. 5000 x 0.08 is 400.00, the invoice prints 420.00.
    dict(
        vendor_name="Harbor Tech", customer_name=None, flow_direction="INBOUND",
        invoice_number="US-20260722-001", grand_total=420.00, tax_amount=0.00, currency="USD",
        invoice_date="2026-06-01", due_date="2026-07-01", status="AUDIT_REQUIRED",
        items=json.dumps(
            [{"description": "Bolts", "quantity": 5000, "unit_price": 0.08, "amount": 420.00}]
        ),
    ),
]

_CHUNKS = [
    {
        "id": "chunk-brl-1",
        "document": (
            "Blue Ridge Logistics - Invoice BRL-7702. Freight and handling, 4 shipments at "
            "USD 280.00 each. Payment terms: net 30 from invoice date."
        ),
        "distance": 0.18,
        "matched_by": "semantic",
        "metadata": {"invoice_id": None, "vendor_name": "Blue Ridge Logistics", "page": 1},
    },
    {
        "id": "chunk-tsd-1",
        "document": (
            "Titan Steel Distributors - Invoice TSD-620458. Structural steel supply. "
            "Remit within 30 days. Late payments subject to 1.5% monthly interest."
        ),
        "distance": 0.24,
        "matched_by": "semantic",
        "metadata": {"invoice_id": None, "vendor_name": "Titan Steel Distributors", "page": 1},
    },
]


# Columns a fixture row may leave out, with the value used when it does. Added
# 2026-08-24 alongside `benchmarks/region_seed_fixtures.py`, whose India/US/EU
# rows need three columns the seven incident-history rows never set: `po_number`
# (a real, queryable column the SQL prompt already exposes), `subtotal` (not in
# the SQL prompt's schema, but the agentic path's `get_full_record` dumps the ORM
# row, so seeding it keeps that record faithful to the source document), and
# `sa_alerts` (the audit trail a "which invoices are flagged" question reads).
# Defaults, not a second INSERT statement: two insert paths for one table is the
# drift this module was extracted to prevent.
_ROW_DEFAULTS = {
    "customer_name": None,
    "flow_direction": "INBOUND",
    "due_date": None,
    "po_number": None,
    "subtotal": None,
    "status": "COMPLETED",
    "items": "[]",
    "tags": "[]",
    "sa_alerts": "[]",
}


def _seed(session, rows=None, tenant_id: str = TENANT_ID) -> dict:
    """Insert the fixture rows and hand back `{invoice_number: id}`.

    `rows` defaults to the seven incident-history invoices. It is a parameter
    because `scripts/run_agent_eval.py` seeds those *plus* the large/small
    document-length pair from `benchmarks/large_invoice_fixture.py`, and needs
    the generated ids to attach page chunks to the right invoice.

    `tenant_id` defaults to the base fixture tenant. It is a parameter because
    the same script now also seeds three regional tenants
    (`benchmarks/region_seed_fixtures.py`) into the same SQLite database — each
    under its own id, so a case bound to one of them cannot see the others'
    rows. Every generated query is tenant-scoped and `execute_generated_sql`
    rejects a query that is not, so that isolation is the product's own, not
    something this fixture has to arrange.
    """
    seeded: dict = {}
    for row in rows if rows is not None else _ROWS:
        invoice_id = uuid4().hex
        seeded[row["invoice_number"]] = invoice_id
        session.execute(
            text(
                "INSERT INTO invoice (id, tenant_id, file_path, vendor_name, customer_name, "
                "flow_direction, invoice_number, subtotal, grand_total, tax_amount, currency, "
                "invoice_date, due_date, po_number, status, items, tags, sa_alerts, created_at, "
                "processing_attempts) "
                "VALUES (:id, :tenant_id, :file_path, :vendor_name, :customer_name, :flow_direction, "
                ":invoice_number, :subtotal, :grand_total, :tax_amount, :currency, :invoice_date, "
                ":due_date, :po_number, :status, :items, :tags, :sa_alerts, "
                "'2026-07-22 00:00:00', 0)"
            ),
            {
                "id": invoice_id,
                # Dashed on purpose -- see run_agentic_sage_live.py's docstring.
                "tenant_id": tenant_id,
                "file_path": f"seed/{row['invoice_number']}.pdf",
                **_ROW_DEFAULTS,
                **row,
            },
        )
    session.commit()
    return seeded
