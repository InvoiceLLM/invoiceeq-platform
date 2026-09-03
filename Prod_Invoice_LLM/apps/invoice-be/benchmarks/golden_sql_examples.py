"""Curated question -> SQL examples for the SQL route (Feature 6.1 item C4, part 3).

One entry per golden case that has a structural answer. Each SQL is the reference
the model should be shown as a few-shot example -- retrieved per query by
embedding similarity, never a tenant's own prior turns (cross-tenant leakage by
example is the risk the design named).

**Every entry is verified, not asserted.** `scratchpad/verify_golden_sql.py` seeds
the golden fixture exactly as `scripts/run_agent_eval.py` does, runs each SQL
through `execute_generated_sql` (so the tenant guard applies), and compares the
returned `invoice_number`s with the golden case's `expected_invoice_numbers`. An
entry that fails that check is removed, not shipped.

`{tenant_id}` is substituted at render time. Line-item examples carry both dialect
shapes because rule 6d has no portable spelling (Gap 253); `sql` is Postgres,
`sql_sqlite` is the SQLite equivalent, and the retrieval step hands the model the
one for the engine the request is bound to (`_sql_dialect_name`).

Cases deliberately absent, because their correct answer is NOT a query: greetings,
out-of-scope requests, the internals probe, the unsupported-field refusal, the two
zero-row typo/unknown-vendor cases (C3's ladder owns those), and the document
question that belongs to RAG.
"""

_PG_LINES = (
    "SELECT invoice.invoice_number, invoice.vendor_name, invoice.currency, "
    "item->>'description' AS line_description, (item->>'quantity')::numeric AS line_qty, "
    "(item->>'unit_price')::numeric AS line_unit_price, (item->>'amount')::numeric AS line_amount "
    "FROM invoice LEFT JOIN LATERAL jsonb_array_elements(CASE WHEN jsonb_typeof(items) = 'array' THEN items ELSE '[]'::jsonb END) AS item ON true "
    "WHERE tenant_id = '{tenant_id}'"
)
_SQLITE_LINES = (
    "SELECT invoice.invoice_number, invoice.vendor_name, invoice.currency, "
    "item.value ->> 'description' AS line_description, item.value ->> 'quantity' AS line_qty, "
    "item.value ->> 'unit_price' AS line_unit_price, item.value ->> 'amount' AS line_amount "
    "FROM invoice LEFT JOIN json_each(CASE WHEN json_valid(items) AND json_type(items) = 'array' THEN items ELSE '[]' END) AS item ON 1=1 "
    "WHERE tenant_id = '{tenant_id}'"
)


def _lines(where_pg: str, where_sqlite: str | None = None) -> dict:
    # SQLite's json_each aliases the TABLE, so the element is `item.value`.
    sqlite_where = where_sqlite or where_pg.replace("item->>", "item.value ->> ")
    return {
        "sql": f"{_PG_LINES} AND {where_pg}",
        "sql_sqlite": f"{_SQLITE_LINES} AND {sqlite_where}",
    }


