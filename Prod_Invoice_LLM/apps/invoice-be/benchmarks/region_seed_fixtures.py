"""The India / US / EU regional tenants, ported into the shipped benchmark fixture set.

Where this comes from, and why it had to be re-seeded rather than reused
-----------------------------------------------------------------------
`tests/{india,us,eu}/chat_question_bank.md` are this repo's only genuinely
answer-bearing question banks: question + ground-truth answer + a grading rubric,
with every figure computed from the matching `ground_truth_line_items.md` and
`tests/_extraction_data.json` (which is where each invoice's expected
status/alert type below comes from — it is not invented here). Until now none of
that material could reach the nightly benchmark job for two separate reasons,
both stated in `agent_eval_golden_sample.py`'s own docstring:

  1. every one of those banks was written against its region's tenant seeded into
     a **live Postgres with real Chroma embeddings** (see
     `tests/us/run_chat_live_test.py`), and no local Postgres/Chroma is running;
  2. `.dockerignore` excludes `**/tests/` from the deployed image, so nothing
     under `tests/` can ship or run in `caj-benchmark-eval-dev` at all.

This module fixes (2) by living in `benchmarks/`, and works around (1) by
re-seeding the same nine invoices per region as ordinary `invoice` rows in the
harness's in-memory SQLite, with the handful of facts that only ever existed in
the PDF's prose (a resale-exemption certificate number, an RCM footer, a
"quoted in USD, invoiced in EUR" note) carried as fixed document chunks in the
same shape `sage_seed_fixtures._CHUNKS` already uses. No embeddings are computed
for those — `scripts/run_agent_eval.py` patches `query_invoice_chunks` to return
this fixed list, exactly as it already did for the base tenant, which is why
`MOCK_EMBEDDINGS=true` remains sufficient.

Three tenants, not one, and that is the load-bearing decision here
------------------------------------------------------------------
These rows are **not** added to `sage_seed_fixtures._ROWS`. They are seeded under
their own tenant ids and every ported case declares which tenant it runs against
(`GoldenCase.tenant_id`). Merging them into the base tenant would have silently
falsified the existing twenty cases rather than extended them:

  * `freight_per_vendor`'s reference answer states "no other seeded vendor has a
    freight/delivery/shipping line" — the US tenant has three;
  * `zero_result_with_useful_redirect`'s states "no invoice at all is dated in
    May 2026" — India's IEQ-IN-7003 is 2026-05-20 and US's IEQ-US-9003 is
    2026-05-15;
  * `titan_steel_payment_status`, `line_item_breakdown_completeness` and
    `two_vendors_two_questions` all name a vendor the US tenant *also* has, with
    a different invoice number and a different total (US's Titan Steel invoice is
    also numbered TSD-620458 but totals USD 10,557.60, not USD 18,450.00).

Tenant isolation is the product's own boundary — every generated query carries
`tenant_id = '<id>'` (enforced, not requested: `execute_generated_sql`'s Safety
Check 3 rejects a query without it) — so one SQLite database can hold all four
tenants without any of them being visible to another's turn.

What is deliberately NOT here
-----------------------------
  * **Multi-turn follow-ups** (India Q7/Q12, US Q7/Q12, EU Q7/Q13, and the
    `realworld_tenant` bank's Q9/Q11/Q15/Q21). Every one resolves a pronoun
    against the previous turn ("of those three...", "and what about..."), and the
    harness runs each case as a single turn under a fresh `session_id` with no
    prior `ChatMessage` rows, so the conversation history the SQL prompt renders
    is empty. Rewriting them as self-contained questions was rejected: it would
    delete the only property they test.
  * **CGST/SGST split questions** (India's flag 4, PE-2026-0512's uneven
    Rs 2,000.00 / Rs 3,700.00 split). ~~The `invoice` table has one combined
    `tax_amount` and no tax-component column at all — the schema limitation is
    itself already the subject of the existing `rajesh_steel_cgst` case, and
    seeding a fake breakdown to make the question answerable would test a schema
    this product does not have.~~

    **That rationale is obsolete as of Gap 310 (2026-08-24) and is struck through
    rather than deleted, because it was wrong in an instructive way.** There was
    never a schema limitation: `Invoice.taxes` is a JSONB column that extraction
    has populated on every invoice for a long time (`queue_worker/handlers.py`),
    carrying one entry per component with its own `tax_type`/`rate_percent`/
    `amount`. What actually existed was a *prompt* limitation — the default chat
    route's hand-typed ~19-column schema block never listed `taxes`, and its
    tax-term note asserted outright that "this schema has no breakdown by tax
    type". The route now hands the identified invoice's whole ORM row to its
    answering step (`query_agent._full_record_block_for`), so a CGST/SGST split
    question is answerable here too, and seeding PE-2026-0512's real uneven split
    into `taxes` would be seeding ground truth, not a fake. Deliberately not done
    in the Gap 310 pass to keep it scoped: `rajesh_steel_cgst` already exercises
    the mechanism end to end. Adding a regional case is now a fixture edit
    (`taxes=` on the row) plus a `GoldenCase`, with no product change behind it.
  * **GSTIN / VAT-ID presence questions** (India Q7, EU Q7). Same shape of
    caveat: `tax_ids` is likewise a real, populated, previously-invisible column
    now included in the full record — the remaining reason these are absent is
    only that no regional row here seeds one.
  * Questions whose incident is already covered by an existing case — US Q4
    (Apex Print's 5,000 x $0.08 = $420) is literally the same arithmetic as the
    base tenant's `bolts_reconciliation`, and US Q8/India Q9 are the same
    two-entity comparison shape as `datapipe_vs_stratedge`.
"""
from __future__ import annotations

