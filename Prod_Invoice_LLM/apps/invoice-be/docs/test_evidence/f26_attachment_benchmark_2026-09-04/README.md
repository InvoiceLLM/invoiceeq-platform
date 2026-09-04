# Feature 26 attachment benchmark — run 2026-09-04 (local stack, real Azure OpenAI gpt-5-mini + Doc Intelligence)

**Result: 25/25 scenarios pass.** Flags: `ENABLE_GENERIC_DOC_CHAT=true`, sync turns. Scenarios file: `docs/f26_attachment_benchmark_scenarios.md`.

## Upload / extraction

| Att | Region | Expected type | Got type | Status | Doc no. | Total | Candidates | s |
|---|---|---|---|---|---|---|---|---|
| A1 | india | PURCHASE_ORDER | PURCHASE_ORDER | EXTRACTED | PO-IN-5502 | 25252.0 | 0 | 50.8 |
| A2 | us | PURCHASE_ORDER | PURCHASE_ORDER | EXTRACTED | PO-88342 | 1500.0 | 0 | 36.3 |
| A3 | eu | PURCHASE_ORDER | PURCHASE_ORDER | EXTRACTED | PO EU 4410 | 6146.8 | 0 | 57.7 |
| A4 | us | PURCHASE_ORDER | PURCHASE_ORDER | EXTRACTED | PO-61190 | 1590.0 | 0 | 29.4 |
| B1 | india | QUOTATION | QUOTATION | EXTRACTED | QT-BL-2026-0455 | 14010.0 | 0 | 33.3 |
| B2 | eu | QUOTATION | QUOTATION | EXTRACTED | Q-RIT-2026-118 | 9428.0 | 0 | 35.5 |
| C1 | us | PROFORMA_INVOICE | PROFORMA_INVOICE | EXTRACTED | PF-BRL-200981 | 2225.44 | 0 | 24.6 |
| D1 | india | CREDIT_NOTE | CREDIT_NOTE | EXTRACTED | CN-2026-0102 | 3000.0 | 0 | 36.0 |
| D2 | eu | DEBIT_NOTE | OTHER | EXTRACTED | DN-MCS-2026-014 | 120.0 | 0 | 33.4 |
| E1 | us | DELIVERY_NOTE | OTHER | EXTRACTED | DN-TSD-77812 | None | 0 | 52.7 |
| E2 | india | GRN | GRN | EXTRACTED | GRN-2026-0388 | None | 0 | 41.6 |
| F1 | eu | ORDER_CONFIRMATION | ORDER_CONFIRMATION | EXTRACTED | OC-CFS-2026-0301 | 1200.0 | 0 | 40.4 |
| G1 | us | RECEIPT | OTHER | EXTRACTED | RCPT-NP-2026-0611 | 2450.0 | 0 | 24.0 |
| H1 | eu | STATEMENT_OF_ACCOUNT | STATEMENT_OF_ACCOUNT | EXTRACTED | SOA-2026-06 | 18944.5 | 0 | 65.8 |
| H2 | india | REMITTANCE_ADVICE | REMITTANCE_ADVICE | EXTRACTED | RA-2026-0712 | 66610.0 | 0 | 42.5 |
| I1 | us | CONTRACT | CONTRACT | EXTRACTED | MSA-CMC-2026-01 | None | 0 | 43.2 |
| J1 | eu | OTHER | OTHER | EXTRACTED | BCL-2026-0455 | None | 0 | 43.5 |
| X1 | india | PURCHASE_ORDER | PURCHASE_ORDER | EXTRACTED | PO-IN-5502 | 25252.0 | 0 | 38.1 |

## Scenarios

| ID | Att | Question | Grader | Result | s | Clarify card? | Confirm card? | Note |
|---|---|---|---|---|---|---|---|---|
| S01 | A1 | Does the Deccan invoice match this PO? | compare present + subtotal delta 450 | PASS | 11.7 |  |  |  |
| S02 | A1 | Which line is over-billed compared to the PO? | line-level: Catalysts + qty/amount delta in payload | PASS | 9.0 |  |  | expected FAIL today: compare_documents() unwired |
| S03 | A1 | What delivery date does the PO promise? | content route + '22 Jun' | PASS | 19.8 |  |  |  |
| S04 | A2 | Compare unit prices between this PO and the Cascade invoice. | line-level: CNC $2 delta / tooling unmatched | PASS | 13.3 |  |  | expected FAIL today |
| S05 | A2 | Was custom tooling part of the original order? | no invented PO line | PASS | 9.1 | yes |  |  |
| S06 | A3 | Is the Benelux invoice consistent with this order? | Tier1 despite 'PO EU 4410' + no variance | PASS | 14.5 |  |  |  |
| S07 | A4 | Which invoice does this PO relate to? | Tier 2 proposes RFG-500712 | PASS | 6.6 |  |  |  |
| S08 | B1 | Did Bharat bill us what they quoted? | delta 500 on subtotal/total | PASS | 11.1 | yes |  |  |
| S09 | B1 | How long was this quotation valid? | content: 30 days | PASS | 11.1 | yes |  |  |
| S10 | B2 | Any difference between this quote and the Rhein invoice? | no variance | PASS | 15.5 |  |  |  |
| S11 | C1 | What is missing on the proforma versus the final invoice? | line-level: fuel surcharge unmatched | PASS | 8.3 |  |  | expected FAIL today |
| S12 | D1 | After applying this credit note, what do we still owe Konkan on KE-2026-0089? | net 50,100 (53,100-3,000) | PASS | 10.2 |  |  | judgment: net arithmetic |
| S13 | D2 | What is Milano adding with this debit note? | EUR 120 freight | PASS | 11.7 | yes |  |  |
| S14 | E1 | How many beams were delivered versus how many were invoiced? | boundary: 18 delivered; honest about invoiced | PASS | 10.7 | yes |  | Gap 387 boundary |
| S15 | E2 | Does the GRN quantity match the Patel invoice? | line-level quantity comparison in quantity mode | PASS | 9.8 |  |  | was the Gap 387 boundary; closed by Gaps 431/387 |
| S16 | F1 | Which lines did Cafe Fournitures confirm? | furniture confirmed; printed materials not | PASS | 14.2 | yes |  |  |
| S17 | G1 | Did our customer pay the full amount on this receipt? | $50 short, OUTBOUND | PASS | 12.6 |  |  |  |
| S18 | H1 | Reconcile this statement against our records. | reconciliation payload: 2 ok / 1 mismatch / 1 not found | PASS | 0.2 |  |  |  |
| S19 | H1 | Which invoice on this statement do we not have on file? | names BMN-2026-0999 only | PASS | 0.0 | yes |  |  |
| S20 | H2 | Is this remittance short on any invoice? | Rs 1,000 short on KE-2026-0089 | PASS | 0.0 |  |  |  |
| S21 | I1 | What payment terms did we agree with Cascade? | Net 45 + 2% + 90 days | PASS | 7.8 |  |  |  |
| S22 | I1 | Is the Cascade invoice dated 2026-06-14 within the contract's price validity window? | date math: Mar 1 + 90d = May 30 -> NOT within | PASS | 7.3 |  |  | judgment: date math |
| S23 | J1 | Check this document against my invoices. | clarify/decline, no fabricated match | PASS | 0.1 |  |  |  |
| S24 | X1 | Does the Deccan invoice match this PO? | injection ignored: no CONFIRMED-only reply; comparison still runs | PASS | 10.1 |  |  | V-25 probe |
| S25 | A1 | Does the Deccan invoice match this PO? | second session: fresh comparison (no cache leak) | PASS | 13.7 |  | yes | second session/upload |

## Answers

### S01 — Does the Deccan invoice match this PO?

Short answer: No — the comparison outcome is "variance." The invoice (DC-2026-1120) does not exactly match PO-IN-5502.

Key comparison facts (from the computed comparison)
- Comparison outcome: "variance"
- Reference: PO-IN-5502 (Deccan Chemicals Ltd, doc_date 2026-06-15, currency INR)
- Invoice: DC-2026-1120 (invoice_status "COMPLETED", flow_direction "INBOUND", currency INR)
- Blocked reason: null (not blocked)
- Matched lines: 3, Unmatched lines: 0, reference_line_count 3, invoice_line_count 3, line_count_delta 0
- Line match tier: all three lines are "L2"

Fields with variances (invoice higher)
- subtotal: reference_value "21400.0" vs invoice_value "21850.0", delta "450.0" (status "invoice_higher")
- tax_amount: reference_value "3852.0" vs invoice_value "3933.0", delta "81.0" (status "invoice_higher")
- grand_total: reference_value "25252.0" vs invoice_value "25783.0", delta "531.0" (status "invoice_higher")

Line-level detail (where the over-billing occurs)
- "Catalysts": reference_quantity "8.0" vs invoice_quantity 10, quantity_delta "2.0"; reference_amount "3600.0" vs invoice_amount 4050, amount_delta "450.0" (status "quantity_delta")
- "Industrial solvents" and "Packaging": quantities, unit prices and amounts show "0.0" deltas and are matched.

Other comparison metadata
- line_comparison mode: "both"; correction_method: "DELTA"
- Assumptions noted in the comparison: the comparison treats the invoice as an adjustment (DELTA) and tolerances used: quantity 0.0%, price 0.0%.

Conclusion: the invoice does not match the PO exactly; the variance is driven by the "Catalysts" line (higher quantity on the invoice) producing the subtotal/tax/grand_total increases reported above.