GOLDEN_SQL_EXAMPLES: list[dict] = [
    # ------------------------------------------------------------------ base tenant
    {
        "case_id": "titan_steel_payment_status",
        "question": "has the Titan Steel Distributors invoice been paid",
        "why": "rule 4a: a named counterparty with no direction cue -- check both columns; and the INBOUND `status` is never a payment signal, so select what IS knowable",
        "sql": "SELECT invoice_number, vendor_name, customer_name, flow_direction, status, due_date, grand_total, currency FROM invoice WHERE tenant_id = '{tenant_id}' AND ((flow_direction = 'INBOUND' AND LOWER(vendor_name) LIKE LOWER('%titan steel distributors%')) OR (flow_direction = 'OUTBOUND' AND LOWER(customer_name) LIKE LOWER('%titan steel distributors%')))",
    },
    {
        "case_id": "rajesh_steel_cgst",
        "question": "whats the CGST we paid to Rajesh Steel",
        "why": "a tax component is a property of the invoice, never a line-item word: select tax_amount with the identifying columns; the components come from the record",
        "sql": "SELECT invoice_number, vendor_name, tax_amount, grand_total, currency FROM invoice WHERE tenant_id = '{tenant_id}' AND flow_direction = 'INBOUND' AND LOWER(vendor_name) LIKE LOWER('%rajesh steel%')",
    },
    {
        "case_id": "datapipe_vs_stratedge",
        "question": "Between DataPipe Solutions and StratEdge Partners, whose invoice to us had the bigger total?",
        "why": "rule 10: a comparison returns a row for EVERY named entity; the superlative is answered in prose, never with LIMIT 1",
        "sql": "SELECT invoice_number, vendor_name, grand_total, currency FROM invoice WHERE tenant_id = '{tenant_id}' AND flow_direction = 'INBOUND' AND (LOWER(vendor_name) LIKE LOWER('%datapipe solutions%') OR LOWER(vendor_name) LIKE LOWER('%stratedge partners%')) ORDER BY grand_total DESC",
    },
    {
        "case_id": "freight_per_vendor",
        "question": "which vendors billed us for freight, delivery, or shipping charges, and how much per vendor",
        "why": "a figure attributable ONLY to a charge type is rule 6d: fetch the matching LINES, never SUM(grand_total); per-vendor subtotals happen in the answer",
        **_lines(
            "flow_direction = 'INBOUND' AND (LOWER(item->>'description') LIKE '%freight%' OR LOWER(item->>'description') LIKE '%delivery%' OR LOWER(item->>'description') LIKE '%shipping%')",
        ),
    },
    {
        "case_id": "bolts_reconciliation",
        "question": "does the bolts line on invoice US-20260722-001 actually add up?",
        "why": "one named line on one named invoice: the line's own quantity, unit price and amount; the arithmetic is done deterministically after retrieval, not in SQL",
        **_lines("invoice.invoice_number = 'US-20260722-001' AND LOWER(item->>'description') LIKE '%bolts%'"),
    },
    {
        "case_id": "large_invoice_full_detail",
        "question": "give me the full details of the Meridian Industrial Supply invoice",
        "why": "rule 11: a details question selects the projection a person reads, never items/tags/sa_alerts by default",
        "sql": "SELECT invoice_number, vendor_name, customer_name, flow_direction, invoice_date, due_date, grand_total, currency, status, po_number FROM invoice WHERE tenant_id = '{tenant_id}' AND LOWER(vendor_name) LIKE LOWER('%meridian industrial supply%')",
    },
    {
        "case_id": "small_invoice_full_detail",
        "question": "give me the full details of the Kingsway Fasteners invoice",
        "why": "rule 11, same projection",
        "sql": "SELECT invoice_number, vendor_name, customer_name, flow_direction, invoice_date, due_date, grand_total, currency, status, po_number FROM invoice WHERE tenant_id = '{tenant_id}' AND LOWER(vendor_name) LIKE LOWER('%kingsway fasteners%')",
    },
    {
        "case_id": "multi_part_totals_and_dates",
        "question": "For the Titan Steel Distributors invoice, what is the total, how much of that is tax, and when is it due?",
        "why": "three attributes of one invoice: one query, the identifying columns plus each attribute asked for",
        "sql": "SELECT invoice_number, vendor_name, grand_total, tax_amount, due_date, currency FROM invoice WHERE tenant_id = '{tenant_id}' AND flow_direction = 'INBOUND' AND LOWER(vendor_name) LIKE LOWER('%titan steel distributors%')",
    },
    {
        "case_id": "all_vendors_over_twenty_thousand",
        "question": "list every vendor we have an invoice from over USD 20,000, with the amount",
        "why": "a threshold in a named currency: filter on currency explicitly, never compare amounts across currencies",
        "sql": "SELECT vendor_name, invoice_number, grand_total, currency FROM invoice WHERE tenant_id = '{tenant_id}' AND flow_direction = 'INBOUND' AND currency = 'USD' AND grand_total > 20000 ORDER BY grand_total DESC",
    },
    {
        "case_id": "two_vendors_two_questions",
        "question": "what did Blue Ridge Logistics and Harbor Tech each bill us, and which is older?",
        "why": "two entities, two facts each: one query returning both rows with the columns both facts need",
        "sql": "SELECT invoice_number, vendor_name, grand_total, currency, invoice_date FROM invoice WHERE tenant_id = '{tenant_id}' AND flow_direction = 'INBOUND' AND (LOWER(vendor_name) LIKE LOWER('%blue ridge logistics%') OR LOWER(vendor_name) LIKE LOWER('%harbor tech%')) ORDER BY invoice_date",
    },
    {
        "case_id": "line_item_breakdown_completeness",
        "question": "what's on the Blue Ridge Logistics invoice? break it down",
        "why": "'break it down' on one invoice is every line of that invoice: rule 6d shape with no description filter",
        **_lines("LOWER(invoice.vendor_name) LIKE LOWER('%blue ridge logistics%')"),
    },
    {
        "case_id": "hostile_user_tone",
        "question": "this thing is useless, it never gives me the right numbers. what did we spend with DataPipe?",
        "why": "tone is not a filter: the question is a spend question about one vendor",
        "sql": "SELECT invoice_number, vendor_name, grand_total, currency, invoice_date FROM invoice WHERE tenant_id = '{tenant_id}' AND flow_direction = 'INBOUND' AND LOWER(vendor_name) LIKE LOWER('%datapipe%')",
    },
    {
        "case_id": "zero_result_with_useful_redirect",
        "question": "show me everything from Acme Corp in May 2026",
        "why": "a correct query can return zero rows: the vendor and the date range are both real filters; what happens next is the zero-row ladder's job, not the query's",
        "sql": "SELECT invoice_number, vendor_name, invoice_date, grand_total, currency, status FROM invoice WHERE tenant_id = '{tenant_id}' AND LOWER(vendor_name) LIKE LOWER('%acme corp%') AND invoice_date >= '2026-05-01' AND invoice_date < '2026-06-01'",
        "allow_zero_rows": True,
        "expected_invoice_numbers": (),
    },
    {
        "case_id": "cross_currency_total_refused",
        "question": "what's our total spend across all invoices?",
        "why": "never blend currencies: group by currency and let the answer say there is no single figure",
        "sql": "SELECT currency, SUM(grand_total) AS total_spend, COUNT(*) AS invoices FROM invoice WHERE tenant_id = '{tenant_id}' AND flow_direction = 'INBOUND' GROUP BY currency ORDER BY currency",
        "expected_invoice_numbers": None,
    },
    # ------------------------------------------------------------------ india tenant
    {
        "case_id": "india_mixed_gst_slab_lines",
        "question": "How many line items are on the Bharat Logistics Pvt Ltd invoice, BL-2026-1450, and what GST rate applies to each?",
        "why": "per-line facts of one named invoice: every line, no description filter; the rate is read from each line's own text",
        **_lines("invoice.invoice_number = 'BL-2026-1450'"),
    },
    {
        "case_id": "india_ganesh_subtotal_reconciliation",
        "question": "Does the Ganesh Hardware Store invoice, GHS-2026-0334, reconcile quantity times unit price against the printed line amount?",
        "why": "reconciliation needs the line's quantity, unit price and printed amount; the multiplication is deterministic after retrieval",
        **_lines("invoice.invoice_number = 'GHS-2026-0334'"),
    },
    {
        "case_id": "india_reverse_charge_vendor",
        "question": "Which vendor billed us under a Reverse Charge Mechanism arrangement?",
        "why": "rule 6b: a subject-matter phrase may live in tags, items, or a name -- one four-column OR group, phrase kept whole",
        "sql": "SELECT invoice_number, vendor_name, grand_total, currency FROM invoice WHERE tenant_id = '{tenant_id}' AND flow_direction = 'INBOUND' AND (LOWER(CAST(tags AS TEXT)) LIKE LOWER('%reverse charge%') OR LOWER(CAST(items AS TEXT)) LIKE LOWER('%reverse charge%') OR LOWER(vendor_name) LIKE LOWER('%reverse charge%') OR LOWER(customer_name) LIKE LOWER('%reverse charge%'))",
    },
    {
        "case_id": "india_outbound_only_disambiguation",
        "question": "Show me our invoice to Anand Distributors -- meaning the one we sent them, not anything they sent us.",
        "why": "rule 4: 'we sent them' is OUTBOUND, filtered by customer_name -- never vendor_name",
        "sql": "SELECT invoice_number, customer_name, flow_direction, invoice_date, due_date, grand_total, currency, status FROM invoice WHERE tenant_id = '{tenant_id}' AND flow_direction = 'OUTBOUND' AND LOWER(customer_name) LIKE LOWER('%anand distributors%')",
    },
    {
        "case_id": "india_no_due_date_refusal",
        "question": "When is the Bharat Logistics invoice, BL-2026-1450, due?",
        "why": "select the attribute asked for; a NULL due_date means the invoice does not state one -- the answer says so, it never invents a date",
        "sql": "SELECT invoice_number, vendor_name, invoice_date, due_date, grand_total, currency FROM invoice WHERE tenant_id = '{tenant_id}' AND invoice_number = 'BL-2026-1450'",
    },
    # ------------------------------------------------------------------ us tenant
    {
        "case_id": "us_zero_tax_exemption_reason",
        "question": "Why was no sales tax charged on the Cascade Manufacturing Co invoice, CMC-330217?",
        "why": "'why' about a tax figure: the identifying columns plus tax_amount and subtotal; the reason is read from the record, not searched for as a line",
        "sql": "SELECT invoice_number, vendor_name, subtotal, tax_amount, grand_total, currency FROM invoice WHERE tenant_id = '{tenant_id}' AND invoice_number = 'CMC-330217'",
    },
    {
        "case_id": "us_flagged_inbound_invoices",
        "question": "Which of our inbound invoices have a tax or line-item calculation issue flagged?",
        "why": "rule 3: audit state lives in `status` / `sa_alerts`; for INBOUND rows AUDIT_REQUIRED is the pipeline's flag",
        "sql": "SELECT invoice_number, vendor_name, status, grand_total, currency FROM invoice WHERE tenant_id = '{tenant_id}' AND flow_direction = 'INBOUND' AND status = 'AUDIT_REQUIRED' ORDER BY invoice_number",
    },
    {
        "case_id": "us_freight_per_vendor_multi",
        "question": "Which vendors billed us for freight, delivery, or shipping-related charges, and how much per vendor?",
        "why": "rule 6d, not 6b: a per-vendor figure for a charge type means the matching LINES; each alternative phrase kept whole",
        **_lines(
            "flow_direction = 'INBOUND' AND (LOWER(item->>'description') LIKE '%freight%' OR LOWER(item->>'description') LIKE '%delivery%' OR LOWER(item->>'description') LIKE '%shipping%')",
        ),
    },
    {
        "case_id": "us_outbound_flagged_and_billed_to",
        "question": "Which of our three outbound invoices has a flagged calculation mismatch, and who was it billed to?",
        "why": "OUTBOUND rows carry their own review states; 'billed to' is customer_name",
        "sql": "SELECT invoice_number, customer_name, status, grand_total, currency FROM invoice WHERE tenant_id = '{tenant_id}' AND flow_direction = 'OUTBOUND' AND (status = 'NEEDS_REVIEW' OR (sa_alerts IS NOT NULL AND CAST(sa_alerts AS TEXT) NOT IN ('[]', 'null', '')))",
    },
    {
        "case_id": "us_cross_invoice_grand_total",
        "question": "Across Summit Office Supplies, Blue Ridge Logistics, and Cascade Manufacturing Co, what is the combined grand total?",
        "why": "three named entities in one currency: return every row (rule 10) and let the deterministic figures block add them",
        "sql": "SELECT invoice_number, vendor_name, grand_total, currency FROM invoice WHERE tenant_id = '{tenant_id}' AND flow_direction = 'INBOUND' AND (LOWER(vendor_name) LIKE LOWER('%summit office supplies%') OR LOWER(vendor_name) LIKE LOWER('%blue ridge logistics%') OR LOWER(vendor_name) LIKE LOWER('%cascade manufacturing%'))",
        "expected_invoice_numbers": ("SOS-100442", "BRL-200981", "CMC-330217"),
    },
    # ------------------------------------------------------------------ eu tenant
    {
        "case_id": "eu_mixed_vat_rates",
        "question": "How many different VAT rates appear on the Cafe Fournitures SARL invoice, CFS-2026-0921?",
        "why": "per-line facts of one invoice: every line; the rates are read from each line's text",
        **_lines("invoice.invoice_number = 'CFS-2026-0921'"),
    },
    {
        "case_id": "eu_currency_confusion_trap",
        "question": "What currency is the Rhein Industrietechnik invoice, RIT-2026-0456, actually payable in, and what is the total?",
        "why": "the currency column is the answer; a currency mentioned in a line's text is not",
        "sql": "SELECT invoice_number, vendor_name, currency, grand_total FROM invoice WHERE tenant_id = '{tenant_id}' AND invoice_number = 'RIT-2026-0456'",
    },
    {
        "case_id": "eu_reverse_charge_inbound_line",
        "question": "Which inbound vendor billed us using intra-EU reverse charge, and for which line item specifically?",
        "why": "'which line specifically' is rule 6d: the matching lines, with the description filter",
        **_lines("flow_direction = 'INBOUND' AND LOWER(item->>'description') LIKE '%reverse charge%'"),
    },
    {
        "case_id": "eu_outbound_reverse_charge_vs_domestic",
        "question": "Which two of our three outbound invoices used reverse charge, and which one charged standard VAT instead -- and why the difference?",
        "why": "all three OUTBOUND rows with tax_amount: zero tax marks reverse charge; the 'why' is read from the record's line text",
        "sql": "SELECT invoice_number, customer_name, tax_amount, grand_total, currency, status FROM invoice WHERE tenant_id = '{tenant_id}' AND flow_direction = 'OUTBOUND' ORDER BY invoice_number",
    },
    {
        "case_id": "eu_benelux_line_understated",
        "question": "Does the Control units line on the Benelux Machines invoice, BMN-2026-0234, add up?",
        "why": "one named line on one named invoice, rule 6d; the arithmetic happens after retrieval",
        **_lines("invoice.invoice_number = 'BMN-2026-0234' AND LOWER(item->>'description') LIKE '%control units%'"),
    },
]