import json

INDIA_TENANT_ID = "11111111-1111-1111-1111-111111111111"
US_TENANT_ID = "22222222-2222-2222-2222-222222222222"
EU_TENANT_ID = "33333333-3333-3333-3333-333333333333"


def _items(*lines) -> str:
    """`(description, quantity, unit_price, amount)` tuples -> the `items` JSON.

    Four keys and no more, because that is the shape rule 6d's un-nesting SQL
    reads (`item.value ->> 'description' | 'quantity' | 'unit_price' | 'amount'`,
    `agents/query_agent.py::_LINE_ITEM_RULE_SQLITE`). Per-line GST/VAT rates
    therefore ride **inside the description string**, which is where they are
    printed on the source PDFs' line rows anyway — there is no per-line tax
    field in this schema to put them in.
    """
    return json.dumps(
        [
            {
                "description": description,
                "quantity": quantity,
                "unit_price": unit_price,
                "amount": amount,
            }
            for description, quantity, unit_price, amount in lines
        ]
    )


def _alerts(*pairs) -> str:
    """`(type, message)` tuples -> the `sa_alerts` JSON, in the shape the product
    writes it (`services/invoice_reconciliation.py`: `{"type": ..., "message": ...}`).

    Alert *types* are taken from `tests/_extraction_data.json`'s "Expected Alert
    Type" / "Actual Alert Type" columns for that exact invoice id, not chosen
    here, so a question about flagged invoices is graded against what this
    pipeline really produced for those documents.
    """
    return json.dumps([{"type": alert_type, "message": message} for alert_type, message in pairs])


