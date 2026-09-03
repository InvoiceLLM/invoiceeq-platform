# Ground Truth -- PROFORMA_INVOICE fixtures (Feature 27 Task F)

Source PDFs: Prod_Invoice_LLM/apps/invoice-be/tests/fixtures/doc_types/proforma_invoice/
{india_inbound,eu_inbound,us_inbound}/ -- 3 files, all synthetic (see ../MANIFEST.md for
full provenance). This is the section 7 cell with zero prior fixtures anywhere in the
repo before this pass -- INVOICE already has real fixtures at tests/india/, tests/eu/,
tests/us/, but PROFORMA_INVOICE did not exist as a distinct type until E4.

All three fixtures are genuine proformas per section 7 explicit warning (must be a
genuine proforma, not a quotation relabelled): each carries a committed buyer PO
reference (not an open-ended offer, which is what would make it a QUOTATION) and an
explicit textual disclaimer that it is not a tax document and not a demand for payment
(what would make it silently indistinguishable from an INVOICE).

## Expected classification and extraction

| File | Region | Printed title (evidence phrase) | Expected doc_type | Expected family (E4) | Prices printed | Grand total printed |
|---|---|---|---|---|---|---|
| IN-PI-01_proforma_invoice.pdf | India | PROFORMA INVOICE | PROFORMA_INVOICE | Money | Yes | Yes (estimated) |
| EU-PI-01_proforma_rechnung.pdf | EU (Germany) | PROFORMA-RECHNUNG / PROFORMA INVOICE (bilingual) | PROFORMA_INVOICE | Money | Yes | Yes (estimated, 0 percent reverse-charge tax) |
| US-PI-01_pro_forma_invoice.pdf | US | PRO FORMA INVOICE | PROFORMA_INVOICE | Money | Yes | Yes (estimated) |

## Flat line-item table

| File | Line Description | Qty | Unit Price (printed) | Line Amount (printed) | Currency |
|---|---|---|---|---|---|
| IN-PI-01 | Forged Steel Flange - 6 inch | 500 | Rs 1,250.00 | Rs 6,25,000.00 | INR |
| IN-PI-01 | Forged Steel Flange - 8 inch | 300 | Rs 1,850.00 | Rs 5,55,000.00 | INR |
| EU-PI-01 | Frequenzumrichter FU-750 | 15 | 620,00 EUR | 9.300,00 EUR | EUR |
| EU-PI-01 | Bediengeraet BG-10 | 15 | 145,00 EUR | 2.175,00 EUR | EUR |
| US-PI-01 | Stainless Steel Fastener Kit, Grade 316 | 800 | $4.25 | $3,400.00 | USD |
| US-PI-01 | Industrial Gasket Set, Model IG-90 | 200 | $11.50 | $2,300.00 | USD |

## Header fields and totals (not per-line, repeated per document)

- IN-PI-01: Vendor Vishwakarma Forgings Ltd, GSTIN 06AAECV4321R1Z8. Buyer Infinevo
  Cloud Pvt Ltd, GSTIN 06AABCI5678F1Z9. Proforma Invoice No PI-2026-1187, Date
  2026-08-05, Buyer PO Reference PO-IN-7710, Validity 30 days, Incoterms FOB Nhava
  Sheva. Subtotal Rs 11,80,000.00, Estimated GST (18 percent) Rs 2,12,400.00,
  Estimated Total Rs 13,92,400.00 -- all figures explicitly labelled "Estimated" and the
  document states GST is payable on the final Tax Invoice, not this document.
- EU-PI-01: Vendor Bergmann Elektrotechnik GmbH, USt-IdNr. DE145278933. Buyer Meridian
  Automation Ltd, VAT No GB741852963 (cross-border UK buyer). Proforma-Rechnung Nr.
  PF-2026-0562, Datum 2026-08-09, Bestellnummer PO-EU-4415, Gueltigkeit 21 Tage,
  Incoterms EXW Nuernberg. Subtotal 11.475,00 EUR, USt (Reverse Charge,
  innergemeinschaftlich) 0,00 EUR, Gesamtbetrag 11.475,00 EUR.
- US-PI-01: Vendor Cascade Industrial Supply LLC, EIN 91-2233445. Buyer Northgate
  Manufacturing Inc. Pro Forma Invoice No PF-2026-2209, Date 08/07/2026, Buyer PO
  Reference PO-US-8841, Validity 15 days. Subtotal $5,700.00, Estimated Freight and
  Insurance $310.00, Estimated Total $6,010.00. Framed explicitly "FOR CUSTOMS PURPOSES
  ONLY" -- the common US usage pattern, distinct from the India/EU advance-payment
  framing.

## Verification-plan relevance (feature_27_generic_extraction.md section 9)

- T-C-1/T-C-2 (classifier): PROFORMA INVOICE and PRO FORMA INVOICE are exact/near-exact
  E4 canonical-name matches and should hit the deterministic pass; PROFORMA-RECHNUNG is
  the harder case (a German-labelled synonym not explicitly listed in the E4 table
  the way DELIVERY_NOTE regional synonyms are), and is a reasonable candidate for
  exercising the LLM-fallback ambiguity path once G2 lands -- flag this specifically
  when task V is run, since it may reveal whether the E4 synonym table needs a German
  PROFORMA_INVOICE entry added.
- E4 family table: PROFORMA_INVOICE is Money family, so full arithmetic verification
  (line-item sum vs subtotal, subtotal plus tax vs grand total) applies -- unlike
  DELIVERY_NOTE. All three fixtures here are internally arithmetically consistent by
  construction (500 times 1,250.00 = 6,25,000.00, and so on for every line), so none of
  them should raise a discrepancy alert once verified end to end.
- These fixtures also directly support A2 T-R-6 in one respect: they confirm what a
  genuine (non-quotation, non-invoice) proforma looks like on paper, which is the
  reference a coder or reviewer needs when deciding whether resolve_extraction_profile
  correctly keeps PROFORMA_INVOICE on the INVOICE-family schema (A2: PROFORMA_INVOICE
  is explicitly listed as one of the four INVOICE-family types, so it must NOT be
  routed to the GENERIC profile).

## Data-quality flags

None. All three fixtures are internally consistent by construction (synthetic,
generated for this purpose, no seeded defects). Task F did not have time in this pass to
build an erroneous-PROFORMA_INVOICE variant; flagged as a real gap, not an oversight --
see ../MANIFEST.md "Remaining section 7 cells".