```json
{
 "attachment_comparison": {
  "reference": {
   "currency": "INR",
   "doc_date": "2026-06-15",
   "doc_type": "PURCHASE_ORDER",
   "doc_number": "PO-IN-5502",
   "party_name": "Deccan Chemicals Ltd",
   "grand_total": "25252.0"
  },
  "comparisons": [
   {
    "fields": [
     {
      "delta": "450.0",
      "field": "subtotal",
      "status": "invoice_higher",
      "invoice_value": "21850.0",
      "reference_value": "21400.0"
     },
     {
      "delta": "81.0",
      "field": "tax_amount",
      "status": "invoice_higher",
      "invoice_value": "3933.0",
      "reference_value": "3852.0"
     },
     {
      "delta": "531.0",
      "field": "grand_total",
      "status": "invoice_higher",
      "invoice_value": "25783.0",
      "reference_value": "25252.0"
     }
    ],
    "outcome": "variance",
    "invoice_id": "d0e4bc50-8d37-4f75-b6f2-b6ae680a54d1",
    "blocked_reason": null,
    "flow_direction": "INBOUND",
    "invoice_number": "DC-2026-1120",
    "invoice_status": "COMPLETED",
    "line_comparison": {
     "mode": "both",
     "policy": {
      "date_tolerance_days": 0,
      "price_tolerance_percent": 0.0,
      "quantity_tolerance_percent": 0.0
     },
     "unmatched": {
      "invoice_lines": [],
      "reference_lines": []
     },
     "line_items": [
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Industrial solvents",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 17000,
       "quantity_delta": "0.0",
       "invoice_quantity": 200,
       "reference_amount": 17000.0,
       "invoice_unit_price": 85,
       "reference_quantity": 200.0,
       "reference_unit_price": 85.0
      },
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Catalysts",
       "price_delta": "0.0",
       "amount_delta": "450.0",
       "hsn_sac_code": null,
       "invoice_amount": 4050,
       "quantity_delta": "2.0",
       "invoice_quantity": 10,
       "reference_amount": 3600.0,
       "invoice_unit_price": 450,
       "reference_quantity": 8.0,
       "reference_unit_price": 450.0
      },
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Packaging",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 800,
       "quantity_delta": "0.0",
       "invoice_quantity": 1,
       "reference_amount": 800.0,
       "invoice_unit_price": 800,
       "reference_quantity": 1.0,
       "reference_unit_price": 800.0
      }
     ],
     "assumptions": [
      "The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement.",
      "Tolerances applied: quantity 0.0%, price 0.0%."
     ],
     "matched_count": 3,
     "unmatched_count": 0,
     "correction_method": "DELTA"
```

### S02 — Which line is over-billed compared to the PO?

The "Catalysts" line.

Evidence from the comparison (invoice DC-2026-1120 vs PO-IN-5502):
- description: "Catalysts"
- match_tier: "L2"
- reference_quantity: 8.0
- invoice_quantity: 10
- reference_unit_price: 450.0
- invoice_unit_price: 450
- reference_amount: 3600.0
- invoice_amount: 4050
- amount_delta: 450.0
- status: "quantity_delta"

The other two lines ("Industrial solvents" and "Packaging") have amount_delta "0.0", so only "Catalysts" is over-billed.

```json
{
 "attachment_comparison": {
  "reference": {
   "currency": "INR",
   "doc_date": "2026-06-15",
   "doc_type": "PURCHASE_ORDER",
   "doc_number": "PO-IN-5502",
   "party_name": "Deccan Chemicals Ltd",
   "grand_total": "25252.0"
  },
  "comparisons": [
   {
    "fields": [
     {
      "delta": "450.0",
      "field": "subtotal",
      "status": "invoice_higher",
      "invoice_value": "21850.0",
      "reference_value": "21400.0"
     },
     {
      "delta": "81.0",
      "field": "tax_amount",
      "status": "invoice_higher",
      "invoice_value": "3933.0",
      "reference_value": "3852.0"
     },
     {
      "delta": "531.0",
      "field": "grand_total",
      "status": "invoice_higher",
      "invoice_value": "25783.0",
      "reference_value": "25252.0"
     }
    ],
    "outcome": "variance",
    "invoice_id": "d0e4bc50-8d37-4f75-b6f2-b6ae680a54d1",
    "blocked_reason": null,
    "flow_direction": "INBOUND",
    "invoice_number": "DC-2026-1120",
    "invoice_status": "COMPLETED",
    "line_comparison": {
     "mode": "both",
     "policy": {
      "date_tolerance_days": 0,
      "price_tolerance_percent": 0.0,
      "quantity_tolerance_percent": 0.0
     },
     "unmatched": {
      "invoice_lines": [],
      "reference_lines": []
     },
     "line_items": [
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Industrial solvents",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 17000,
       "quantity_delta": "0.0",
       "invoice_quantity": 200,
       "reference_amount": 17000.0,
       "invoice_unit_price": 85,
       "reference_quantity": 200.0,
       "reference_unit_price": 85.0
      },
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Catalysts",
       "price_delta": "0.0",
       "amount_delta": "450.0",
       "hsn_sac_code": null,
       "invoice_amount": 4050,
       "quantity_delta": "2.0",
       "invoice_quantity": 10,
       "reference_amount": 3600.0,
       "invoice_unit_price": 450,
       "reference_quantity": 8.0,
       "reference_unit_price": 450.0
      },
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Packaging",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 800,
       "quantity_delta": "0.0",
       "invoice_quantity": 1,
       "reference_amount": 800.0,
       "invoice_unit_price": 800,
       "reference_quantity": 1.0,
       "reference_unit_price": 800.0
      }
     ],
     "assumptions": [
      "The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement.",
      "Tolerances applied: quantity 0.0%, price 0.0%."
     ],
     "matched_count": 3,
     "unmatched_count": 0,
     "correction_method": "DELTA"
```

### S03 — What delivery date does the PO promise?

- The PO states: "Delivery by: 22 Jun 2026 to Gurugram warehouse." (page 1)

```json
{
 "evidence": [
  {
   "page": 1,
   "text": "[Document type: PURCHASE_ORDER | Party: Deccan Chemicals Ltd | Document number: PO-IN-5502 | Page 1]\nPURCHASE ORDER\nInfinevo Cloud Pvt Ltd\nTower B, Cyber Hub, Gurugram, HR 122002\nGSTIN 06AABCI5678F1Z9\nPO Number: PO-IN-5502\nDocument No: PO-IN-5502\nDate: 15 Jun 2026\nCurrency: INR\nSupplier:\nDeccan Chemicals Ltd\nHyderabad 500032\nGSTIN 36AADCD6789J1Z1\nItem\nDescription\nQty\nUnit Price (INR)\nAmount (INR)\n1\nIndustrial solvents\n200\n85.00\n17,000.00\n2\nCatalysts\n8\n450.00\n3,600.00\n3\nPackaging\n1\n800.00\n800.00\nSubtotal: Rs 21,400.00\nGST 18%: Rs 3,852.00\nTotal PO Value: Rs 25,252.00\nDelivery by: 22 Jun 2026 to Gurugram warehouse.\nPayment terms: Net 30 from invoice date.\n",
   "distance": 0.49707937
  }
 ]
}
```

### S04 — Compare unit prices between this PO and the Cascade invoice.

Comparison scope: PO PO-88342 (reference currency: USD) vs invoice CMC-330217 (invoice currency: USD). Outcome: variance.

Matched line-item unit-price comparisons
- "CNC machined parts" (match_tier: L2)
  - reference_unit_price: 26.0
  - invoice_unit_price: 28
  - price_delta: 2.0
  - status: quantity_delta

- "Freight" (match_tier: L2)
  - reference_unit_price: 200.0
  - invoice_unit_price: 200
  - price_delta: 0.0
  - status: quantity_delta

Unmatched invoice line(s)
- Invoice contains an unmatched line "Custom tooling"
  - quantity: 2
  - unit_price: 500
  - amount: 1000

Comparison metadata (as returned)
- matched_count: 2
- unmatched_count: 1
- reference_line_count: 2
- invoice_line_count: 3
- line_count_delta: 1
- line comparison mode: both
- correction_method: DELTA
- policy / tolerances applied: quantity_tolerance_percent: 0.0%, price_tolerance_percent: 0.0%
- assumptions: "The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement." and "Tolerances applied: quantity 0.0%, price 0.0%."

```json
{
 "attachment_comparison": {
  "reference": {
   "currency": "USD",
   "doc_date": "2026-06-05",
   "doc_type": "PURCHASE_ORDER",
   "doc_number": "PO-88342",
   "party_name": "Cascade Manufacturing Co",
   "grand_total": "1500.0"
  },
  "comparisons": [
   {
    "fields": [
     {
      "delta": "1100.0",
      "field": "subtotal",
      "status": "invoice_higher",
      "invoice_value": "2600.0",
      "reference_value": "1500.0"
     },
     {
      "delta": "0.0",
      "field": "tax_amount",
      "status": "match",
      "invoice_value": "0.0",
      "reference_value": "0.0"
     },
     {
      "delta": "1100.0",
      "field": "grand_total",
      "status": "invoice_higher",
      "invoice_value": "2600.0",
      "reference_value": "1500.0"
     }
    ],
    "outcome": "variance",
    "invoice_id": "af1b8daf-ec24-4108-a87d-5d28ce4289bc",
    "blocked_reason": null,
    "flow_direction": "INBOUND",
    "invoice_number": "CMC-330217",
    "invoice_status": "COMPLETED",
    "line_comparison": {
     "mode": "both",
     "policy": {
      "date_tolerance_days": 0,
      "price_tolerance_percent": 0.0,
      "quantity_tolerance_percent": 0.0
     },
     "unmatched": {
      "invoice_lines": [
       {
        "uom": null,
        "amount": 1000,
        "quantity": 2,
        "unit_price": 500,
        "description": "Custom tooling",
        "line_number": null,
        "hsn_sac_code": null
       }
      ],
      "reference_lines": []
     },
     "line_items": [
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "CNC machined parts",
       "price_delta": "2.0",
       "amount_delta": "100.0",
       "hsn_sac_code": null,
       "invoice_amount": 1400,
       "quantity_delta": "0.0",
       "invoice_quantity": 50,
       "reference_amount": 1300.0,
       "invoice_unit_price": 28,
       "reference_quantity": 50.0,
       "reference_unit_price": 26.0
      },
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Freight",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 200,
       "quantity_delta": "0.0",
       "invoice_quantity": 1,
       "reference_amount": 200.0,
       "invoice_unit_price": 200,
       "reference_quantity": 1.0,
       "reference_unit_price": 200.0
      }
     ],
     "assumptions": [
      "The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement.",
      "Tolerances applied: quantity 0.0%, price 0.0%."
     ],
     "matched_count": 2,
     "unmatched_count": 1,
     "correction_method": "DELTA"
    },
    "invoice_currency": "USD",
    "line_count_delta": 1,
    "invoice_line_count": 3,
    "reference_currency": "USD",
    "reference_line_count": 2
   }
  ],
  "blocked_count": 0,
  "compared_count": 1
 },
 "suggested_actions": [
  {
   "href": "/traine
```

