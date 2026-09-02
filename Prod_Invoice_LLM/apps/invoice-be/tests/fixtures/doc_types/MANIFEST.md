# Doc-Type Fixture Manifest -- Feature 27 Task F

Owner: functional-tester. **2026-09-02 Dispatch B revision**: brought coverage from 2/10 to
10/10 section-7 doc types (5 -> 16 files) and added the classifier-confidence column N2 asks
for. Corrects one stale claim from the original pass, below.

**Correction of fact (stale claim from the original 2026-09-02 pass, now fixed):** the
original manifest stated `services/document_type_classifier.py` "does not exist yet... G2 has
not landed" and deferred the confidence column on that basis. That is no longer true --
`document_type_classifier.py` shipped (tracker Gap 369, G2) with a full, working
`classify_doc_type()` and `tests/test_document_type_classifier.py` covering it. The
confidence column below is measured against that real, shipped module (and, where the
deterministic pass did not resolve, the real deployed Azure OpenAI `gpt-5-mini` model --
**not** `MockInvoiceLLM`; `.env` carries live Azure OpenAI credentials in this dev
environment).

## Coverage summary (Dispatch B, 2026-09-02)

| Type | Cells covered | Status |
|---|---|---|
| QUOTATION | India (1) | 1/3 regions, 1/1 doc types now has coverage |
| PROFORMA_INVOICE | India, EU, US (3) | 3/3 -- unchanged from original pass |
| PURCHASE_ORDER | India, US (2) | 2/3 regions |
| CONTRACT | India (no grand total), EU (no grand total) (2) | 2/3 regions; **required no-grand-total case satisfied by both** |
| DELIVERY_NOTE | India, EU, US (3) | 3/3 regions -- US added this pass |
| GRN | India (1) | 1/1 (India-only cell per section 7's own table) |
| INVOICE | reused from tests/india/, tests/eu/, tests/us/ | no new fixtures needed (section 7 explicit) |
| CREDIT_NOTE | India (1) | 1/3 regions |
| DEBIT_NOTE | India (1) | 1/3 regions |
| OTHER | India bill of lading + India e-way bill (2) | 2/2 (T-C-4's required pair) |

**10 of 10 section-7 doc types now have at least one fixture** (up from 2 of 10). Total
fixture files: **16** (5 from the original pass + 11 new this pass). This is deliberately
**not** the full 30-40 file regional matrix section 7's own table lists in full -- per this
dispatch's explicit scope, one defensible sample per doc type, full regional breadth left to
the taxonomy wave.

## Files produced -- original pass (unchanged from 2026-09-02 first session)

| Filename | Path | doc_type | Family (E4) | Region | Real or synthetic | Expected doc_type_evidence phrase |
|---|---|---|---|---|---|---|
| IN-DN-01_delivery_challan_no_prices.pdf | delivery_note/india_inbound/ | DELIVERY_NOTE | Quantity | India | Synthetic | "DELIVERY CHALLAN" |
| EU-DN-01_lieferschein_no_prices.pdf | delivery_note/eu_inbound/ | DELIVERY_NOTE | Quantity | EU (Germany) | Synthetic | "LIEFERSCHEIN" |
| IN-PI-01_proforma_invoice.pdf | proforma_invoice/india_inbound/ | PROFORMA_INVOICE | Money | India | Synthetic | "PROFORMA INVOICE" |
| EU-PI-01_proforma_rechnung.pdf | proforma_invoice/eu_inbound/ | PROFORMA_INVOICE | Money | EU (Germany) | Synthetic | "PROFORMA-RECHNUNG" / "PROFORMA INVOICE" |
| US-PI-01_pro_forma_invoice.pdf | proforma_invoice/us_inbound/ | PROFORMA_INVOICE | Money | US | Synthetic | "PRO FORMA INVOICE" |

Provenance/anonymisation for these 5: unchanged from the original pass -- all synthetic, all
party names/GSTINs/VAT IDs/EINs invented, real regional layout conventions and number
formats (Indian lakh-grouping, EU comma-decimal). See each type's `ground_truth_*.md` for
full detail.

## Files produced -- Dispatch B, 2026-09-02 (11 new)

| Filename | Path | doc_type | Family (E4) | Region | Real or synthetic | Expected doc_type_evidence phrase |
|---|---|---|---|---|---|---|
| US-DN-01_packing_slip_no_prices.pdf | delivery_note/us_inbound/ | DELIVERY_NOTE | Quantity | US | Synthetic | "PACKING SLIP" |
| IN-PO-01_purchase_order.pdf | purchase_order/india_inbound/ | PURCHASE_ORDER | Commitment | India | Synthetic | "PURCHASE ORDER" |
| US-PO-01_purchase_order.pdf | purchase_order/us_inbound/ | PURCHASE_ORDER | Commitment | US | Synthetic | "PURCHASE ORDER" |
| IN-CT-01_rate_contract_no_total.pdf | contract/india_inbound/ | CONTRACT | Commitment | India | Synthetic | "RATE CONTRACT" |
| EU-CT-01_rahmenvertrag_no_total.pdf | contract/eu_inbound/ | CONTRACT | Commitment | EU (Germany) | Synthetic | "RAHMENVERTRAG" |
| IN-QT-01_quotation.pdf | quotation/india_inbound/ | QUOTATION | Commitment (provisional -- see classifier module docstring naming note 2) | India | Synthetic | "QUOTATION" |
| IN-GRN-01_goods_receipt_note.pdf | grn/india_inbound/ | GRN | Quantity | India | Synthetic (per E4, explicitly acceptable for this low-frequency/internal-origin type) | "GOODS RECEIPT NOTE" |
| IN-OTH-01_bill_of_lading.pdf | other/india_inbound/ | OTHER | Other/advisory | India (export) | Synthetic | "BILL OF LADING" |
| IN-OTH-02_eway_bill_quoting_tax_invoice.pdf | other/india_inbound/ | OTHER | Other/advisory | India | Synthetic | "e-Way Bill" (quotes but is not itself "Tax Invoice No INV-2026-0447" in its body) |
| IN-CN-01_credit_note.pdf | credit_note/india_inbound/ | CREDIT_NOTE | Money | India | Synthetic | "CREDIT NOTE" |
| IN-DB-01_debit_note.pdf | debit_note/india_inbound/ | DEBIT_NOTE | Money | India | Synthetic | "DEBIT NOTE" |

All 11 are synthetic, all party names/GSTINs/VAT IDs/EINs/document numbers invented, no real
customer data. Several fixtures deliberately share invented entities/PO numbers/invoice
numbers across type boundaries (documented per-file in each type's `ground_truth_*.md`) to
give the fixture set a realistic commercial-lifecycle continuity (quote -> PO -> rate
contract -> delivery -> GRN -> credit/debit note), matching E4's stated lifecycle ordering --
the numbers are not meant to arithmetically reconcile across documents, only to read as the
same real-world transaction chain. Full per-file provenance, layout justification and ground
truth (expected line items, header fields, verification-plan relevance) is in each type's own
`ground_truth_line_items.md`, not duplicated here.

## Classifier confidence per fixture -- N2's requested distribution (2026-09-02, Dispatch B)

Measured by running the real `classify_doc_type()` from `services/document_type_classifier.py`
over every one of the 16 fixtures: OCR-equivalent text extracted from each PDF via PyMuPDF
(`page.get_text()`, concatenated across pages), fed to `classify_doc_type(text, {})` exactly
as `queue_worker/handlers.py` would feed it OCR's `content` string. Where the deterministic
pass did not resolve, the real deployed Azure OpenAI `gpt-5-mini` model answered (credentials
present in `.env`; `[LLM] initialising Azure OpenAI: gpt-5-mini on
https://openai-invoicellm-dev.openai.azure.com/` printed live during the run) -- not
`MockInvoiceLLM`.

| File | Expected doc_type | Actual doc_type | Correct? | Method | Confidence | Reason |
|---|---|---|---|---|---|---|
| IN-DN-01_delivery_challan_no_prices.pdf | DELIVERY_NOTE | DELIVERY_NOTE | Yes | deterministic | 1.00 | -- |
| EU-DN-01_lieferschein_no_prices.pdf | DELIVERY_NOTE | DELIVERY_NOTE | Yes | deterministic | 1.00 | -- |
| US-DN-01_packing_slip_no_prices.pdf | DELIVERY_NOTE | DELIVERY_NOTE | Yes | deterministic | 1.00 | -- |
| IN-PI-01_proforma_invoice.pdf | PROFORMA_INVOICE | PROFORMA_INVOICE | Yes | deterministic | 1.00 | -- |
| EU-PI-01_proforma_rechnung.pdf | PROFORMA_INVOICE | PROFORMA_INVOICE | Yes | deterministic | 1.00 | -- |
| US-PI-01_pro_forma_invoice.pdf | PROFORMA_INVOICE | PROFORMA_INVOICE | Yes | deterministic | 1.00 | -- |
| IN-PO-01_purchase_order.pdf | PURCHASE_ORDER | PURCHASE_ORDER | Yes | deterministic | 1.00 | -- |
| US-PO-01_purchase_order.pdf | PURCHASE_ORDER | PURCHASE_ORDER | Yes | deterministic | 1.00 | -- |
| IN-CT-01_rate_contract_no_total.pdf | CONTRACT | CONTRACT | Yes | deterministic | 1.00 | -- |
| EU-CT-01_rahmenvertrag_no_total.pdf | CONTRACT | CONTRACT | Yes | **llm** (real Azure OpenAI call) | **0.95** | -- |
| IN-QT-01_quotation.pdf | QUOTATION | QUOTATION | Yes | deterministic | 1.00 | -- |
| IN-GRN-01_goods_receipt_note.pdf | GRN | GRN | Yes | deterministic | 1.00 | -- |
| IN-OTH-01_bill_of_lading.pdf | OTHER | OTHER | Yes | **llm** (real Azure OpenAI call) | **0.90** | -- |
| IN-OTH-02_eway_bill_quoting_tax_invoice.pdf | OTHER | OTHER | Yes | **llm** (real Azure OpenAI call) | **0.92** | -- |
| IN-CN-01_credit_note.pdf | CREDIT_NOTE | CREDIT_NOTE | Yes | deterministic | 1.00 | -- |
| IN-DB-01_debit_note.pdf | DEBIT_NOTE | DEBIT_NOTE | Yes | deterministic | 1.00 | -- |

**16/16 correct. 13/16 resolved deterministically (confidence 1.0, no LLM call, no cost). 3/16
required the real LLM fallback** (EU-CT-01's German-only "RAHMENVERTRAG" title, which is not
in `_DOC_TYPE_SYNONYMS`; both OTHER fixtures, since `_DOC_TYPE_SYNONYMS["OTHER"]` is
intentionally always empty per E5). All 3 LLM-path confidences landed in **0.90-0.95** --
comfortably above the `0.6` threshold, with a wide margin (0.30-0.35) and zero real data
points observed between 0.6 and 0.90.

**Functional-tester's recommendation on the N2 / `DOC_TYPE_CONFIDENCE_THRESHOLD` question
(0.6 today):** the real data gathered here does not show 0.6 producing any false
`OTHER`-demotion or any near-miss -- every real LLM call this pass answered confidently and
correctly, nowhere near the boundary. That is evidence the threshold is **not currently
causing harm**, but it is *not* evidence that 0.6 is well-calibrated, because this pass never
produced a genuinely hard or ambiguous real document for the LLM to hesitate on -- every
fixture here has an unambiguous printed title band by construction (the fixture set's own
realism bar, not a weakness of the classifier). **Recommendation: raise the threshold
moderately, to roughly 0.75-0.8, rather than leaving it at 0.6.** Reasoning: (1) every
confident real answer observed clusters at 0.90+, so raising the floor to 0.75-0.8 would not
have demoted any of these 16 real fixtures to `OTHER`; (2) a wider margin between "accepted"
and "not confident enough" gives more protection against a genuinely low-confidence guess on
a real-world document this fixture set does not contain (e.g. a badly-scanned or
multi-language title band), which is exactly the failure mode E7's "a wrong type is worse
than no type" design principle is guarding against; (3) 0.6 was chosen with zero data before
any fixture existed (N2's own framing) and this pass's data, while limited to 3 LLM-path
points, gives no reason to keep it that low. This is a directional recommendation, not a
final calibration -- it is based on 3 real LLM-path data points, all of which happen to be
confident and correct, so it cannot rule out a genuinely ambiguous production document
scoring in the 0.6-0.85 range and correctly deserving to pass. Whether to move the constant,
and to what exact value, is senior-dev's call per this dispatch's own instruction; this
manifest supplies the first real distribution to judge it against, which is what N2 asked
for.

## Rules followed (section 7)

- No real customer data -- all 16 fixtures are synthetic, declared as such throughout.
- Synthetic-must-be-realistic: real layout conventions, real regional field vocabulary and
  number formats (Indian GSTIN/HSN/lakh-grouping, German VAT-ID/comma-decimal, US EIN/customs
  framing), real title-band wording taken from or matching the E4 synonym table where
  applicable, real legal/statutory boilerplate where a real document would carry it (CGST
  Section 34 citations, B/L negotiable-original clause, e-Way Bill Rule 138 citation) -- not
  schematic placeholders.
- Ground truth recorded per file: expected doc_type, expected family, expected
  doc_type_evidence phrase -- in each type's own `ground_truth_line_items.md`.
- CONTRACT's required no-grand-total case: satisfied by **both** CONTRACT fixtures (India
  rate contract, EU Rahmenvertrag), not just one.
- OTHER's required bill-of-lading + e-way-bill pair (T-C-4): satisfied, and the e-way-bill
  fixture additionally quotes a tax-invoice number in its body -- the harder real-world case
  the dispatch specifically asked for.
- DELIVERY_NOTE's three-region proof: now complete (India, Germany, US).
- Classifier confidence recorded per file, against the real classifier and real deployed LLM,
  not a fabricated or mocked number -- satisfies N2.

## Deliberately not attempted this pass (out of Dispatch B's scope, for the taxonomy wave)

- The full 30-40 file regional matrix section 7's own table lists (EU/US QUOTATION, EU/US
  CONTRACT beyond the one pair, EU/US CREDIT_NOTE/DEBIT_NOTE, India's E-Invoice IRN+QR /
  Bill of Supply sub-cases of INVOICE, etc.).
- Erroneous/seeded-defect variants for any new type (the pattern `tests/india/`, `tests/eu/`
  use for INVOICE -- `*_erroneous_simple/medium/complex`). Every fixture in this manifest is
  internally consistent by construction; none exercises a discrepancy-detection path.
- Real (non-synthetic) samples for GRN or any OTHER-family transport document -- section 11
  already flags real GRN/DDT sourcing as a procurement problem, not an engineering one.
