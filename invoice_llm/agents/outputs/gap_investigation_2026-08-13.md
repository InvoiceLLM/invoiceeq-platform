# Gap Investigation — InvoiceEQ Ground-Truth Test Run

**Date:** 2026-08-13
**Scope:** Investigation and root-cause tracing only. No application code was modified in this pass. Founder approval required before implementation begins on any item below.
**Method:** Direct code reads of the current (post-merge) codebase, plus one read-only Postgres query against the local ground-truth test database (the real extraction result already produced by this session's live Azure OCR + Azure OpenAI run) to obtain hard evidence for Gap 222. No fixtures were re-run and no endpoints were re-invoked beyond that one read-only query.

---

## Gap 220 — Outbound invoices skip line-item math verification

**Hypothesis:** Outbound (AR/sales) invoices don't get the same subtotal-reconciliation check inbound invoices get, so arithmetic errors on outbound line items go undetected.

**What I found:** Confirmed, unchanged from the earlier investigation pass. `outbound_extraction_agent.py`'s `verify_node()` deliberately imports only `verify_grand_total_in_source_text`, `verify_line_item_amounts_in_source_text`, `verify_tax_amount_in_source_text`, and `verify_field_confidence` — it never calls `verify_line_items_math`/`verify_totals_math`. The code carries an explicit comment explaining why: `OutboundInvoiceExtractionSchema` has no `subtotal` field (a v1 scope cut), so those checks would always be a no-op if included.

**Code references:**
- `agents/outbound_extraction_agent.py:37-46` — `OutboundInvoiceExtractionSchema`, no `subtotal` field
- `agents/outbound_extraction_agent.py:133-175` — `verify_node()`, exclusion + explanatory comment (~150-155)

**Confidence:** confirmed
**Suggested owner:** senior-dev (invoice-be) — either add `subtotal` to the outbound schema and wire in `verify_line_items_math`, or get an explicit product decision that outbound doesn't need this check (self-generated customer-facing invoices carry different audit risk than vendor-submitted ones). Needs a product call either way, not just a code change.

---

## Gap 221 — SQL-routed chat answers ignore tenant Chat Response Style

**Hypothesis:** Tenant-configured chat style (response length/tone/custom instructions) has no effect on SQL-routed chat answers.

**What I found:** Confirmed, unchanged. 13/13 live ground-truth chat prompts routed to SQL in this session's test run. `{style_block}` (built by `_get_chat_style_block()`) is injected into the SQL route's schema-building `system_prompt` — which only generates SQL text internally and is never shown to the user — instead of into `summary_prompt`, which produces the actual reply. As a result, tenant chat-style settings are structurally inert for the route that handled 100% of this session's test traffic.

**Code references:**
- `agents/query_agent.py` ~line 670 — SQL-generation `system_prompt`, where `{style_block}` is currently (mis)injected
- `agents/query_agent.py` ~line 719 — `summary_prompt`, the correct injection target, currently missing it

**Confidence:** confirmed
**Suggested owner:** senior-dev (invoice-be) — move the `{style_block}` injection from the SQL-generation prompt to the summary prompt. Small, well-scoped fix.

---

## Gap 222 — Negative/credit-note line loses its sign during LLM extraction (root cause now fully confirmed)

**Hypothesis (this pass, upgraded from "investigate"):** A credit-note line's negative amount is mishandled somewhere in the line-sum reconciliation check, producing a false `AUDIT_REQUIRED` on IN-IN-03 (`Line items sum (55000.00) does not match subtotal (45000.00)`).

**What I found:** The bug is **not** in `verify_line_items_math`. I read the full function body (`utils/verification_tools.py:16-95`) — the sum at line 82 is a plain, unmodified `sum(float(item.get("amount") or 0.0) for item in items)`. No `abs()`, no sign flip. Given correctly-signed input (50,000 + −5,000), it would compute 45,000 and pass silently. I also grepped the entire invoice-be codebase for `abs(` and confirmed nothing strips the sign from line-item amounts anywhere in extraction, persistence, or verification.

To find where the sign actually gets lost, I queried the real, already-processed IN-IN-03 record in the local Postgres DB (produced by this session's live Azure Document Intelligence + Azure OpenAI extraction run) and read the source PDF's raw text directly:

- **Source PDF** (`tests/india/inbound/IN-IN-03_correct_complex.pdf`) prints the credit-note row with a literal minus sign on both fields: `Credit note adjustment CN-2026-0091 | 1 | -5,000.00 | -5,000.00`.
- **Stored extraction result** (invoice `d36c2ac3-a8ca-4b6c-a731-34d73b518e91`, `KE-2026-0089`) has that same line item persisted as `"unit_price": 5000.0, "amount": 5000.0` — **positive**, sign dropped.

So the causal chain is:
1. Vendor prints a literal `-5,000.00` for the credit-note line.
2. The LLM extraction step (`extract_node` in `extraction_agent.py`, using the `InvoiceLineItem` schema) does not preserve that sign — despite the schema's own field instruction ("Transcribe printed figure verbatim... do not recalculate"), the model isn't reliably applying that instruction to a leading minus sign on a line-item row.
3. `verify_line_items_math` receives `items` with wrong-signed data, correctly (per its own logic) sums them to 55,000, correctly compares against the true subtotal of 45,000, and correctly raises `line_items_mismatch`.

The verification layer did its job correctly on bad input. The defect is one layer upstream, in extraction fidelity for negative/credit amounts.

**Code references:**
- `utils/verification_tools.py:82` — the sum itself; confirmed not buggy
- `agents/extraction_agent.py:47` — `InvoiceLineItem.amount` field description (verbatim-transcription instruction, not reliably followed for negative lines)
- Live DB evidence: invoice `d36c2ac3-a8ca-4b6c-a731-34d73b518e91` (`KE-2026-0089`), `items` JSON, `sa_alerts` JSON

**Confidence:** confirmed (upgraded from "likely" — direct DB evidence closes the inferential gap)
**Suggested owner:** senior-dev (invoice-be) — prompt-engineering fix in `extraction_agent.py`'s line-item extraction instructions, e.g. an explicit callout that credit-note/debit-note/negative-adjustment lines showing a minus sign or parentheses in source text must be extracted as negative `amount`/`unit_price` values. Verify by re-running extraction against this exact PDF (`IN-IN-03_correct_complex.pdf`) post-fix and confirming `status` resolves to `COMPLETED` with no `line_items_mismatch` alert.

---

## Gap 223 — Verification scope is arithmetic-only (product decision, not a bug)

**Hypothesis:** Some real-world defect classes (e.g., a preserved-verbatim vendor typo that a human would still flag) go uncaught because every verification tool checks internal arithmetic self-consistency, not semantic/business correctness.

**What I found:** Unchanged from the earlier pass. The US-IN-05/EU-IN-05-class test cases intentionally probe fields that are correctly transcribed verbatim but don't match a "true" business expectation. The pipeline is behaving exactly as designed (transcribe-verbatim, never auto-correct vendor data) — this is a scope question, not a locatable code defect.

**Code references:** none — by design, not a bug.
**Confidence:** inconclusive (not a defect; needs a product decision on whether to expand verification scope)
**Suggested owner:** founder/product — decide if additional verification classes are worth building, and what "correct" means beyond internal arithmetic consistency.

---

## Gap 224 — Chat gives false-confidence $0.00 on ambiguous category queries

**Hypothesis:** When a chat question references a category/filter that doesn't cleanly map to a DB column, chat confidently answers $0.00 instead of flagging the ambiguity.

**What I found:** Unchanged, confirmed. The SQL-route schema prompt (`query_agent.py` ~lines 586-603) lists 13 `invoice` table columns for the LLM but excludes `items` (line-item JSONB) and `tags`. When a user's question implies a category that isn't a real column, the LLM sometimes generates a SQL `WHERE` clause against a non-matching filter and returns a confidently-worded, empty ($0.00) result rather than saying it can't answer. Related to, but a distinct defect from, Gap 221.

**Code references:**
- `agents/query_agent.py` ~586-603 — SQL schema prompt column list (missing `items`/`tags`)

**Confidence:** confirmed
**Suggested owner:** senior-dev (invoice-be) — smaller fix: add a "no matching column, say so" guardrail to the SQL-generation prompt. Larger fix: expose `items`/`tags` to the SQL route (JSONB querying).

---

## Gap 225 — Currency symbol not tenant-aware

**Hypothesis:** Chat/UI renders a fixed currency symbol regardless of the invoice's actual currency field.

**What I found:** Unchanged, carried over from the earlier phase of this investigation — not re-verified again in this final pass since nothing in the relevant code has changed since it was last confirmed.

**Confidence:** confirmed (carried over from earlier verification this session)
**Suggested owner:** senior-dev (invoice-fe primarily; possibly invoice-be response formatting for chat replies)

---

## Gap 226 (new) — Test harness never captured per-line "Actual" data

**Hypothesis:** The extraction test harness's per-line faithfulness claims (printed-vs-true) were inferred indirectly rather than directly verified against per-line API output.

**What I found:** Confirmed. `tests/run_extraction_harness.py` only ever writes to the "Invoices" sheet of the ground-truth workbook — it never reads or writes the "LineItems" sheet. This is a limitation of my own test tooling, not application code. It's also the reason `Actual Subtotal` showed as `null` for IN-IN-03 in the harness output (the harness doesn't persist/query the computed subtotal onto the Invoice row either — a related but distinct harness gap, noted in that row's `Actual Notes/Errors` field). I was able to work around this for Gap 222 by querying the DB directly instead of relying on the harness output.

**Code references:**
- `tests/run_extraction_harness.py` — entire file; no LineItems-sheet read/write logic exists

**Confidence:** confirmed
**Suggested owner:** senior-dev / functional-tester — harness enhancement. Does not block any application-code fix above, since Gap 222 was independently confirmed via direct DB query. Low urgency.

---

## Sub-question: are chat prompts #8/#9 worth re-running with real fixtures?

Prompts #8 (trained-rule persistence) and #9 (prompt-injection robustness) were sent as plain chat text in this run, without their proper setup — per your own scope simplification during the chat-harness build ("trainer nothing to test only chat... just send them as literal chat text"), no rule was actually committed via Trainer beforehand for #8, and no adversarial-content invoice was actually uploaded for #9. Their results in this run are not meaningful signal about real defects in either area — they were structurally undermined by the simplified test setup, not by the application.

**Recommendation:** worth re-running with real fixtures if trained-rule persistence and prompt-injection robustness are considered high-value defect classes (both touch trust/security), but this is a follow-up test-harness task, not a confirmed gap, and carries lower urgency than the six items above.

---

## Priority-ordered list

1. **Gap 222** — Extraction sign-loss on negative/credit-note lines. Root cause fully confirmed with DB evidence. Data-integrity risk: legitimate invoices get falsely flagged `AUDIT_REQUIRED`, and the underlying stored `amount`/`unit_price` values are simply wrong (not just the derived alert).
2. **Gap 220** — Outbound invoices ship with zero line-item arithmetic cross-check. Customer-facing risk (AR/sales invoices sent externally with no math verification at all).
3. **Gap 224** — Chat's false-confidence $0.00 on ambiguous categories. Confirmed root cause, user-trust impact, comparatively small fix.
4. **Gap 221** — Tenant chat style ignored on the SQL route (100% of this session's traffic). Confirmed, trivial one-line relocation fix.
5. **Gap 225** — Currency symbol not tenant-aware. Confirmed FE display bug.
6. **Gap 223** — Verification scope is arithmetic-only. Not a bug; needs a founder/product decision, no code-level urgency.
7. **Gap 226** — Test harness never captured per-line actual data. Tooling-only, doesn't block any fix above, low priority.