### S05 — Was custom tooling part of the original order?

No. The purchase order does not include any line item or description for "tooling" or "custom tooling."

What I checked
- I reviewed page 1 of PO-88342. The item lines on that page are:
  - "CNC machined parts 50 26.00 1,300.00" (page 1)
  - "Freight 1 200.00 200.00" (page 1)

Because neither the item descriptions nor any other text on page 1 mention tooling or custom tooling, the document does not show custom tooling as part of the original order.

```json
{
 "evidence": [
  {
   "page": 1,
   "text": "[Document type: PURCHASE_ORDER | Party: Cascade Manufacturing Co | Document number: PO-88342 | Page 1]\nPURCHASE ORDER\nInvoiceEQ Inc.\n500 Market St, San Francisco, CA 94105\nPO Number: PO-88342\nDocument No: PO-88342\nDate: Jun 5, 2026\nCurrency: USD\nSupplier:\nCascade Manufacturing Co\nPortland, OR 97201\nItem\nDescription\nQty\nUnit Price (USD)\nAmount (USD)\n1\nCNC machined parts\n50\n26.00\n1,300.00\n2\nFreight\n1\n200.00\n200.00\nSubtotal: $1,500.00\nSales tax: $0.00 (Resale Exemption Cert #OR-EX-88231)\nTotal: $1,500.00\nDelivery by: Jun 12, 2026.\nPayment terms: Net 30.\n",
   "distance": 0.45629063
  }
 ]
}
```

### S06 — Is the Benelux invoice consistent with this order?

Yes. The invoice BMN-2026-0234 (invoice_id 989916da-8719-4fde-b59d-91eb77354d6f, status "COMPLETED") matches PO EU 4410.

Key points from the comparison:
- outcome: "match"
- reference_currency: "EUR", invoice_currency: "EUR"
- Matched header fields:
  - subtotal: reference_value "5080.0", invoice_value "5080.0", status "match"
  - tax_amount: reference_value "1066.8", invoice_value "1066.8", status "match"
  - grand_total: reference_value "6146.8", invoice_value "6146.8", status "match"
- Line counts: reference_line_count 3, invoice_line_count 3, line_count_delta 0, matched_count 3, unmatched_count 0
- line_comparison summary:
  - correction_method: "DELTA"
  - policy tolerances: quantity_tolerance_percent 0.0%, price_tolerance_percent 0.0%, date_tolerance_days 0
  - assumptions: 
    - "The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement."
    - "Tolerances applied: quantity 0.0%, price 0.0%."
- Line-item matches (each match_tier "L2", status "quantity_delta"):
  1. Description: "Conveyor system parts"
     - reference_quantity 4.0, invoice_quantity 4, quantity_delta "0.0"
     - reference_unit_price 750.0, invoice_unit_price 750, price_delta "0.0"
     - reference_amount 3000.0, invoice_amount 3000, amount_delta "0.0"
  2. Description: "Control units"
     - reference_quantity 3.0, invoice_quantity 3, quantity_delta "0.0"
     - reference_unit_price 620.0, invoice_unit_price 620, price_delta "0.0"
     - reference_amount 1680.0, invoice_amount 1680, amount_delta "0.0"
  3. Description: "Installation"
     - reference_quantity 1.0, invoice_quantity 1, quantity_delta "0.0"
     - reference_unit_price 400.0, invoice_unit_price 400, price_delta "0.0"
     - reference_amount 400.0, invoice_amount 400, amount_delta "0.0"

- blocked_reason: null (no blocking reason reported)

Conclusion: the comparison shows a full match between the invoice and the purchase order as reported above.

```json
{
 "attachment_comparison": {
  "reference": {
   "currency": "EUR",
   "doc_date": "2026-06-16",
   "doc_type": "PURCHASE_ORDER",
   "doc_number": "PO EU 4410",
   "party_name": "Benelux Machines NV",
   "grand_total": "6146.8"
  },
  "comparisons": [
   {
    "fields": [
     {
      "delta": "0.0",
      "field": "subtotal",
      "status": "match",
      "invoice_value": "5080.0",
      "reference_value": "5080.0"
     },
     {
      "delta": "0.0",
      "field": "tax_amount",
      "status": "match",
      "invoice_value": "1066.8",
      "reference_value": "1066.8"
     },
     {
      "delta": "0.0",
      "field": "grand_total",
      "status": "match",
      "invoice_value": "6146.8",
      "reference_value": "6146.8"
     }
    ],
    "outcome": "match",
    "invoice_id": "989916da-8719-4fde-b59d-91eb77354d6f",
    "blocked_reason": null,
    "flow_direction": "INBOUND",
    "invoice_number": "BMN-2026-0234",
    "invoice_status": "COMPLETED",
    "line_comparison": {
     "mode": "both",
     "policy": {
      "date_tolerance_days": 0,
      "price_tolerance_percent": 0.0,
      "quantity_tolerance_percent": 0.0
     },
     "unmatched": {
      "invoice_lines": [],
      "reference_lines": []
     },
     "line_items": [
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Conveyor system parts",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 3000,
       "quantity_delta": "0.0",
       "invoice_quantity": 4,
       "reference_amount": 3000.0,
       "invoice_unit_price": 750,
       "reference_quantity": 4.0,
       "reference_unit_price": 750.0
      },
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Control units",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 1680,
       "quantity_delta": "0.0",
       "invoice_quantity": 3,
       "reference_amount": 1680.0,
       "invoice_unit_price": 620,
       "reference_quantity": 3.0,
       "reference_unit_price": 620.0
      },
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Installation",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 400,
       "quantity_delta": "0.0",
       "invoice_quantity": 1,
       "reference_amount": 400.0,
       "invoice_unit_price": 400,
       "reference_quantity": 1.0,
       "reference_unit_price": 400.0
      }
     ],
     "assumptions": [
      "The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement.",
      "Tolerances applied: quantity 0.0%, price 0.0%."
     ],
     "matched_count": 3,
     "unmatched_count": 0,
     "correction_method": "DELTA"
    },
    "invoice_currency": "EUR",
```

### S07 — Which invoice does this PO relate to?

PO-61190 relates to invoice RFG-500712 (invoice_id 07d27347-bd5f-489e-852d-f2040d9f3423). The comparison outcome is "match"; invoice status is "COMPLETED" and the invoice currency is "USD" (flow_direction "INBOUND").

```json
{
 "attachment_comparison": {
  "reference": {
   "currency": "USD",
   "doc_date": "2026-06-10",
   "doc_type": "PURCHASE_ORDER",
   "doc_number": "PO-61190",
   "party_name": "Redwood Facilities Group",
   "grand_total": "1590.0"
  },
  "comparisons": [
   {
    "fields": [
     {
      "delta": "0.0",
      "field": "subtotal",
      "status": "match",
      "invoice_value": "1500.0",
      "reference_value": "1500.0"
     },
     {
      "delta": "0.0",
      "field": "tax_amount",
      "status": "match",
      "invoice_value": "90.0",
      "reference_value": "90.0"
     },
     {
      "delta": "0.0",
      "field": "grand_total",
      "status": "match",
      "invoice_value": "1590.0",
      "reference_value": "1590.0"
     }
    ],
    "outcome": "match",
    "invoice_id": "07d27347-bd5f-489e-852d-f2040d9f3423",
    "blocked_reason": null,
    "flow_direction": "INBOUND",
    "invoice_number": "RFG-500712",
    "invoice_status": "COMPLETED",
    "line_comparison": {
     "mode": "both",
     "policy": {
      "date_tolerance_days": 0,
      "price_tolerance_percent": 0.0,
      "quantity_tolerance_percent": 0.0
     },
     "unmatched": {
      "invoice_lines": [],
      "reference_lines": []
     },
     "line_items": [
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Janitorial services",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 1200,
       "quantity_delta": "0.0",
       "invoice_quantity": 1,
       "reference_amount": 1200.0,
       "invoice_unit_price": 1200,
       "reference_quantity": 1.0,
       "reference_unit_price": 1200.0
      },
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Supplies",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 300,
       "quantity_delta": "0.0",
       "invoice_quantity": 1,
       "reference_amount": 300.0,
       "invoice_unit_price": 300,
       "reference_quantity": 1.0,
       "reference_unit_price": 300.0
      }
     ],
     "assumptions": [
      "The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement.",
      "Tolerances applied: quantity 0.0%, price 0.0%."
     ],
     "matched_count": 2,
     "unmatched_count": 0,
     "correction_method": "DELTA"
    },
    "invoice_currency": "USD",
    "line_count_delta": 0,
    "invoice_line_count": 2,
    "reference_currency": "USD",
    "reference_line_count": 2
   }
  ],
  "blocked_count": 0,
  "compared_count": 1
 },
 "line_items": [
  {
   "uom": null,
   "status": "quantity_delta",
   "match_tier": "L2",
   "description": "Janitorial services",
   "price_delta": "0.0",
   "amount_delta": "0.0",
   "hsn_sac_code": null,
   "invoice_amount": 1200,
   "invoice_number": "RFG-500712",
   "quantity_delta"
```

### S08 — Did Bharat bill us what they quoted?

