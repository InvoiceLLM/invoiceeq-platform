# functional-tester: BE Gap 237 live repro + BE Gap 242 test-data reseed

Scope (approved via architect): two read-only/data-prep tasks in Prod_Invoice_LLM/apps/invoice-be, no application code or prompt changes.

## Task 1 -- BE Gap 237 step 1 live repro

- [x] Read .claude/CONVENTIONS.md, BE Gap 237 (~line 508) and BE Gap 242 (~line 530) tracker entries in full
- [x] Confirm local stack is up (Postgres/Redis/Chroma/Azurite via docker compose) and BE app is reachable at localhost:8000
- [x] Design a seeded multi-invoice tenant where a broad category question ("cloud") matches invoices via three different branches (vendor_name, tags, items-only), plus one non-matching control invoice, plus one same-category invoice in a different currency
- [x] Write seed+repro script: tests/gap237_sql_repro.py (own tenant "Gap237 Chat SQL Repro Test", repoints user_test_default per the existing _multiturn_chat_repro.py pattern, real chat session, 2 turns, flushes the Redis answer cache per run so repeats aren't served stale)
- [x] Run it against the real backend -- ran 7 times (run0-run6) to characterize behavior given LLM non-determinism
- [x] Diff the two turns' generated SQL WHERE clauses by hand: core defect reproduces live (2/7 runs), but the tracker's specific hypothesis (items branch dropped) is DISCONFIRMED -- both reproductions dropped vendor_name instead, items survived both times. 4/7 runs showed a separate, undocumented failure mode (no fresh SQL generated for turn 2 at all).
- [x] Restore user_test_default's tenant_id back to tenant-us after every run (verified back to 3511ae3e-... at the end)
- [x] Write raw evidence to docs/test_evidence/gap237_sql_repro_2026-08-17/ (README.md analysis + raw_turns_run0.json..run6.json)
- [x] Update docs/test_coverage_map.md with the result and a link to the evidence

## Task 2 -- BE Gap 242 test-data reseed (Blue Ridge Logistics)

- [x] Queried current (corrupted) items/subtotal for Blue Ridge Logistics (tenant-us) directly from the DB -- items was a placeholder ("TEST LINE ITEM EDIT", amount 200.0), subtotal 200.0 (also corrupted, didn't reconcile with tax_amount/grand_total)
- [x] Reverse-solved the real pre-corruption subtotal from tax_amount/grand_total (2225.00 -- exact match on the 7.25% tax rate)
- [x] Applied the UPDATE directly against the local dev DB via tests/gap242_reseed_blue_ridge.py (4 realistic freight/logistics line items summing to $2225.00, subtotal corrected to match; grand_total/tax_amount/tags untouched); script asserts vendor identity + arithmetic reconciliation before writing
- [x] Recorded exactly what was changed (before/after JSON) in docs/test_evidence/gap242_blue_ridge_reseed_2026-08-17/
- [x] Noted the reseed in docs/test_coverage_map.md

## Final status

Both tasks complete, 2026-08-17. No application code or prompts touched. Evidence filed under docs/test_evidence/gap237_sql_repro_2026-08-17/ and docs/test_evidence/gap242_blue_ridge_reseed_2026-08-17/, both linked from docs/test_coverage_map.md. Key result for the senior-dev's upcoming prompt-fix pass: Gap 237's "items branch" hypothesis is disconfirmed as the specific mechanism (any OR branch can be dropped, not items specifically); a second failure mode (no fresh SQL generated on the follow-up turn) and a gap in the already-shipped step-3 hedge's trigger condition were also found and documented, but not fixed (out of scope).