# ---------------------------------------------------------------------------
# India — Infinevo Cloud Pvt Ltd (Gurugram, GSTIN 06AABCI5678F1Z9), INR
# ---------------------------------------------------------------------------
# 6 inbound + 3 outbound, from tests/india/ground_truth_line_items.md. `due_date`
# is None on every row and that is ground truth, not an omission: "No due-date
# field appears on any of the 9 India invoices" — it is what makes Q14's
# honest-refusal case a real test rather than a lookup.
INDIA_ROWS = [
    dict(
        vendor_name="Sharma Traders", customer_name=None, flow_direction="INBOUND",
        invoice_number="ST-2026-0771", subtotal=35000.00, grand_total=41300.00,
        tax_amount=6300.00, currency="INR", invoice_date="2026-06-04", due_date=None,
        po_number=None, status="COMPLETED",
        items=_items(("Office chairs", 10, 3500.00, 35000.00)),
    ),
    dict(
        vendor_name="Bharat Logistics Pvt Ltd", customer_name=None, flow_direction="INBOUND",
        invoice_number="BL-2026-1450", subtotal=13500.00, grand_total=14510.00,
        tax_amount=1010.00, currency="INR", invoice_date="2026-06-11", due_date=None,
        po_number="PO-IN-3301", status="COMPLETED",
        items=_items(
            ("Transport service (GST 5%)", 1, 10000.00, 10000.00),
            ("Packing material (GST 12%)", 1, 2000.00, 2000.00),
            ("Handling and admin (GST 18%)", 1, 1500.00, 1500.00),
        ),
    ),
    dict(
        vendor_name="Konkan Exports Pvt Ltd", customer_name=None, flow_direction="INBOUND",
        invoice_number="KE-2026-0089", subtotal=45000.00, grand_total=53100.00,
        tax_amount=8100.00, currency="INR", invoice_date="2026-06-16", due_date=None,
        po_number="PO-IN-4410", status="COMPLETED",
        items=_items(
            ("Consulting services (import, Reverse Charge Mechanism / RCM applicable)",
             1, 50000.00, 50000.00),
            ("Credit note adjustment CN-2026-0091", 1, -5000.00, -5000.00),
        ),
    ),
    dict(
        vendor_name="Ganesh Hardware Store", customer_name=None, flow_direction="INBOUND",
        invoice_number="GHS-2026-0334", subtotal=39000.00, grand_total=46020.00,
        tax_amount=7020.00, currency="INR", invoice_date="2026-06-06", due_date=None,
        po_number=None, status="AUDIT_REQUIRED",
        items=_items(("Cement bags (100 qty)", 100, 380.00, 39000.00)),
        sa_alerts=_alerts(
            (
                "line_item_calculation_mismatch",
                "Line 'Cement bags (100 qty)' prints INR 39,000.00 but quantity 100 x unit "
                "price INR 380.00 is INR 38,000.00. The printed subtotal and the 18% GST of "
                "INR 7,020.00 both key off the higher figure.",
            ),
        ),
    ),
    dict(
        vendor_name="Patel Enterprises", customer_name=None, flow_direction="INBOUND",
        invoice_number="PE-2026-0512", subtotal=30000.00, grand_total=35700.00,
        tax_amount=5700.00, currency="INR", invoice_date="2026-06-19", due_date=None,
        po_number="PO-IN-2207", status="AUDIT_REQUIRED",
        items=_items(
            ("Raw materials", 1, 25000.00, 25000.00),
            ("Processing charges", 1, 5000.00, 5000.00),
        ),
        sa_alerts=_alerts(
            (
                "tax_amount_not_verified_in_source",
                "Vendor letterhead prints no GSTIN, and the CGST/SGST split on the face of the "
                "document is uneven; the two components still sum to the recorded INR 5,700.00.",
            ),
        ),
    ),
    dict(
        vendor_name="Deccan Chemicals Ltd", customer_name=None, flow_direction="INBOUND",
        invoice_number="DC-2026-1120", subtotal=21850.00, grand_total=25783.00,
        tax_amount=3933.00, currency="INR", invoice_date="2026-06-23", due_date=None,
        po_number="PO-IN-5502", status="AUDIT_REQUIRED",
        items=_items(
            ("Industrial solvents", 200, 85.00, 17000.00),
            ("Catalysts", 10, 450.00, 4050.00),
            ("Packaging", 1, 800.00, 800.00),
        ),
        sa_alerts=_alerts(
            (
                "line_item_calculation_mismatch",
                "Line 'Catalysts' prints INR 4,050.00 but quantity 10 x unit price INR 450.00 "
                "is INR 4,500.00. Subtotal, GST and total are self-consistent with the printed "
                "line, so only a per-line check catches it.",
            ),
        ),
    ),
    dict(
        vendor_name=None, customer_name="Vikram Retail Chain", flow_direction="OUTBOUND",
        invoice_number="IEQ-IN-7001", subtotal=180000.00, grand_total=212400.00,
        tax_amount=32400.00, currency="INR", invoice_date="2026-06-26", due_date=None,
        po_number=None, status="SENT",
        items=_items(("Software licensing - Q3", 1, 180000.00, 180000.00)),
    ),
    dict(
        vendor_name=None, customer_name="Anand Distributors", flow_direction="OUTBOUND",
        invoice_number="IEQ-IN-7002", subtotal=95000.00, grand_total=112100.00,
        tax_amount=17100.00, currency="INR", invoice_date="2026-06-28", due_date=None,
        po_number=None, status="NEEDS_REVIEW",
        items=_items(("Implementation and training", 1, 90000.00, 95000.00)),
        sa_alerts=_alerts(
            (
                "subtotal_mismatch",
                "Line 'Implementation and training' prints INR 95,000.00 but quantity 1 x unit "
                "price INR 90,000.00 is INR 90,000.00.",
            ),
        ),
    ),
    dict(
        vendor_name=None, customer_name="Kavya Enterprises", flow_direction="OUTBOUND",
        invoice_number="IEQ-IN-7003", subtotal=150000.00, grand_total=177000.00,
        tax_amount=27000.00, currency="INR", invoice_date="2026-05-20", due_date=None,
        po_number=None, status="PAID",
        items=_items(("Annual maintenance contract", 1, 150000.00, 150000.00)),
    ),
]