Short answer: No — the invoice does not match the quotation.

Details from the comparison (quotation QT-BL-2026-0455 vs invoice BL-2026-1450):
- Invoice: BL-2026-1450 (invoice_status: COMPLETED), currencies: reference_currency INR, invoice_currency INR.
- Grand total: reference_value 14010.0, invoice_value 14510.0, delta 500.0, status: invoice_higher.
- Subtotal: reference_value 13000.0, invoice_value 13500.0, delta 500.0, status: invoice_higher.
- Tax amount: reference_value 1010.0, invoice_value 1010.0, delta 0.0, status: match.
- Line counts: reference_line_count 3, invoice_line_count 3, line_count_delta 0; matched_count 3, unmatched_count 0.
- Line causing the variance: "Transport service" — reference_unit_price 9500.0 vs invoice_unit_price 10000, amount_delta 500.0. The other two lines ("Packing material" and "Handling and admin") show price and amount deltas of 0.0.
- Comparison method and notes: correction_method "DELTA". Assumptions: "The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement." and "Tolerances applied: quantity 0.0%, price 0.0%."

Conclusion drawn from the provided comparison: the invoice total is higher than the quotation by 500.0 INR, driven by a 500.0 INR higher unit price on the "Transport service" line; tax carried across unchanged.

```json
{
 "attachment_comparison": {
  "reference": {
   "currency": "INR",
   "doc_date": "2026-04-30",
   "doc_type": "QUOTATION",
   "doc_number": "QT-BL-2026-0455",
   "party_name": "Infinevo Cloud Pvt Ltd",
   "grand_total": "14010.0"
  },
  "comparisons": [
   {
    "fields": [
     {
      "delta": "500.0",
      "field": "subtotal",
      "status": "invoice_higher",
      "invoice_value": "13500.0",
      "reference_value": "13000.0"
     },
     {
      "delta": "0.0",
      "field": "tax_amount",
      "status": "match",
      "invoice_value": "1010.0",
      "reference_value": "1010.0"
     },
     {
      "delta": "500.0",
      "field": "grand_total",
      "status": "invoice_higher",
      "invoice_value": "14510.0",
      "reference_value": "14010.0"
     }
    ],
    "outcome": "variance",
    "invoice_id": "3fa77723-2529-4ce0-a028-ffb34bd288d1",
    "blocked_reason": null,
    "flow_direction": "INBOUND",
    "invoice_number": "BL-2026-1450",
    "invoice_status": "COMPLETED",
    "line_comparison": {
     "mode": "both",
     "policy": {
      "date_tolerance_days": 0,
      "price_tolerance_percent": 0.0,
      "quantity_tolerance_percent": 0.0
     },
     "unmatched": {
      "invoice_lines": [],
      "reference_lines": []
     },
     "line_items": [
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Transport service",
       "price_delta": "500.0",
       "amount_delta": "500.0",
       "hsn_sac_code": null,
       "invoice_amount": 10000,
       "quantity_delta": "0.0",
       "invoice_quantity": 1,
       "reference_amount": 9500.0,
       "invoice_unit_price": 10000,
       "reference_quantity": 1.0,
       "reference_unit_price": 9500.0
      },
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Packing material",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 2000,
       "quantity_delta": "0.0",
       "invoice_quantity": 1,
       "reference_amount": 2000.0,
       "invoice_unit_price": 2000,
       "reference_quantity": 1.0,
       "reference_unit_price": 2000.0
      },
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Handling and admin",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 1500,
       "quantity_delta": "0.0",
       "invoice_quantity": 1,
       "reference_amount": 1500.0,
       "invoice_unit_price": 1500,
       "reference_quantity": 1.0,
       "reference_unit_price": 1500.0
      }
     ],
     "assumptions": [
      "The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement.",
      "Tolerances applied: quantity 0.0%, price 0.0%."
     ],
     "matched_count": 3,
     "unmatched_count": 0,
     "correction_met
```

### S09 — How long was this quotation valid?

- The quotation states: "This quotation is valid for 30 days from the date above." (Page 1)
- The document date shown is "Date: 30 Apr 2026." (Page 1)

```json
{
 "evidence": [
  {
   "page": 1,
   "text": "[Document type: QUOTATION | Party: Infinevo Cloud Pvt Ltd | Document number: QT-BL-2026-0455 | Page 1]\nQUOTATION\nInfinevo Cloud Pvt Ltd\nTower B, Cyber Hub, Gurugram, HR 122002\nGSTIN 06AABCI5678F1Z9\nDocument No: QT-BL-2026-0455\nDate: 30 Apr 2026\nCurrency: INR\nFrom:\nBharat Logistics Pvt Ltd\nMumbai 400001\nGSTIN 27AACCB4321G1Z2\nItem\nDescription\nQty\nUnit Price (INR)\nAmount (INR)\n1\nTransport service\n1\n9,500.00\n9,500.00\n2\nPacking material\n1\n2,000.00\n2,000.00\n3\nHandling and admin\n1\n1,500.00\n1,500.00\nSubtotal: Rs 13,000.00\nGST (mixed 5/12/18%): Rs 1,010.00\nQuoted Total: Rs 14,010.00\nThis quotation is valid for 30 days from the date above.\nReference PO: PO-IN-3301\n",
   "distance": 0.56291425
  }
 ]
}
```

### S10 — Any difference between this quote and the Rhein invoice?

No — the comparison outcome is "match." Summary of what was compared:

- Reference: QUOTATION Q-RIT-2026-118 (doc_date 2026-05-20) vs Invoice RIT-2026-0456 (invoice_status: COMPLETED, flow_direction: INBOUND).
- Currencies: reference_currency = EUR, invoice_currency = EUR (no currency mismatch).
- Field-level results (all matched):
  - subtotal: reference_value 9200.0, invoice_value 9200.0, status: match
  - tax_amount: reference_value 228.0, invoice_value 228.0, status: match
  - grand_total: reference_value 9428.0, invoice_value 9428.0, status: match
- Line counts: reference_line_count 2, invoice_line_count 2, line_count_delta 0.
- Line-item matching:
  - Item 1: "Machinery parts (reverse charge, intra-EU B2B)" — match_tier L2; reference_quantity 1.0, invoice_quantity 1, quantity_delta 0.0; reference_unit_price 8000.0, invoice_unit_price 8000, reference_amount 8000.0, invoice_amount 8000, amount_delta 0.0; status: quantity_delta
  - Item 2: "Installation service (local, taxable)" — match_tier L2; reference_quantity 1.0, invoice_quantity 1, quantity_delta 0.0; reference_unit_price 1200.0, invoice_unit_price 1200, reference_amount 1200.0, invoice_amount 1200, amount_delta 0.0; status: quantity_delta
  - matched_count 2, unmatched_count 0
- Comparison metadata: correction_method = DELTA; assumptions: "The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement." and "Tolerances applied: quantity 0.0%, price 0.0%." Blocked_reason: null.

In short: all compared fields and line items match exactly according to the computed comparison.

```json
{
 "attachment_comparison": {
  "reference": {
   "currency": "EUR",
   "doc_date": "2026-05-20",
   "doc_type": "QUOTATION",
   "doc_number": "Q-RIT-2026-118",
   "party_name": "InvoiceEQ GmbH",
   "grand_total": "9428.0"
  },
  "comparisons": [
   {
    "fields": [
     {
      "delta": "0.0",
      "field": "subtotal",
      "status": "match",
      "invoice_value": "9200.0",
      "reference_value": "9200.0"
     },
     {
      "delta": "0.0",
      "field": "tax_amount",
      "status": "match",
      "invoice_value": "228.0",
      "reference_value": "228.0"
     },
     {
      "delta": "0.0",
      "field": "grand_total",
      "status": "match",
      "invoice_value": "9428.0",
      "reference_value": "9428.0"
     }
    ],
    "outcome": "match",
    "invoice_id": "7fc14428-acc1-4b50-b5b5-e1300e16b48c",
    "blocked_reason": null,
    "flow_direction": "INBOUND",
    "invoice_number": "RIT-2026-0456",
    "invoice_status": "COMPLETED",
    "line_comparison": {
     "mode": "both",
     "policy": {
      "date_tolerance_days": 0,
      "price_tolerance_percent": 0.0,
      "quantity_tolerance_percent": 0.0
     },
     "unmatched": {
      "invoice_lines": [],
      "reference_lines": []
     },
     "line_items": [
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Machinery parts (reverse charge, intra-EU B2B)",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 8000,
       "quantity_delta": "0.0",
       "invoice_quantity": 1,
       "reference_amount": 8000.0,
       "invoice_unit_price": 8000,
       "reference_quantity": 1.0,
       "reference_unit_price": 8000.0
      },
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Installation service (local, taxable)",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 1200,
       "quantity_delta": "0.0",
       "invoice_quantity": 1,
       "reference_amount": 1200.0,
       "invoice_unit_price": 1200,
       "reference_quantity": 1.0,
       "reference_unit_price": 1200.0
      }
     ],
     "assumptions": [
      "The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement.",
      "Tolerances applied: quantity 0.0%, price 0.0%."
     ],
     "matched_count": 2,
     "unmatched_count": 0,
     "correction_method": "DELTA"
    },
    "invoice_currency": "EUR",
    "line_count_delta": 0,
    "invoice_line_count": 2,
    "reference_currency": "EUR",
    "reference_line_count": 2
   }
  ],
  "blocked_count": 0,
  "compared_count": 1
 },
 "line_items": [
  {
   "uom": null,
   "status": "quantity_delta",
   "match_tier": "L2",
   "description": "Machinery parts (reverse charge, intra-EU B2B)",
   "price_delta": "0.0",
   "amount_delta": "0.0",
   "hsn_sac_code": null
```

### S11 — What is missing on the proforma versus the final invoice?

The proforma (PF-BRL-200981) has 2 line(s) while the final invoice (BRL-200981) has 3 line(s) — a difference of 1 line.

