# Ground Truth -- CONTRACT fixtures (Feature 27 Task F, Dispatch B)

Source PDFs: `../contract/{india_inbound,eu_inbound}/` -- 2 files, both synthetic (see
`../MANIFEST.md`). **Both fixtures deliberately carry NO grand total** -- this is section 7's
explicit required case and the direct input for T-R-2 ("a CONTRACT with no grand total
produces no missing-total alert"). COMMITMENT family (E4).

## Expected classification and extraction

| File | Region | Printed title (evidence phrase) | Expected doc_type | Expected family (E4) | Grand total printed | Classification path |
|---|---|---|---|---|---|---|
| IN-CT-01_rate_contract_no_total.pdf | India | RATE CONTRACT | CONTRACT | Commitment | **No** | Deterministic ("rate contract" is an exact `_DOC_TYPE_SYNONYMS` entry) |
| EU-CT-01_rahmenvertrag_no_total.pdf | EU (Germany) | RAHMENVERTRAG | CONTRACT | Commitment | **No** | **LLM fallback** -- "Rahmenvertrag" is NOT in `_DOC_TYPE_SYNONYMS` (only the English "framework agreement" is listed; see the module's own "SCOPE, STATED HONESTLY" comment) |

This pair is deliberately the one place in this fixture set that proves both classification
paths for the same doc_type on the same requirement (no-grand-total CONTRACT): India hits
the deterministic pass, Germany forces a real (not mocked) LLM call. **Measured against the
real classifier + real Azure OpenAI, 2026-09-02** (see `../MANIFEST.md`): IN-CT-01 ->
`deterministic`, confidence 1.0; EU-CT-01 -> `llm`, confidence 0.95, evidence exactly
"RAHMENVERTRAG". The LLM call succeeded and answered correctly well above the 0.6 threshold.

## Flat "line item" table (unit rates only -- no quantities, no line amounts, by design)

| File | Line Description | Unit Rate | UOM/Basis |
|---|---|---|---|
| IN-CT-01 | Forged Steel Flange - 6 inch | Rs 1,150.00 (excl. GST) | Nos |
| IN-CT-01 | Forged Steel Flange - 8 inch | Rs 1,700.00 (excl. GST) | Nos |
| EU-CT-01 | Wartungsdienstleistung - Standardanlage (maintenance, standard plant) | 480,00 EUR | pro Einsatz (per call-out) |
| EU-CT-01 | Wartungsdienstleistung - Grossanlage (maintenance, large plant) | 950,00 EUR | pro Einsatz (per call-out) |

## Header fields (not per-line, repeated per document)

- IN-CT-01: Buyer Infinevo Cloud Pvt Ltd, GSTIN 06AABCI5678F1Z9. Vendor Vishwakarma Forgings
  Ltd, GSTIN 06AAECV4321R1Z8. Rate Contract No RC-IN-2026-014, Effective Date 2026-09-01,
  Validity Period 12 months. Explicit text: "states no order quantity and no total contract
  value... determined by individual Release Orders." Termination: 30 days' written notice.
- EU-CT-01: Buyer Nordwind Handels GmbH, USt-IdNr. DE298471166. Vendor (Lieferant) Muller
  Praezisionstechnik GmbH, USt-IdNr. DE813456712. Rahmenvertrag-Nr. RV-2026-0091,
  Vertragsbeginn 01.09.2026, Laufzeit 24 Monate. Explicit text: "nennt keine Bestellmenge und
  keinen Gesamtwert" (states no order quantity and no total value). Termination
  (Kuendigung): 60 days' notice to month end.

## Verification-plan relevance (feature_27_generic_extraction.md section 9)

- **T-R-2, the direct subject of this pair**: "a CONTRACT with no grand total produces no
  missing-total alert." Both fixtures have zero grand total, zero subtotal, zero tax line --
  a naive money-family check would flag both as missing every arithmetic field; the
  COMMITMENT-family rubric must not.
- T-C-1 (India, deterministic) vs T-C-2-adjacent (Germany, real LLM fallback, not the
  invented-value negative case but the *positive* confident-in-vocabulary case
  `test_a_confident_in_vocabulary_answer_from_the_fallback_is_kept` mirrors).
- N2 (confidence calibration): EU-CT-01 is one of only 3 real (non-mocked) LLM-path data
  points in this fixture set -- see `../MANIFEST.md` for the full distribution and the
  functional-tester recommendation on the 0.6 threshold.
- Open question flagged for founder/senior-dev, not resolved here: should "rahmenvertrag" be
  added to `_DOC_TYPE_SYNONYMS["CONTRACT"]` as a deterministic entry? This fixture shows the
  LLM fallback currently handles it correctly and confidently (0.95), so there is no
  correctness defect -- only a cost question (one avoidable LLM call per German-titled
  framework agreement).

## Data-quality flags

None. Both fixtures are internally consistent by construction (synthetic, no seeded
defects, no amounts printed to be inconsistent). No erroneous-CONTRACT variant built this
pass; flagged as a real gap for the taxonomy wave, not an oversight.