INDIA_CHUNKS = [
    {
        "id": "chunk-ke-1",
        "document": (
            "Konkan Exports Pvt Ltd - Invoice KE-2026-0089. Consulting services (import). "
            "Reverse Charge Mechanism applies: GST shown below is informational only and is "
            "NOT added to the payable total. Subtotal Rs 45,000.00, GST 18% Rs 8,100.00, "
            "Total Rs 53,100.00."
        ),
        "distance": 0.19,
        "matched_by": "semantic",
        "metadata": {"invoice_id": None, "vendor_name": "Konkan Exports Pvt Ltd", "page": 1},
    },
    {
        "id": "chunk-ghs-1",
        "document": (
            "Ganesh Hardware Store - Invoice GHS-2026-0334. Cement bags (100 qty), Qty 100, "
            "Unit Price Rs 380.00, Amount Rs 39,000.00. Subtotal Rs 39,000.00, CGST 9% + "
            "SGST 9% Rs 7,020.00, Total Rs 46,020.00."
        ),
        "distance": 0.26,
        "matched_by": "semantic",
        "metadata": {"invoice_id": None, "vendor_name": "Ganesh Hardware Store", "page": 1},
    },
]


# ---------------------------------------------------------------------------
# US — Infinevo Cloud Inc. (Austin, TX), USD
# ---------------------------------------------------------------------------
# Three vendor names here collide with the base tenant's incident-history rows
# (Blue Ridge Logistics, Titan Steel Distributors, Redwood Facilities Group) with
# different invoice numbers and totals. That collision is the reason these rows
# are in their own tenant — see the module docstring.
US_ROWS = [
    dict(
        vendor_name="Summit Office Supplies", customer_name=None, flow_direction="INBOUND",
        invoice_number="SOS-100442", subtotal=450.00, grand_total=450.00,
        tax_amount=0.00, currency="USD", invoice_date="2026-06-03", due_date=None,
        po_number=None, status="COMPLETED",
        items=_items(("Laptop stands", 10, 45.00, 450.00)),
    ),
    dict(
        vendor_name="Blue Ridge Logistics", customer_name=None, flow_direction="INBOUND",
        invoice_number="BRL-200981", subtotal=2225.00, grand_total=2386.31,
        tax_amount=161.31, currency="USD", invoice_date="2026-06-10", due_date=None,
        po_number="PO-55021", status="COMPLETED",
        items=_items(
            ("Freight service", 1, 2000.00, 2000.00),
            ("Fuel surcharge", 1, 150.00, 150.00),
            ("Handling fee", 1, 75.00, 75.00),
        ),
    ),
    dict(
        vendor_name="Cascade Manufacturing Co", customer_name=None, flow_direction="INBOUND",
        invoice_number="CMC-330217", subtotal=2600.00, grand_total=2600.00,
        tax_amount=0.00, currency="USD", invoice_date="2026-06-14", due_date=None,
        po_number="PO-88342", status="COMPLETED",
        items=_items(
            ("CNC machined parts", 50, 28.00, 1400.00),
            ("Custom tooling", 2, 500.00, 1000.00),
            ("Freight", 1, 200.00, 200.00),
        ),
    ),
    dict(
        vendor_name="Apex Print Solutions", customer_name=None, flow_direction="INBOUND",
        invoice_number="APS-410093", subtotal=420.00, grand_total=453.60,
        tax_amount=33.60, currency="USD", invoice_date="2026-06-05", due_date=None,
        po_number=None, status="AUDIT_REQUIRED",
        items=_items(("Business cards (5,000 qty)", 5000, 0.08, 420.00)),
        sa_alerts=_alerts(
            (
                "line_item_calculation_mismatch",
                "Line 'Business cards (5,000 qty)' prints USD 420.00 but quantity 5000 x unit "
                "price USD 0.08 is USD 400.00. The printed subtotal and the 8% sales tax of "
                "USD 33.60 both key off the higher figure.",
            ),
        ),
    ),
    dict(
        vendor_name="Redwood Facilities Group", customer_name=None, flow_direction="INBOUND",
        invoice_number="RFG-500712", subtotal=1500.00, grand_total=1590.00,
        tax_amount=90.00, currency="USD", invoice_date="2026-06-18", due_date=None,
        po_number="PO-61190", status="AUDIT_REQUIRED",
        items=_items(
            ("Janitorial services", 1, 1200.00, 1200.00),
            ("Supplies", 1, 300.00, 300.00),
        ),
        sa_alerts=_alerts(
            (
                "tax_calculation_mismatch",
                "Line items and the USD 1,500.00 subtotal both reconcile, but sales tax prints "
                "as a flat USD 90.00 with no rate shown; a plausible 8.25% would be USD 123.75. "
                "The defect is in the tax figure itself, not the lines.",
            ),
        ),
    ),
    dict(
        vendor_name="Titan Steel Distributors", customer_name=None, flow_direction="INBOUND",
        invoice_number="TSD-620458", subtotal=9960.00, grand_total=10557.60,
        tax_amount=597.60, currency="USD", invoice_date="2026-06-22", due_date=None,
        po_number="PO-71004", status="AUDIT_REQUIRED",
        items=_items(
            ("Steel beams", 20, 310.00, 6200.00),
            ("Steel plates", 15, 210.00, 3510.00),
            ("Delivery", 1, 250.00, 250.00),
        ),
        sa_alerts=_alerts(
            (
                "line_item_calculation_mismatch",
                "Line 'Steel plates' prints USD 3,510.00 but quantity 15 x unit price USD "
                "210.00 is USD 3,150.00. Subtotal, tax and total are self-consistent with the "
                "printed line, so only a per-line check catches it.",
            ),
        ),
    ),
    dict(
        vendor_name=None, customer_name="NorthPoint Retail Inc.", flow_direction="OUTBOUND",
        invoice_number="IEQ-US-9001", subtotal=2500.00, grand_total=2500.00,
        tax_amount=0.00, currency="USD", invoice_date="2026-06-25", due_date=None,
        po_number=None, status="SENT",
        items=_items(("SaaS subscription - Enterprise tier (1 mo)", 1, 2500.00, 2500.00)),
    ),
    dict(
        vendor_name=None, customer_name="Fieldstone Analytics LLC", flow_direction="OUTBOUND",
        invoice_number="IEQ-US-9002", subtotal=6200.00, grand_total=6200.00,
        tax_amount=0.00, currency="USD", invoice_date="2026-06-27", due_date=None,
        po_number=None, status="NEEDS_REVIEW",
        items=_items(
            ("Professional services - implementation (40 hrs at USD 150.00/hr)",
             40, 150.00, 6200.00),
        ),
        sa_alerts=_alerts(
            (
                "subtotal_mismatch",
                "Line 'Professional services - implementation' prints USD 6,200.00 but "
                "quantity 40 x unit price USD 150.00 is USD 6,000.00.",
            ),
        ),
    ),
    dict(
        vendor_name=None, customer_name="Meridian Health Partners", flow_direction="OUTBOUND",
        invoice_number="IEQ-US-9003", subtotal=12000.00, grand_total=12000.00,
        tax_amount=0.00, currency="USD", invoice_date="2026-05-15", due_date=None,
        po_number=None, status="PAID",
        items=_items(("Annual support contract", 1, 12000.00, 12000.00)),
    ),
]