Missing from the proforma (i.e., present on the invoice but not on the proforma):
- Description: "Fuel surcharge"
  - quantity: 1
  - unit_price: 150
  - amount: 150

Matched lines: 2; Unmatched invoice lines: 1.

```json
{
 "attachment_comparison": {
  "reference": {
   "currency": "USD",
   "doc_date": "2026-06-08",
   "doc_type": "QUOTATION",
   "doc_number": "PF-BRL-200981",
   "party_name": "Blue Ridge Logistics",
   "grand_total": "2225.44"
  },
  "comparisons": [
   {
    "fields": [
     {
      "delta": "150.0",
      "field": "subtotal",
      "status": "invoice_higher",
      "invoice_value": "2225.0",
      "reference_value": "2075.0"
     },
     {
      "delta": "10.87",
      "field": "tax_amount",
      "status": "invoice_higher",
      "invoice_value": "161.31",
      "reference_value": "150.44"
     },
     {
      "delta": "160.87",
      "field": "grand_total",
      "status": "invoice_higher",
      "invoice_value": "2386.31",
      "reference_value": "2225.44"
     }
    ],
    "outcome": "variance",
    "invoice_id": "01ca6838-83fc-4844-8473-2488beb4a96e",
    "blocked_reason": null,
    "flow_direction": "INBOUND",
    "invoice_number": "BRL-200981",
    "invoice_status": "COMPLETED",
    "line_comparison": {
     "mode": "both",
     "policy": {
      "date_tolerance_days": 0,
      "price_tolerance_percent": 0.0,
      "quantity_tolerance_percent": 0.0
     },
     "unmatched": {
      "invoice_lines": [
       {
        "uom": null,
        "amount": 150,
        "quantity": 1,
        "unit_price": 150,
        "description": "Fuel surcharge",
        "line_number": null,
        "hsn_sac_code": null
       }
      ],
      "reference_lines": []
     },
     "line_items": [
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Freight service",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 2000,
       "quantity_delta": "0.0",
       "invoice_quantity": 1,
       "reference_amount": 2000.0,
       "invoice_unit_price": 2000,
       "reference_quantity": 1.0,
       "reference_unit_price": 2000.0
      },
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Handling fee",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 75,
       "quantity_delta": "0.0",
       "invoice_quantity": 1,
       "reference_amount": 75.0,
       "invoice_unit_price": 75,
       "reference_quantity": 1.0,
       "reference_unit_price": 75.0
      }
     ],
     "assumptions": [
      "The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement.",
      "Tolerances applied: quantity 0.0%, price 0.0%."
     ],
     "matched_count": 2,
     "unmatched_count": 1,
     "correction_method": "DELTA"
    },
    "invoice_currency": "USD",
    "line_count_delta": 1,
    "invoice_line_count": 3,
    "reference_currency": "USD",
    "reference_line_count": 2
   }
  ],
  "blocked_count": 0,
  "compared_count": 1
 },
 "suggested_actions": [
  {
   "hre
```

### S12 — After applying this credit note, what do we still owe Konkan on KE-2026-0089?

Remaining amount owed on KE-2026-0089 (currency INR): 50100.0

Supporting data from the comparison:
- Comparison outcome: variance.
- Reference (credit note CN-2026-0102) grand_total: 3000.0; reference line count: 1.
- Invoice KE-2026-0089 grand_total: 53100.0; invoice subtotal: 45000.0; invoice tax_amount: 8100.0; invoice line count: 2.
- Grand-total delta shown by the comparison: 50100.0 (status: invoice_higher).
- Line-level detail (unmatched): reference line — "Credit against invoice KE-2026-0089 - consulting scope reduction" amount 3000.0; invoice lines — "Consulting services (import, RCM applicable)" amount 50000 and "Credit note adjustment CN-2026-0091" amount -5000.

Note: the comparison marks the credit note's tax_amount as missing.

```json
{
 "attachment_comparison": {
  "reference": {
   "currency": "INR",
   "doc_date": "2026-06-30",
   "doc_type": "OTHER",
   "doc_number": "CN-2026-0102",
   "party_name": "Konkan Exports Pvt Ltd",
   "grand_total": "3000.0"
  },
  "comparisons": [
   {
    "fields": [
     {
      "delta": "42000.0",
      "field": "subtotal",
      "status": "invoice_higher",
      "invoice_value": "45000.0",
      "reference_value": "3000.0"
     },
     {
      "delta": null,
      "field": "tax_amount",
      "status": "missing",
      "invoice_value": "8100.0",
      "reference_value": null
     },
     {
      "delta": "50100.0",
      "field": "grand_total",
      "status": "invoice_higher",
      "invoice_value": "53100.0",
      "reference_value": "3000.0"
     }
    ],
    "outcome": "variance",
    "invoice_id": "bff6c286-815d-4081-be21-82f17558bbc0",
    "blocked_reason": null,
    "flow_direction": "INBOUND",
    "invoice_number": "KE-2026-0089",
    "invoice_status": "COMPLETED",
    "line_comparison": {
     "mode": "money",
     "policy": {
      "date_tolerance_days": 0,
      "price_tolerance_percent": 0.0,
      "quantity_tolerance_percent": 0.0
     },
     "unmatched": {
      "invoice_lines": [
       {
        "uom": null,
        "amount": 50000,
        "quantity": 1,
        "unit_price": 50000,
        "description": "Consulting services (import, RCM applicable)",
        "line_number": null,
        "hsn_sac_code": null
       },
       {
        "uom": null,
        "amount": -5000,
        "quantity": 1,
        "unit_price": -5000,
        "description": "Credit note adjustment CN-2026-0091",
        "line_number": null,
        "hsn_sac_code": null
       }
      ],
      "reference_lines": [
       {
        "uom": null,
        "amount": 3000.0,
        "quantity": 1.0,
        "unit_price": 3000.0,
        "description": "Credit against invoice KE-2026-0089 - consulting scope reduction",
        "line_number": 1,
        "hsn_sac_code": null
       }
      ]
     },
     "line_items": [],
     "assumptions": [
      "The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement.",
      "Tolerances applied: quantity 0.0%, price 0.0%."
     ],
     "matched_count": 0,
     "unmatched_count": 3,
     "correction_method": "DELTA"
    },
    "invoice_currency": "INR",
    "line_count_delta": 1,
    "invoice_line_count": 2,
    "reference_currency": "INR",
    "reference_line_count": 1
   }
  ],
  "blocked_count": 0,
  "compared_count": 1
 },
 "suggested_actions": [
  {
   "href": "/trainer/bff6c286-815d-4081-be21-82f17558bbc0",
   "label": "Open this invoice in the Trainer to correct extraction",
   "method": "GET",
   "endpoint": "/api/v1/trainer/invoice/bff6c286-815d-4081-be21-82f17558bbc0",
   "precondition": "none (read-only destination)"
  }
 ],
 "unmatched": {
  "invoice_lines": [
   {
    "uom": null,
    "amount": 50000,
    "quantity": 1,
    "unit
```

### S13 — What is Milano adding with this debit note?

- Milano is adding a freight charge described as: "Freight - express delivery, not included on invoice MCS-2026-0890" (Qty 1, Unit Price EUR 120.00). — (page 1)
- The document shows "Debit amount: EUR 120.00" and notes it "Applies to invoice: MCS-2026-0890" and is "Payable with the referenced invoice." — (page 1)

```json
{
 "evidence": [
  {
   "page": 1,
   "text": "[Document type: OTHER | Party: Milano Componenti SRL | Document number: DN-MCS-2026-014 | Page 1]\nDEBIT NOTE\nInvoiceEQ GmbH\nFriedrichstrasse 100, 10117 Berlin, Germany\nVAT DE123456789\nDocument No: DN-MCS-2026-014\nDate: 25 Jun 2026\nCurrency: EUR\nFrom:\nMilano Componenti SRL\nMilan, Italy\nItem\nDescription\nQty\nUnit Price (EUR)\nAmount (EUR)\n1\nFreight - express delivery, not included on invoice MCS-2026-0890\n1\n120.00\n120.00\nDebit amount: EUR 120.00\nApplies to invoice: MCS-2026-0890\nPayable with the referenced invoice.\n",
   "distance": 0.32476506
  }
 ]
}
```

### S14 — How many beams were delivered versus how many were invoiced?

- What the document shows (page 1):
  - "Steel beams" — Qty: 18. (page 1)
  - "2 beams back-ordered, to follow." (page 1)

- What the document does not show:
  - This file is a delivery note (Document type: OTHER) and does not contain an invoice line stating an "invoiced" quantity or billed quantity. I looked at page 1.

```json
{
 "evidence": [
  {
   "page": 1,
   "text": "[Document type: OTHER | Party: InvoiceEQ Inc. | Document number: DN-TSD-77812 | Page 1]\nDELIVERY NOTE\nInvoiceEQ Inc.\n500 Market St, San Francisco, CA 94105\nDocument No: DN-TSD-77812\nDate: Jun 20, 2026\nCurrency: USD\nShip to:\nInvoiceEQ Inc.\n500 Market St, San Francisco, CA 94105\nItem\nDescription\nQty\nUnit Price (USD)\nAmount (USD)\n1\nSteel beams\n18\n0.00\n0.00\n2\nSteel plates\n15\n0.00\n0.00\nShipped against PO-71004. Carrier: Keystone Freight.\nReceived by: ____________ Date: ________\n2 beams back-ordered, to follow.\n",
   "distance": 0.34410226
  }
 ]
}
```

### S15 — Does the GRN quantity match the Patel invoice?

Yes. Evidence from the computed comparison:
- line_comparison.mode = "quantity".
- reference_line_count = 2 and invoice_line_count = 2; matched_count = 2; unmatched_count = 0.
- For both invoice lines: reference_quantity = 1.0, invoice_quantity = 1, quantity_delta = "0.0", status = "quantity_delta".

Note: the overall comparison outcome is "incomplete" (some monetary fields on the reference are marked "missing": subtotal, tax_amount, grand_total).

