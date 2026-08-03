# FE Gap Repro — 2026-08-03

Scope: live-repro 4 remaining gaps against the real local dev stack (docker compose + native be/fe/worker). Diagnosis only, no app-code fixes. Evidence under `Prod_Invoice_LLM/apps/invoice-fe/docs/test_evidence/`, tracker updates in `fe_features_tracker.md`, coverage map in `test_coverage_map.md`.

## Already done (verified, not redone)
- [x] Gap 72 — PDF viewer (rotate broken, zoom works, wrong-PDF ruled out) — confirmed complete, evidence at `test_evidence/gap72_pdf_viewer/`
- [x] Gap 81 — stuck at UPLOADED (worker-liveness/supervision gap) — confirmed complete, evidence at `test_evidence/gap81_outbound_worker_liveness.log`
- [x] Gap 84 — stuck at PROCESSING (real backend bug, DB status never persisted on exception) — confirmed complete, evidence at `test_evidence/gap84_stuck_processing_root_cause.log`

## Environment check
- [x] `docker ps` — Postgres/Redis/Azurite healthy; Chroma unhealthy but not needed for these gaps
- [x] be (uvicorn :8000), fe (next dev :3001), worker (queue_worker.main_worker x2), website (:3200) all confirmed running and responsive (200s)
- [x] Queue worker confirmed alive (process start time checked, not touching upload/processing state for these 4 gaps anyway)

## Remaining repro work
- [x] Gap 82 — "click a field to correct it" does nothing. **Does NOT reproduce as a broken handler.** Tested all 7 fields across AUDIT_REQUIRED/COMPLETED/REJECTED invoice states in real non-headless Chromium — click-to-edit works correctly everywhere it should, correctly disabled on resolved invoices. Found one minor byproduct UX defect (disabled field still shows `cursor:text`). Tracker rewritten, evidence filed.
- [x] Gap 83 — Outbound Audit screen redundant internal tab row. **Root-caused**: NOT the Receiving/Sending toggle (ruled out, symmetric+correct on both directions) — it's `app/invoices/outbound-review/[id]/page.tsx` still double-wrapping in `<Shell>`, the exact Gap 71 bug, never fixed on this file. Confirmed live: Sidebar/Header/nav all render 2x. Tracker rewritten, evidence filed.
- [x] Gap 96 — Settings → Connectors "Configure". **Confirmed original diagnosis wrong, does not reproduce** — real working Link, Connect/OAuth flow also works correctly (real Google consent popup, correct polling/disabled-state). Tracker rewritten recommending closure. Found a real, distinct new defect while testing the post-connect folder-browse UI — logged as new Gap 105 (FolderTreeExplorer swallows fetch errors, real 502 renders identically to empty folder). Backend confirmed correct via log; fault-injected test row cleaned up after use.
- [x] Gap 85 — not re-swept (per instruction — no new angle available in this session). Left exactly as-is, noted in coverage map.

## Output
- [x] Tracker entries rewritten for Gap 82, 83, 96 (each with 2026-08-03 findings); new Gap 105 appended (next available number — senior-dev had already added Gaps 100-104 in a Settings Tab Audit pass since this session started, checked highest number before assigning)
- [x] Evidence filed: `test_evidence/gap82_click_to_edit/`, `test_evidence/gap83_outbound_review_double_shell/`, `test_evidence/gap96_connectors_flow/` (also covers Gap 105), each with screenshots + README
- [x] `test_coverage_map.md` updated with all 4 rows
- [x] New defect logged as Gap 105 (see above)
- [x] Temp repro scripts cleaned up (`tmp_gap_repro/` removed); DB fault-injection row for Gap 105 deleted after use

Status: COMPLETE