US_CHUNKS = [
    {
        "id": "chunk-cmc-1",
        "document": (
            "Cascade Manufacturing Co - Invoice CMC-330217. CNC machined parts, custom "
            "tooling and freight. Sales Tax: $0.00. Resale Exemption Certificate "
            "#OR-EX-88231 on file. Total $2,600.00."
        ),
        "distance": 0.17,
        "matched_by": "semantic",
        "metadata": {"invoice_id": None, "vendor_name": "Cascade Manufacturing Co", "page": 1},
    },
    {
        "id": "chunk-sos-1",
        "document": (
            "Summit Office Supplies - Invoice SOS-100442. Laptop stands, 10 at $45.00. "
            "No sales tax charged on this B2B service item. Total $450.00."
        ),
        "distance": 0.28,
        "matched_by": "semantic",
        "metadata": {"invoice_id": None, "vendor_name": "Summit Office Supplies", "page": 1},
    },
]


# ---------------------------------------------------------------------------
# EU — Infinevo Cloud GmbH (Berlin, VAT ID DE312456789), EUR
# ---------------------------------------------------------------------------
EU_ROWS = [
    dict(
        vendor_name="Nordic Office AB", customer_name=None, flow_direction="INBOUND",
        invoice_number="NOA-2026-3310", subtotal=2000.00, grand_total=2380.00,
        tax_amount=380.00, currency="EUR", invoice_date="2026-06-02", due_date=None,
        po_number=None, status="COMPLETED",
        items=_items(("Ergonomic desks", 5, 400.00, 2000.00)),
    ),
    dict(
        vendor_name="Cafe Fournitures SARL", customer_name=None, flow_direction="INBOUND",
        invoice_number="CFS-2026-0921", subtotal=1300.00, grand_total=1516.50,
        tax_amount=216.50, currency="EUR", invoice_date="2026-06-09", due_date=None,
        po_number="PO-EU-1102", status="COMPLETED",
        items=_items(
            ("Office furniture (VAT 20% standard rate)", 1, 1000.00, 1000.00),
            ("Printed materials / books (VAT 5.5% reduced rate)", 1, 300.00, 300.00),
        ),
    ),
    dict(
        vendor_name="Rhein Industrietechnik GmbH", customer_name=None, flow_direction="INBOUND",
        invoice_number="RIT-2026-0456", subtotal=9200.00, grand_total=9428.00,
        tax_amount=228.00, currency="EUR", invoice_date="2026-06-17", due_date=None,
        po_number="PO-DE-2291", status="COMPLETED",
        items=_items(
            ("Machinery parts (reverse charge, intra-EU B2B, VAT 0%)", 1, 8000.00, 8000.00),
            ("Installation service (local, taxable, VAT 19%)", 1, 1200.00, 1200.00),
        ),
    ),
    dict(
        vendor_name="Iberia Suministros SL", customer_name=None, flow_direction="INBOUND",
        invoice_number="ISL-2026-0678", subtotal=1150.00, grand_total=1391.50,
        tax_amount=241.50, currency="EUR", invoice_date="2026-06-07", due_date=None,
        po_number=None, status="AUDIT_REQUIRED",
        items=_items(("Packaging materials (500 qty)", 500, 2.20, 1150.00)),
        sa_alerts=_alerts(
            (
                "line_item_calculation_mismatch",
                "Line 'Packaging materials (500 qty)' prints EUR 1,150.00 but quantity 500 x "
                "unit price EUR 2.20 is EUR 1,100.00. The printed subtotal and the 21% VAT of "
                "EUR 241.50 both key off the higher figure.",
            ),
        ),
    ),
    dict(
        vendor_name="Milano Componenti SRL", customer_name=None, flow_direction="INBOUND",
        invoice_number="MCS-2026-0890", subtotal=5000.00, grand_total=6100.00,
        tax_amount=1100.00, currency="EUR", invoice_date="2026-06-20", due_date=None,
        po_number="PO-EU-3387", status="AUDIT_REQUIRED",
        items=_items(
            ("Precision components", 1, 4500.00, 4500.00),
            ("Quality certification", 1, 500.00, 500.00),
        ),
        sa_alerts=_alerts(
            (
                "missing_required_field",
                "Vendor letterhead prints no VAT ID. Subtotal EUR 5,000.00, VAT 22% "
                "EUR 1,100.00 and total EUR 6,100.00 are all internally consistent -- the "
                "defect is the missing identifier, not the arithmetic.",
            ),
        ),
    ),
    dict(
        vendor_name="Benelux Machines NV", customer_name=None, flow_direction="INBOUND",
        invoice_number="BMN-2026-0234", subtotal=5080.00, grand_total=6146.80,
        tax_amount=1066.80, currency="EUR", invoice_date="2026-06-24", due_date=None,
        po_number="PO-EU-4410", status="AUDIT_REQUIRED",
        items=_items(
            ("Conveyor system parts", 4, 750.00, 3000.00),
            ("Control units", 3, 620.00, 1680.00),
            ("Installation", 1, 400.00, 400.00),
        ),
        sa_alerts=_alerts(
            (
                "line_item_calculation_mismatch",
                "Line 'Control units' prints EUR 1,680.00 but quantity 3 x unit price EUR "
                "620.00 is EUR 1,860.00 -- printed LOWER than true, the opposite direction "
                "from the other flagged mismatches in this corpus.",
            ),
        ),
    ),
    dict(
        vendor_name=None, customer_name="Alpine Retail GmbH", flow_direction="OUTBOUND",
        invoice_number="IEQ-EU-8001", subtotal=3200.00, grand_total=3200.00,
        tax_amount=0.00, currency="EUR", invoice_date="2026-06-26", due_date=None,
        po_number=None, status="SENT",
        items=_items(
            ("Platform subscription - Growth tier (1 mo) - reverse charge, intra-EU B2B, "
             "customer in Austria", 1, 3200.00, 3200.00),
        ),
    ),
    dict(
        vendor_name=None, customer_name="Lisboa Comercio Lda", flow_direction="OUTBOUND",
        invoice_number="IEQ-EU-8002", subtotal=4200.00, grand_total=4200.00,
        tax_amount=0.00, currency="EUR", invoice_date="2026-06-29", due_date=None,
        po_number=None, status="NEEDS_REVIEW",
        items=_items(
            ("Onboarding + integration services - reverse charge, intra-EU B2B, customer in "
             "Portugal", 1, 4000.00, 4200.00),
        ),
        sa_alerts=_alerts(
            (
                "subtotal_mismatch",
                "Line 'Onboarding + integration services' prints EUR 4,200.00 but quantity 1 x "
                "unit price EUR 4,000.00 is EUR 4,000.00.",
            ),
        ),
    ),
    dict(
        vendor_name=None, customer_name="Deutsche Warenhandel GmbH", flow_direction="OUTBOUND",
        invoice_number="IEQ-EU-8003", subtotal=9500.00, grand_total=11305.00,
        tax_amount=1805.00, currency="EUR", invoice_date="2026-05-18", due_date=None,
        po_number=None, status="PAID",
        items=_items(
            ("Annual license renewal - domestic sale within Germany, standard VAT 19%",
             1, 9500.00, 9500.00),
        ),
    ),
]