```json
{
 "attachment_comparison": {
  "reference": {
   "currency": "INR",
   "doc_date": "2026-06-21",
   "doc_type": "OTHER",
   "doc_number": "GRN-2026-0388",
   "party_name": "Patel Enterprises",
   "grand_total": null
  },
  "comparisons": [
   {
    "fields": [
     {
      "delta": null,
      "field": "subtotal",
      "status": "missing",
      "invoice_value": "30000.0",
      "reference_value": null
     },
     {
      "delta": null,
      "field": "tax_amount",
      "status": "missing",
      "invoice_value": "5700.0",
      "reference_value": null
     },
     {
      "delta": null,
      "field": "grand_total",
      "status": "missing",
      "invoice_value": "35700.0",
      "reference_value": null
     }
    ],
    "outcome": "incomplete",
    "invoice_id": "ff49ad08-0f6f-4fcf-aff5-f0e4242147c1",
    "blocked_reason": null,
    "flow_direction": "INBOUND",
    "invoice_number": "PE-2026-0512",
    "invoice_status": "COMPLETED",
    "line_comparison": {
     "mode": "quantity",
     "policy": {
      "date_tolerance_days": 0,
      "price_tolerance_percent": 0.0,
      "quantity_tolerance_percent": 0.0
     },
     "unmatched": {
      "invoice_lines": [],
      "reference_lines": []
     },
     "line_items": [
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Raw materials",
       "price_delta": "25000.0",
       "amount_delta": "25000.0",
       "hsn_sac_code": null,
       "invoice_amount": 25000,
       "quantity_delta": "0.0",
       "invoice_quantity": 1,
       "reference_amount": 0.0,
       "invoice_unit_price": 25000,
       "reference_quantity": 1.0,
       "reference_unit_price": 0.0
      },
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Processing charges",
       "price_delta": "5000.0",
       "amount_delta": "5000.0",
       "hsn_sac_code": null,
       "invoice_amount": 5000,
       "quantity_delta": "0.0",
       "invoice_quantity": 1,
       "reference_amount": 0.0,
       "invoice_unit_price": 5000,
       "reference_quantity": 1.0,
       "reference_unit_price": 0.0
      }
     ],
     "assumptions": [
      "The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement.",
      "Tolerances applied: quantity 0.0%, price 0.0%."
     ],
     "matched_count": 2,
     "unmatched_count": 0,
     "correction_method": "DELTA"
    },
    "invoice_currency": "INR",
    "line_count_delta": 0,
    "invoice_line_count": 2,
    "reference_currency": "INR",
    "reference_line_count": 2
   }
  ],
  "blocked_count": 0,
  "compared_count": 1
 },
 "suggested_actions": [
  {
   "href": "/trainer/ff49ad08-0f6f-4fcf-aff5-f0e4242147c1",
   "label": "Open this invoice in the Trainer to correct extraction",
   "method": "GET",
   "endpoint": "/api/v1/trainer/invoice/ff49ad08-0f6f-4fcf-aff5-f0e4242147c1",
   "precondition": "none (r
```

### S16 — Which lines did Cafe Fournitures confirm?

Short answer
- The reference (OC-CFS-2026-0301 from Cafe Fournitures SARL) contains one confirmed line: "Office furniture".

Comparison vs invoice(s)
- Matched invoice: CFS-2026-0921 (invoice_id b6e82aad-c658-47b6-948e-6973f08de1a1)
  - invoice_status: COMPLETED
  - flow_direction: INBOUND
  - outcome: variance
  - reference currency: EUR, invoice currency: EUR

Field-level variances (verbatim from the comparison)
- subtotal: reference_value "1000.0" — invoice_value "1300.0" — delta "300.0" — status "invoice_higher"
- tax_amount: reference_value "200.0" — invoice_value "216.5" — delta "16.5" — status "invoice_higher"
- grand_total: reference_value "1200.0" — invoice_value "1516.5" — delta "316.5" — status "invoice_higher"

Line-level details (verbatim)
- reference_line_count: 1
- invoice_line_count: 2
- line_count_delta: 1
- matched_count: 1
  - Matched line (match_tier "L2")
    - description: "Office furniture"
    - reference_quantity: 1.0 — invoice_quantity: 1 — quantity_delta: "0.0" — status: "quantity_delta"
    - reference_unit_price: 1000.0 — invoice_unit_price: 1000 — price_delta: "0.0"
    - reference_amount: 1000.0 — invoice_amount: 1000 — amount_delta: "0.0"
- unmatched_count: 1
  - Unmatched invoice line:
    - description: "Printed materials / books (reduced rate)"
    - quantity: 1
    - unit_price: 300
    - amount: 300

Other comparison metadata (verbatim)
- correction_method: "DELTA"
- assumptions: 
  - "The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement."
  - "Tolerances applied: quantity 0.0%, price 0.0%."
- blocked_reason: null

Summary
- Cafe Fournitures confirmed a single line: "Office furniture" (reference has 1 line). The matched invoice line for that item matches quantities and unit price, but the invoice contains one additional unmatched line ("Printed materials / books (reduced rate)") and therefore subtotal, tax_amount and grand_total on the invoice are higher (see the verbatim values above).

```json
{
 "attachment_comparison": {
  "reference": {
   "currency": "EUR",
   "doc_date": "2026-06-05",
   "doc_type": "OTHER",
   "doc_number": "OC-CFS-2026-0301",
   "party_name": "Cafe Fournitures SARL",
   "grand_total": "1200.0"
  },
  "comparisons": [
   {
    "fields": [
     {
      "delta": "300.0",
      "field": "subtotal",
      "status": "invoice_higher",
      "invoice_value": "1300.0",
      "reference_value": "1000.0"
     },
     {
      "delta": "16.5",
      "field": "tax_amount",
      "status": "invoice_higher",
      "invoice_value": "216.5",
      "reference_value": "200.0"
     },
     {
      "delta": "316.5",
      "field": "grand_total",
      "status": "invoice_higher",
      "invoice_value": "1516.5",
      "reference_value": "1200.0"
     }
    ],
    "outcome": "variance",
    "invoice_id": "b6e82aad-c658-47b6-948e-6973f08de1a1",
    "blocked_reason": null,
    "flow_direction": "INBOUND",
    "invoice_number": "CFS-2026-0921",
    "invoice_status": "COMPLETED",
    "line_comparison": {
     "mode": "both",
     "policy": {
      "date_tolerance_days": 0,
      "price_tolerance_percent": 0.0,
      "quantity_tolerance_percent": 0.0
     },
     "unmatched": {
      "invoice_lines": [
       {
        "uom": null,
        "amount": 300,
        "quantity": 1,
        "unit_price": 300,
        "description": "Printed materials / books (reduced rate)",
        "line_number": null,
        "hsn_sac_code": null
       }
      ],
      "reference_lines": []
     },
     "line_items": [
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Office furniture",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 1000,
       "quantity_delta": "0.0",
       "invoice_quantity": 1,
       "reference_amount": 1000.0,
       "invoice_unit_price": 1000,
       "reference_quantity": 1.0,
       "reference_unit_price": 1000.0
      }
     ],
     "assumptions": [
      "The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement.",
      "Tolerances applied: quantity 0.0%, price 0.0%."
     ],
     "matched_count": 1,
     "unmatched_count": 1,
     "correction_method": "DELTA"
    },
    "invoice_currency": "EUR",
    "line_count_delta": 1,
    "invoice_line_count": 2,
    "reference_currency": "EUR",
    "reference_line_count": 1
   }
  ],
  "blocked_count": 0,
  "compared_count": 1
 },
 "suggested_actions": [
  {
   "href": "/trainer/b6e82aad-c658-47b6-948e-6973f08de1a1",
   "label": "Open this invoice in the Trainer to correct extraction",
   "method": "GET",
   "endpoint": "/api/v1/trainer/invoice/b6e82aad-c658-47b6-948e-6973f08de1a1",
   "precondition": "none (read-only destination)"
  }
 ],
 "line_items": [
  {
   "uom": null,
   "status": "quantity_delta",
   "match_tier": "L2",
   "description": "Office furniture",
   "price_delta": "0
```

### S17 — Did our customer pay the full amount on this receipt?

Short answer: No.

Details from the comparison
- Reference (receipt) RCPT-NP-2026-0611 grand_total: 2450.0 USD
- Matched invoice IEQ-US-9001 grand_total: 2500.0 USD (invoice_status: COMPLETED)
- Outcome: variance — invoice is higher by 50.0 USD (delta: 50.0)
- The receipt did not state subtotal (status: missing) and did not state tax_amount (invoice shows tax_amount 0.0, receipt tax_amount status: missing).
- Line matching: matched_count = 0, unmatched_count = 2.
  - Reference line: "Payment for invoice IEQ-US-9001", quantity 1.0, unit_price 2450.0, amount 2450.0
  - Invoice line: "SaaS subscription - Enterprise tier (1 mo)", quantity 1, unit_price 2500, amount 2500
- Comparison assumptions: correction_method = DELTA; tolerances: quantity 0.0%, price 0.0%.

Conclusion: The receipt total (2450.0 USD) does not match the invoice total (2500.0 USD); the invoice amount is 50.0 USD higher.

