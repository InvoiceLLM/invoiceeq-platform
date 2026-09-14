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
- [x] B.1 Gap 510 OCR text threaded to set_attachment_region()
- [x] B.2 Gap 519 rank_findings() buries unquantified findings
- [x] B.3 Gap 515.1 unmatched credits never rendered
- [x] B.4 Gap 517.2 delivery-note figures collide
- [x] B.5 Track boundary: full suite

## Track C — never built
- [x] C.1 Gap 518 payment-application card for remittance advice
- [x] C.2 Gap 517.3 delivery-note duplicate card
- [x] C.3 Task 30.9 India rule cards — retrieve what is available, report what is not

## Track D — chat agent outside the bubble
- [x] D.1 Gap 513 vendor-scoped Trainer rules leak via substring match
- [x] D.2 (live 18/20 -> golden re-baselined -> deterministic 20/20; Gap 522 filed from the live verdicts) Task 30.15 live eval run against gpt-5-mini narration

## Track E — frontend
- [x] E.1 (BE + FE halves done) FE Gap 472 insight row id on findings
- [x] E.2 FE Gap 471 correct the spec §2 table
- [x] E.3 FE Gap 470 render provenance / abstention
- [ ] E.4 Gap 514 + FE Gap 478 Trainer visibility surface
- [ ] E.5 Close FE Feature 21

Status: SESSION 2 2026-09-14 11:37–12:37 (1 h hard stop) — ENDED ON TIME. Uncommitted, in the Changes panel. Tracks B, C, D.1 done; docs written (tracker + spec §12). Open: D.2 (30.15 live), Track E, ten cards still on f-strings. Previous status follows.

Status (previous): PAUSED 2026-09-14 on founder instruction ("stop work for today"). Docker stopped, data volume
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


## Hard stop 12:37, 2026-09-14 — final state
Done this session: Tracks B, C, D; FE 472 BE half; FE 478 collision resolved (theme -> FE Gap 496); golden
re-baselined (20/20 deterministic, 18/20 live); ALL cards now on claims; Gap 522 filed (narration raw
floats); Gap 523 found+fixed (guard regex was a backspace — the guard was blind to raw figures for a day).
OPEN: Gap 522 fix (founder to pick a/b); FE Gaps 470, 471, 472-FE-half. Nothing committed.

## Founder rulings 2026-09-14 (after the 12:37 hard stop) — scope for the NEXT session, not yet started
- Gap 522 → option (a): hand the narration model a `figures_text` map built by money_text()/days_text()/count_text() and instruct it to quote only those spellings; contract gate unchanged.
- FE Gap 472 (FE half) → read `finding.insight_id` for actions immediately; KEEP the mount-time fetch only to restore dismissed/noted state on reload.
- FE Gap 470 → build BOTH: abstention card (next_step as a chip that seeds the composer) + provenance line reusing the citation-pill style; add both optional fields to types/chat.ts.
- FE Gap 471 → correct Feature 21 spec §2 table in place (ChatMessage.insights; GET /chat/insights?attachment_id=; no pin — BE Gap 492) with a one-line reason.
Founder: "go and fix the above" 12:43 → ALL FOUR DONE 12:52. Gap 522 live re-run 20/20 with 0 raw-float verdicts; FE 470/471/472 closed; FE suite 35 passed; tsc clean. Uncommitted.
