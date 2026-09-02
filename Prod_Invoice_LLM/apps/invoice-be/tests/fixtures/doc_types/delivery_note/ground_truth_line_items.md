# Ground Truth -- DELIVERY_NOTE fixtures (Feature 27 Task F)

Source PDFs: Prod_Invoice_LLM/apps/invoice-be/tests/fixtures/doc_types/delivery_note/
{india_inbound,eu_inbound,us_inbound}/ -- 3 files, all synthetic (see ../MANIFEST.md for full
provenance). All three fixtures deliberately carry NO price fields at all -- this is the
section 7 required case for the quantity-family rubric (T-R-1: quantities present, no
arithmetic alert, no missing-total alert). **Dispatch B (2026-09-02) added the third,
US-region "Packing Slip" file, completing the three-region proof section 7 recommends**
(India + Germany were sourced in the original pass; US was flagged "recommended, not yet
sourced").

## Expected classification and extraction

| File | Region | Printed title (evidence phrase) | Expected doc_type | Expected family (E4) | Prices printed | Line count |
|---|---|---|---|---|---|---|
| IN-DN-01_delivery_challan_no_prices.pdf | India | DELIVERY CHALLAN | DELIVERY_NOTE | Quantity | No | 3 |
| EU-DN-01_lieferschein_no_prices.pdf | EU (Germany) | LIEFERSCHEIN | DELIVERY_NOTE | Quantity | No | 3 |
| US-DN-01_packing_slip_no_prices.pdf | US | PACKING SLIP | DELIVERY_NOTE | Quantity | No | 2 |

## Flat line-item table

| File | Line Description | Qty | UOM | HSN/reference |
|---|---|---|---|---|
| IN-DN-01 | CNC Machined Bracket - Type A | 250 | Nos | HSN 8479 |
| IN-DN-01 | CNC Machined Bracket - Type B | 120 | Nos | HSN 8479 |
| IN-DN-01 | Mounting Plate Assembly | 60 | Nos | HSN 8479 |
| EU-DN-01 | Hydraulikzylinder HZ-400 | 40 | Stk | -- |
| EU-DN-01 | Dichtungssatz HZ-400 | 80 | Stk | -- |
| EU-DN-01 | Montageplatte Typ C | 20 | Stk | -- |
| US-DN-01 | Industrial Conveyor Belt, Model CB-500 | 10 | EA | -- |
| US-DN-01 | Replacement Roller Assembly | 40 | EA | -- |

## Header fields (not per-line, repeated per document)

- IN-DN-01: Party (vendor/shipper) Ashoka Precision Components Pvt Ltd, GSTIN
  27AAJCA9988P1Z3. Consignee Infinevo Cloud Pvt Ltd, GSTIN 06AABCI5678F1Z9. Challan No
  DC-2026-0871, Challan Date 2026-08-14, PO Reference PO-IN-6102, Vehicle No
  MH-12-AB-4471. No subtotal, no tax, no grand total printed anywhere on the document --
  this absence is correct and expected, not a defect (E4 quantity family: "price fields
  are optional and frequently absent by design").
- EU-DN-01: Party (vendor/shipper) Muller Praezisionstechnik GmbH, USt-IdNr.
  DE813456712. Empfaenger (recipient) Nordwind Handels GmbH, USt-IdNr. DE298471166.
  Lieferschein-Nr. LS-2026-4471, Lieferdatum 2026-08-11, Bestellnummer PO-EU-3390. No
  subtotal, no tax, no grand total printed -- same expectation as above.
- US-DN-01: Party (shipper) Cascade Industrial Supply LLC. Ship To Northgate Manufacturing
  Inc., 220 Commerce Park Blvd, Austin, TX 78701, USA. Packing Slip No PS-2026-3390, Ship
  Date 09/20/2026, Order Reference PO-US-8841 (the same PO number used in
  `../purchase_order/us_inbound/US-PO-01`, a deliberate cross-fixture continuity: this
  packing slip represents the physical shipment against that PO), Carrier/Tracking No FedEx
  Freight 881204471. No prices printed -- same expectation as above.

## Verification-plan relevance (feature_27_generic_extraction.md section 9)

- T-R-1 (a DELIVERY_NOTE with quantities and no prices produces zero arithmetic alerts
  and a passing status): all three fixtures here are the direct input for this test once G5
  lands.
- T-R-7 (a DELIVERY_NOTE produces no low_confidence_field alerts even when
  ocr_result field_confidence contains low scores for VendorName/InvoiceTotal): these
  fixtures are the realistic case that scenario is built to guard, since
  prebuilt-invoice will force-fit VendorName/InvoiceTotal fields onto a document that
  states neither.
- T-C-1 (deterministic synonym-pass classification, no LLM call): DELIVERY CHALLAN,
  LIEFERSCHEIN and PACKING SLIP are all exact E4 synonym-table entries. **Confirmed against
  the real classifier, 2026-09-02** (see ../MANIFEST.md): all three
  `doc_type_method=deterministic`, `doc_type_confidence=1.0`.

## Data-quality flags

None. All three fixtures are internally consistent by construction (synthetic, generated for
this purpose, no seeded defects) -- unlike tests/india/, tests/eu/ which deliberately
carry seeded correct/erroneous pairs. No erroneous-DELIVERY_NOTE variant built yet (e.g. a
challan with a fabricated qty mismatch); flagged as a real gap, not an oversight -- see
../MANIFEST.md "Remaining section 7 cells".