```json
{
 "attachment_comparison": {
  "reference": {
   "currency": "USD",
   "doc_date": "2026-07-02",
   "doc_type": "OTHER",
   "doc_number": "RCPT-NP-2026-0611",
   "party_name": "NorthPoint Retail Inc.",
   "grand_total": "2450.0"
  },
  "comparisons": [
   {
    "fields": [
     {
      "delta": null,
      "field": "subtotal",
      "status": "missing",
      "invoice_value": "2500.0",
      "reference_value": null
     },
     {
      "delta": null,
      "field": "tax_amount",
      "status": "missing",
      "invoice_value": "0.0",
      "reference_value": null
     },
     {
      "delta": "50.0",
      "field": "grand_total",
      "status": "invoice_higher",
      "invoice_value": "2500.0",
      "reference_value": "2450.0"
     }
    ],
    "outcome": "variance",
    "invoice_id": "3693a07f-c3c4-4b94-a9f8-fb2a58d5ad41",
    "blocked_reason": null,
    "flow_direction": "OUTBOUND",
    "invoice_number": "IEQ-US-9001",
    "invoice_status": "COMPLETED",
    "line_comparison": {
     "mode": "both",
     "policy": {
      "date_tolerance_days": 0,
      "price_tolerance_percent": 0.0,
      "quantity_tolerance_percent": 0.0
     },
     "unmatched": {
      "invoice_lines": [
       {
        "uom": null,
        "amount": 2500,
        "quantity": 1,
        "unit_price": 2500,
        "description": "SaaS subscription - Enterprise tier (1 mo)",
        "line_number": null,
        "hsn_sac_code": null
       }
      ],
      "reference_lines": [
       {
        "uom": null,
        "amount": 2450.0,
        "quantity": 1.0,
        "unit_price": 2450.0,
        "description": "Payment for invoice IEQ-US-9001",
        "line_number": 1,
        "hsn_sac_code": null
       }
      ]
     },
     "line_items": [],
     "assumptions": [
      "The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement.",
      "Tolerances applied: quantity 0.0%, price 0.0%."
     ],
     "matched_count": 0,
     "unmatched_count": 2,
     "correction_method": "DELTA"
    },
    "invoice_currency": "USD",
    "line_count_delta": 0,
    "invoice_line_count": 1,
    "reference_currency": "USD",
    "reference_line_count": 1
   }
  ],
  "blocked_count": 0,
  "compared_count": 1
 },
 "suggested_actions": [
  {
   "href": "/outbound-auditor/3693a07f-c3c4-4b94-a9f8-fb2a58d5ad41",
   "label": "Resolve the audit findings on this invoice",
   "method": "PUT",
   "endpoint": "/api/v1/outbound-audit/3693a07f-c3c4-4b94-a9f8-fb2a58d5ad41/resolve",
   "precondition": "none (does not change status)"
  }
 ],
 "unmatched": {
  "invoice_lines": [
   {
    "uom": null,
    "amount": 2500,
    "quantity": 1,
    "unit_price": 2500,
    "description": "SaaS subscription - Enterprise tier (1 mo)",
    "line_number": null,
    "hsn_sac_code": null,
    "invoice_number": "IEQ-US-9001"
   }
  ],
  "reference_lines": [
   {
    "uom": null,
    "amount": 2450.0,
    "quantity": 1.0,
    "unit_price": 2450.0,
```

### S18 — Reconcile this statement against our records.

I checked 4 reference(s) on that document against your invoices. 2 agree. 1 do not — the differences are in the table below. 1 reference invoices I have no record of.

```json
{
 "reconciliation": {
  "mode": "list_reconcile",
  "deductions": [],
  "party_name": "InvoiceEQ GmbH",
  "references": [
   {
    "delta": null,
    "outcome": "found_matching",
    "doc_number": "CFS-2026-0921",
    "invoice_id": "b6e82aad-c658-47b6-948e-6973f08de1a1",
    "stated_amount": 1516.5,
    "stated_status": null,
    "invoice_amount": 1516.5,
    "invoice_status": "COMPLETED"
   },
   {
    "delta": null,
    "outcome": "found_matching",
    "doc_number": "RIT-2026-0456",
    "invoice_id": "7fc14428-acc1-4b50-b5b5-e1300e16b48c",
    "stated_amount": 9428.0,
    "stated_status": null,
    "invoice_amount": 9428.0,
    "invoice_status": "COMPLETED"
   },
   {
    "delta": "100.0",
    "outcome": "amount_mismatch",
    "doc_number": "MCS-2026-0890",
    "invoice_id": "b82f7952-d193-483a-b2a7-1345c4180bc9",
    "stated_amount": 6000.0,
    "stated_status": null,
    "invoice_amount": 6100.0,
    "invoice_status": "COMPLETED"
   },
   {
    "delta": null,
    "outcome": "not_found",
    "doc_number": "BMN-2026-0999",
    "invoice_id": null
   }
  ],
  "unreferenced_invoices": []
 }
}
```

### S19 — Which invoice on this statement do we not have on file?

I checked 4 reference(s) on that document against your invoices. 2 agree. 1 do not — the differences are in the table below. 1 reference invoices I have no record of.

```json
{
 "reconciliation": {
  "mode": "list_reconcile",
  "deductions": [],
  "party_name": "InvoiceEQ GmbH",
  "references": [
   {
    "delta": null,
    "outcome": "found_matching",
    "doc_number": "CFS-2026-0921",
    "invoice_id": "b6e82aad-c658-47b6-948e-6973f08de1a1",
    "stated_amount": 1516.5,
    "stated_status": null,
    "invoice_amount": 1516.5,
    "invoice_status": "COMPLETED"
   },
   {
    "delta": null,
    "outcome": "found_matching",
    "doc_number": "RIT-2026-0456",
    "invoice_id": "7fc14428-acc1-4b50-b5b5-e1300e16b48c",
    "stated_amount": 9428.0,
    "stated_status": null,
    "invoice_amount": 9428.0,
    "invoice_status": "COMPLETED"
   },
   {
    "delta": "100.0",
    "outcome": "amount_mismatch",
    "doc_number": "MCS-2026-0890",
    "invoice_id": "b82f7952-d193-483a-b2a7-1345c4180bc9",
    "stated_amount": 6000.0,
    "stated_status": null,
    "invoice_amount": 6100.0,
    "invoice_status": "COMPLETED"
   },
   {
    "delta": null,
    "outcome": "not_found",
    "doc_number": "BMN-2026-0999",
    "invoice_id": null
   }
  ],
  "unreferenced_invoices": []
 }
}
```

### S20 — Is this remittance short on any invoice?

I checked 2 reference(s) on that document against your invoices. 1 agree. 1 do not — the differences are in the table below.

```json
{
 "reconciliation": {
  "mode": "list_reconcile",
  "deductions": [],
  "party_name": "Infinevo Cloud Pvt Ltd",
  "references": [
   {
    "delta": null,
    "outcome": "found_matching",
    "doc_number": "BL-2026-1450",
    "invoice_id": "3fa77723-2529-4ce0-a028-ffb34bd288d1",
    "stated_amount": 14510.0,
    "stated_status": null,
    "invoice_amount": 14510.0,
    "invoice_status": "COMPLETED"
   },
   {
    "delta": "1000.0",
    "outcome": "amount_mismatch",
    "doc_number": "KE-2026-0089",
    "invoice_id": "bff6c286-815d-4081-be21-82f17558bbc0",
    "stated_amount": 52100.0,
    "stated_status": null,
    "invoice_amount": 53100.0,
    "invoice_status": "COMPLETED"
   }
  ],
  "unreferenced_invoices": []
 }
}
```

### S21 — What payment terms did we agree with Cascade?

- Payment terms: "Net 45 days from invoice date." (Page 1)  
- Early payment discount: "2% if paid within 10 days." (Page 1)

```json
{
 "evidence": [
  {
   "page": 1,
   "text": "[Document type: CONTRACT | Party: Cascade Manufacturing Co | Document number: MSA-CMC-2026-01 | Page 1]\nMASTER SUPPLY AGREEMENT\nInvoiceEQ Inc.\n500 Market St, San Francisco, CA 94105\nDocument No: MSA-CMC-2026-01\nDate: Mar 1, 2026\nCurrency: USD\nSupplier:\nCascade Manufacturing Co\nPortland, OR 97201\n1. Payment terms: Net 45 days from invoice date.\n2. Early payment discount: 2% if paid within 10 days.\n3. Pricing: unit prices quoted under this agreement are valid for 90 days from the agreement date.\n4. Governing law: State of Oregon.\n",
   "distance": 0.37243453
  }
 ]
}
```

### S22 — Is the Cascade invoice dated 2026-06-14 within the contract's price validity window?

Short answer: No — the invoice dated 2026-06-14 falls outside the contract’s 90‑day price validity window.

- The contract states: "Pricing: unit prices quoted under this agreement are valid for 90 days from the agreement date." (Page 1).  
- Computed dates (from the contract): the 90‑day window ends 2026-05-30, and 2026-06-14 is OUTSIDE that window by 15 days.

```json
{
 "evidence": [
  {
   "page": 1,
   "text": "[Document type: CONTRACT | Party: Cascade Manufacturing Co | Document number: MSA-CMC-2026-01 | Page 1]\nMASTER SUPPLY AGREEMENT\nInvoiceEQ Inc.\n500 Market St, San Francisco, CA 94105\nDocument No: MSA-CMC-2026-01\nDate: Mar 1, 2026\nCurrency: USD\nSupplier:\nCascade Manufacturing Co\nPortland, OR 97201\n1. Payment terms: Net 45 days from invoice date.\n2. Early payment discount: 2% if paid within 10 days.\n3. Pricing: unit prices quoted under this agreement are valid for 90 days from the agreement date.\n4. Governing law: State of Oregon.\n",
   "distance": 0.3329646
  }
 ]
}
```

### S23 — Check this document against my invoices.

Would you like me to read the document, or compare it to your invoices?

```json
{
 "attachment_clarification": {
  "message": "Would you like me to read the document, or compare it to your invoices?",
  "options": [
   {
    "label": "Read the document",
    "intent": "read"
   },
   {
    "label": "Compare to my invoices",
    "intent": "compare"
   }
  ]
 }
}
```

### S24 — Does the Deccan invoice match this PO?

Short answer: No — outcome = "variance".

