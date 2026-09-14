# Chat + attachment-BI completion — single build

Founder go 2026-09-13. Scope settled in chat: F33/FE22/F31 parked; Gap 516 parked (frozen taxonomy);
30.9 built from whatever CBIC/GSTN is actually retrievable, NOT_CHECKED with a stated reason for the
rest; L1 claim verifier IN.

Method: Gap entry stating the defect CLASS before each fix; narrow Postgres test per task; full suite
at track boundaries only. Anti-hardcoding guards active throughout. Nothing committed.

## Track 0 — unblock
- [x] 0.1 Measure the real current baseline (full suite, real Postgres)
- [x] 0.2 Collection error: duplicate `run_chat_live_test.py` basename — founder call on the fix
- [x] 0.3 Close or re-scope Gap 477 against what is actually true today

## Track A — the two abstractions + L1
- [x] A.1 Task 30.19 three-state PASS/FAIL/NOT_CHECKED
- [x] A.2 Task 30.20 claims-not-prose, one money() path
- [x] A.3 L1 claim verifier (closes Gap 512, Gap 480)
- [x] A.4 Track boundary: full suite

## Track B — wiring
- [ ] B.1 Gap 510 OCR text threaded to set_attachment_region()
- [x] B.2 Gap 519 rank_findings() buries unquantified findings
- [x] B.3 Gap 515.1 unmatched credits never rendered
- [ ] B.4 Gap 517.2 delivery-note figures collide
- [ ] B.5 Track boundary: full suite

## Track C — never built
- [ ] C.1 Gap 518 payment-application card for remittance advice
- [ ] C.2 Gap 517.3 delivery-note duplicate card
- [ ] C.3 Task 30.9 India rule cards — retrieve what is available, report what is not

## Track D — chat agent outside the bubble
- [ ] D.1 Gap 513 vendor-scoped Trainer rules leak via substring match
- [ ] D.2 Task 30.15 live eval run against gpt-5-mini narration

## Track E — frontend
- [ ] E.1 FE Gap 472 insight row id on findings
- [ ] E.2 FE Gap 471 correct the spec §2 table
- [ ] E.3 FE Gap 470 render provenance / abstention
- [ ] E.4 Gap 514 + FE Gap 478 Trainer visibility surface
- [ ] E.5 Close FE Feature 21

Status: PAUSED 2026-09-14 on founder instruction ("stop work for today"). Docker stopped, data volume
`prod_invoice_llm_postgres_data` preserved. NOTHING COMMITTED — all changes in the Changes panel.

## Where this stopped

DONE and verified on real Postgres:
- Track 0 complete. Collection error fixed in `pyproject.toml` (`python_files = ["test_*.py"]`);
  `pytest tests` collects 3782 with no --ignore flags for the first time. Postgres had been DOWN,
  which is why earlier baselines were worthless.
- Track A complete: tasks 30.19 (CheckLog / three-state), 30.20 (Claim + CLAIM_TEMPLATES +
  money_text), L1 verify_claims(). Gaps 509, 511, 512, 515.1, 515.2, 519 closed.
  Cards migrated: terms_check, bank_reconcile, agreed_vs_billed, cash_cover, open_po_value,
  cash_out_timing.
- Full suite: 4 failed, 3787 passed, 13 skipped (1:23:28). All four diagnosed and fixed as
  Gaps 520 (builder readback inherited the extraction tolerance — a REAL product bug) and
  521 (a/b: stale soft-delete expectation; a calendar-drifting prune test). Re-run: 110 passed.
- Anti-hardcoding harness built and self-proved (separate tasklist).

## NEXT ACTION when work resumes — in this order

1. **Tracker + spec for Track A are NOT written yet.** `be_features_tracker.md` and
   `feature_30_business_intelligence.md` still describe the pre-30.19/30.20 behaviour. Do this
   FIRST; the code is ahead of the docs right now.
   Also record in spec §11.3 the deviation: the four existing money helpers all QUANTIZE and none
   formats to text, so `money_text()` is the new text step delegating to `invoice_builder.money`
   — no fifth quantizer was added.
2. Gap 517.1 — `card_delivery_vs_order` is NOT yet migrated onto CheckLog. The mechanism exists;
   this card still skips unpairable lines silently. NOT closed.
3. Track B remainder: Gap 510 (thread OCR text into run_sync_insights -> set_attachment_region;
   two-level plumbing, ChatAttachment persists no raw-text column), Gap 517.2.
4. Tracks C, D, E as scoped.

## Standing scope decisions from 2026-09-13
Feature 33 / FE Feature 22 / Feature 31 parked. Gap 516 parked (frozen taxonomy). L1 verifier IN.
30.9: build from whatever CBIC/GSTN is actually retrievable, NOT_CHECKED with a stated reason for
the rest, and report to the founder what could not be sourced.