EU_CHUNKS = [
    {
        "id": "chunk-rit-1",
        "document": (
            "Rhein Industrietechnik GmbH - Invoice RIT-2026-0456. Machinery parts supplied "
            "under intra-EU B2B reverse charge (VAT 0%); installation service taxed locally "
            "at 19%. Note: contract value quoted in USD $10,000 equivalent, invoiced in EUR. "
            "Total EUR 9,428.00."
        ),
        "distance": 0.16,
        "matched_by": "semantic",
        "metadata": {"invoice_id": None, "vendor_name": "Rhein Industrietechnik GmbH", "page": 1},
    },
    {
        "id": "chunk-mcs-1",
        "document": (
            "Milano Componenti SRL - Invoice MCS-2026-0890. Precision components and quality "
            "certification. Subtotal EUR 5,000.00, VAT 22% EUR 1,100.00, Total EUR 6,100.00."
        ),
        "distance": 0.27,
        "matched_by": "semantic",
        "metadata": {"invoice_id": None, "vendor_name": "Milano Componenti SRL", "page": 1},
    },
]


# ---------------------------------------------------------------------------
# The registry the harness seeds from
# ---------------------------------------------------------------------------
# Which invoice each chunk belongs to, so `scripts/run_agent_eval.py` can bind it
# to that row's generated id and a `get_full_record` fetch on the agentic path
# returns a page instead of nothing. An explicit map rather than a
# `metadata["invoice_number"]` key, because real Chroma metadata does not carry
# one -- the same reason the base tenant's two chunks are paired to BRL-7702 /
# TSD-620458 by an explicit tuple in that script rather than read out of the chunk.
CHUNK_INVOICE_NUMBERS = {
    "chunk-ke-1": "KE-2026-0089",
    "chunk-ghs-1": "GHS-2026-0334",
    "chunk-cmc-1": "CMC-330217",
    "chunk-sos-1": "SOS-100442",
    "chunk-rit-1": "RIT-2026-0456",
    "chunk-mcs-1": "MCS-2026-0890",
}