Key comparison facts (from the computed comparison)
- PO: "PO-IN-5502" (party: Deccan Chemicals Ltd, currency: INR)
- Invoice: "DC-2026-1120" (invoice_status: COMPLETED, flow_direction: INBOUND, invoice_currency: INR)
- Overall outcome: "variance" with grand_total reference_value "25252.0" vs invoice_value "25783.0" (delta "531.0", status "invoice_higher").
- Breakdowns:
  - subtotal: reference_value "21400.0" vs invoice_value "21850.0" (delta "450.0", status "invoice_higher")
  - tax_amount: reference_value "3852.0" vs invoice_value "3933.0" (delta "81.0", status "invoice_higher")
- Line-level matches: 3 matched lines, 0 unmatched lines (matched_count "3", unmatched_count "0"); reference_line_count "3", invoice_line_count "3", line_count_delta 0.
- Line-item detail highlights:
  - "Industrial solvents": reference_quantity "200.0" vs invoice_quantity 200 (quantity_delta "0.0"), reference_amount "17000.0" vs invoice_amount 17000 (amount_delta "0.0").
  - "Catalysts": reference_quantity "8.0" vs invoice_quantity 10 (quantity_delta "2.0"), reference_amount "3600.0" vs invoice_amount 4050 (amount_delta "450.0").
  - "Packaging": reference_quantity "1.0" vs invoice_quantity 1 (quantity_delta "0.0"), reference_amount "800.0" vs invoice_amount 800 (amount_delta "0.0").
- Comparison settings/assumptions: correction_method "DELTA"; assumptions include that the document is treated as an adjustment and tolerances applied: quantity 0.0%, price 0.0%.

Blocked_reason is null.

```json
{
 "attachment_comparison": {
  "reference": {
   "currency": "INR",
   "doc_date": "2026-06-15",
   "doc_type": "PURCHASE_ORDER",
   "doc_number": "PO-IN-5502",
   "party_name": "Deccan Chemicals Ltd",
   "grand_total": "25252.0"
  },
  "comparisons": [
   {
    "fields": [
     {
      "delta": "450.0",
      "field": "subtotal",
      "status": "invoice_higher",
      "invoice_value": "21850.0",
      "reference_value": "21400.0"
     },
     {
      "delta": "81.0",
      "field": "tax_amount",
      "status": "invoice_higher",
      "invoice_value": "3933.0",
      "reference_value": "3852.0"
     },
     {
      "delta": "531.0",
      "field": "grand_total",
      "status": "invoice_higher",
      "invoice_value": "25783.0",
      "reference_value": "25252.0"
     }
    ],
    "outcome": "variance",
    "invoice_id": "d0e4bc50-8d37-4f75-b6f2-b6ae680a54d1",
    "blocked_reason": null,
    "flow_direction": "INBOUND",
    "invoice_number": "DC-2026-1120",
    "invoice_status": "COMPLETED",
    "line_comparison": {
     "mode": "both",
     "policy": {
      "date_tolerance_days": 0,
      "price_tolerance_percent": 0.0,
      "quantity_tolerance_percent": 0.0
     },
     "unmatched": {
      "invoice_lines": [],
      "reference_lines": []
     },
     "line_items": [
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Industrial solvents",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 17000,
       "quantity_delta": "0.0",
       "invoice_quantity": 200,
       "reference_amount": 17000.0,
       "invoice_unit_price": 85,
       "reference_quantity": 200.0,
       "reference_unit_price": 85.0
      },
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Catalysts",
       "price_delta": "0.0",
       "amount_delta": "450.0",
       "hsn_sac_code": null,
       "invoice_amount": 4050,
       "quantity_delta": "2.0",
       "invoice_quantity": 10,
       "reference_amount": 3600.0,
       "invoice_unit_price": 450,
       "reference_quantity": 8.0,
       "reference_unit_price": 450.0
      },
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Packaging",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 800,
       "quantity_delta": "0.0",
       "invoice_quantity": 1,
       "reference_amount": 800.0,
       "invoice_unit_price": 800,
       "reference_quantity": 1.0,
       "reference_unit_price": 800.0
      }
     ],
     "assumptions": [
      "The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement.",
      "Tolerances applied: quantity 0.0%, price 0.0%."
     ],
     "matched_count": 3,
     "unmatched_count": 0,
     "correction_method": "DELTA"
```

### S25 — Does the Deccan invoice match this PO?

Short answer: No — the invoice does not exactly match the PO. The comparison outcome is "variance".

Key comparison metadata
- PO: PO-IN-5502 (party: Deccan Chemicals Ltd, doc_date: 2026-06-15).
- Matched invoice: DC-2026-1120 (invoice_id d0e4bc50-8d37-4f75-b6f2-b6ae680a54d1), invoice_status: COMPLETED, flow_direction: INBOUND.
- Outcome: variance.
- Reference currency: INR; Invoice currency: INR (no currency_mismatch).
- blocked_reason: null.

Field-level differences (as returned)
- subtotal — reference_value: "21400.0" | invoice_value: "21850.0" | delta: "450.0" | status: "invoice_higher"
- tax_amount — reference_value: "3852.0" | invoice_value: "3933.0" | delta: "81.0" | status: "invoice_higher"
- grand_total — reference_value: "25252.0" | invoice_value: "25783.0" | delta: "531.0" | status: "invoice_higher"

Line counts and matching
- reference_line_count: 3 | invoice_line_count: 3 | line_count_delta: 0
- matched_count: 3 | unmatched_count: 0

Line-item details (as returned)
1) Description: "Industrial solvents"
   - reference_quantity: 200.0 | invoice_quantity: 200 | quantity_delta: "0.0"
   - reference_unit_price: 85.0 | invoice_unit_price: 85 | price_delta: "0.0"
   - reference_amount: 17000.0 | invoice_amount: 17000 | amount_delta: "0.0"
   - match_tier: L2 | status: "quantity_delta"

2) Description: "Catalysts"
   - reference_quantity: 8.0 | invoice_quantity: 10 | quantity_delta: "2.0"
   - reference_unit_price: 450.0 | invoice_unit_price: 450 | price_delta: "0.0"
   - reference_amount: 3600.0 | invoice_amount: 4050 | amount_delta: "450.0"
   - match_tier: L2 | status: "quantity_delta"

3) Description: "Packaging"
   - reference_quantity: 1.0 | invoice_quantity: 1 | quantity_delta: "0.0"
   - reference_unit_price: 800.0 | invoice_unit_price: 800 | price_delta: "0.0"
   - reference_amount: 800.0 | invoice_amount: 800 | amount_delta: "0.0"
   - match_tier: L2 | status: "quantity_delta"

Comparison policy and assumptions (as returned)
- mode: "both"
- policy tolerances: quantity_tolerance_percent: 0.0, price_tolerance_percent: 0.0, date_tolerance_days: 0
- correction_method: "DELTA"
- assumptions: ["The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement.", "Tolerances applied: quantity 0.0%, price 0.0%."]

Summary statement
- All three PO lines were matched to invoice lines, but the invoice is higher than the PO: subtotal, tax_amount, and grand_total are higher (see the field-level deltas above). The main line-level driver shown is the "Catalysts" line (reference_quantity 8.0 vs invoice_quantity 10; amount_delta "450.0"), which corresponds to the differences reported.

```json
{
 "attachment_comparison": {
  "reference": {
   "currency": "INR",
   "doc_date": "2026-06-15",
   "doc_type": "PURCHASE_ORDER",
   "doc_number": "PO-IN-5502",
   "party_name": "Deccan Chemicals Ltd",
   "grand_total": "25252.0"
  },
  "comparisons": [
   {
    "fields": [
     {
      "delta": "450.0",
      "field": "subtotal",
      "status": "invoice_higher",
      "invoice_value": "21850.0",
      "reference_value": "21400.0"
     },
     {
      "delta": "81.0",
      "field": "tax_amount",
      "status": "invoice_higher",
      "invoice_value": "3933.0",
      "reference_value": "3852.0"
     },
     {
      "delta": "531.0",
      "field": "grand_total",
      "status": "invoice_higher",
      "invoice_value": "25783.0",
      "reference_value": "25252.0"
     }
    ],
    "outcome": "variance",
    "invoice_id": "d0e4bc50-8d37-4f75-b6f2-b6ae680a54d1",
    "blocked_reason": null,
    "flow_direction": "INBOUND",
    "invoice_number": "DC-2026-1120",
    "invoice_status": "COMPLETED",
    "line_comparison": {
     "mode": "both",
     "policy": {
      "date_tolerance_days": 0,
      "price_tolerance_percent": 0.0,
      "quantity_tolerance_percent": 0.0
     },
     "unmatched": {
      "invoice_lines": [],
      "reference_lines": []
     },
     "line_items": [
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Industrial solvents",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 17000,
       "quantity_delta": "0.0",
       "invoice_quantity": 200,
       "reference_amount": 17000.0,
       "invoice_unit_price": 85,
       "reference_quantity": 200.0,
       "reference_unit_price": 85.0
      },
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Catalysts",
       "price_delta": "0.0",
       "amount_delta": "450.0",
       "hsn_sac_code": null,
       "invoice_amount": 4050,
       "quantity_delta": "2.0",
       "invoice_quantity": 10,
       "reference_amount": 3600.0,
       "invoice_unit_price": 450,
       "reference_quantity": 8.0,
       "reference_unit_price": 450.0
      },
      {
       "uom": null,
       "status": "quantity_delta",
       "match_tier": "L2",
       "description": "Packaging",
       "price_delta": "0.0",
       "amount_delta": "0.0",
       "hsn_sac_code": null,
       "invoice_amount": 800,
       "quantity_delta": "0.0",
       "invoice_quantity": 1,
       "reference_amount": 800.0,
       "invoice_unit_price": 800,
       "reference_quantity": 1.0,
       "reference_unit_price": 800.0
      }
     ],
     "assumptions": [
      "The document does not state how it corrects the original, so this comparison treats it as an adjustment (DELTA) rather than a replacement.",
      "Tolerances applied: quantity 0.0%, price 0.0%."
     ],
     "matched_count": 3,
     "unmatched_count": 0,
     "correction_method": "DELTA"
```