REGION_TENANTS: dict[str, dict] = {
    INDIA_TENANT_ID: {
        "label": "india",
        "entity": "Infinevo Cloud Pvt Ltd (Gurugram, India)",
        "rows": INDIA_ROWS,
        "chunks": INDIA_CHUNKS,
    },
    US_TENANT_ID: {
        "label": "us",
        "entity": "Infinevo Cloud Inc. (Austin, TX, USA)",
        "rows": US_ROWS,
        "chunks": US_CHUNKS,
    },
    EU_TENANT_ID: {
        "label": "eu",
        "entity": "Infinevo Cloud GmbH (Berlin, Germany)",
        "rows": EU_ROWS,
        "chunks": EU_CHUNKS,
    },
}


def region_stats_summary(tenant_id: str) -> str:
    """The tenant snapshot the planner/SQL prompts get for a regional tenant.

    Computed from that tenant's own rows for the same reason
    `agent_eval_golden_sample.tenant_stats_summary()` is: `_get_tenant_stats_summary()`'s
    ORM query returns an empty tenant against this SQLite fixture, and a
    hand-typed snapshot drifts from the rows it claims to describe the moment one
    of them changes. Counts *counterparties*, not `vendor_name`, because a third
    of these rows are OUTBOUND and carry `customer_name` instead — a "distinct
    vendors" figure computed off `vendor_name` alone would silently under-report
    every regional tenant by three.
    """
    rows = REGION_TENANTS[tenant_id]["rows"]
    totals: dict[str, float] = {}
    counterparties = set()
    statuses: dict[str, int] = {}
    dates = []
    inbound = 0
    for row in rows:
        currency = row["currency"]
        totals[currency] = totals.get(currency, 0.0) + float(row["grand_total"])
        counterparties.add(row["vendor_name"] or row["customer_name"])
        statuses[row["status"]] = statuses.get(row["status"], 0) + 1
        dates.append(row["invoice_date"])
        if row["flow_direction"] == "INBOUND":
            inbound += 1

    spend = "; ".join(f"{c} {v:,.2f}" for c, v in sorted(totals.items()))
    status_text = ", ".join(f"{k}: {v}" for k, v in sorted(statuses.items()))
    return (
        "Tenant Data Snapshot (orientation only - always run a live query for exact figures): "
        f"{len(rows)} total invoices ({inbound} INBOUND from vendors, {len(rows) - inbound} "
        f"OUTBOUND issued by this tenant), total spend per currency: {spend} "
        "(never add or compare amounts across different currencies - no exchange rate is "
        f"available; always state the currency alongside any amount), {len(counterparties)} "
        f"distinct counterparties, dates {min(dates)} to {max(dates)}, status breakdown: "
        f"{status_text}. No invoice in this tenant has a due date recorded."
    )


__all__ = [
    "CHUNK_INVOICE_NUMBERS",
    "EU_CHUNKS",
    "EU_ROWS",
    "EU_TENANT_ID",
    "INDIA_CHUNKS",
    "INDIA_ROWS",
    "INDIA_TENANT_ID",
    "REGION_TENANTS",
    "US_CHUNKS",
    "US_ROWS",
    "US_TENANT_ID",
    "region_stats_summary",
]
