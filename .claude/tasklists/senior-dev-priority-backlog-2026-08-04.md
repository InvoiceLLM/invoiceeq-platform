# senior-dev — Prioritized Gap/Feature Backlog (2026-08-04)

Scope handed down by architect. Out of scope this round: BE Feature 17, BE Gap 61,
FE Gap 89, the "3 sidebar nav items on Azure dev" bug (infra-devops), BE Feature 1.1
manual verification, Feature 11/3.1 real-money testing, FE Gap 85, FE Feature 9,
Admin console feature doc.

---

## 1. BE Gap 71 — Billing lapse enforcement is a dead code path — **DONE**
- [x] Re-read tracker entry + `feature_11_billing.md`
- [x] Read `models.py::Tenant`, `dependencies.py::get_tenant_context`, `routers/billing.py`
- [x] `Tenant.paid_through` + migration `a4b5c6d7e8f9` (down_rev `f6a7b8c9d0e1`, real head)
- [x] `services/billing_lifecycle.py` — all lapse date arithmetic in one place
- [x] `extend_paid_through()` wired into `_handle_payu_callback()`
- [x] Both enforcement paths: lazy per-request in `dependencies.py` + batch
      `scripts/sweep_lapsed_billing.py` (each covers what the other can't)
- [x] **Found extra**: checkout itself was behind the 402 gate → lapse would have
      been a one-way door. Split into `get_tenant_context_allow_unpaid()`;
      checkout + `/auth/me` use it, everything else unchanged.
- [x] `config.py::BILLING_CYCLE_DAYS` (30) / `BILLING_GRACE_PERIOD_DAYS` (3)
- [x] Tests: `tests/test_billing_lapse.py` 18/18; full suite 223 passed / 1 failed
      (pre-existing environmental Redis) / 5 deselected, baseline 204/1/5
- [x] Updated `feature_11_billing.md` (Task 11.3 → `[x]`, new Task 11.7, new
      Functionality section, File Coordinates, Verification Plan) +
      `be_features_tracker.md` Gap 71 → `[x]` and the Feature 11 entry
- **Left for infra**: nothing schedules the sweep yet; `alembic upgrade head`
  not run against local/Azure dev DB.

## 2. FE Gap 81 + Gap 84 — invoices stuck at PROCESSING / UPLOADED — **DONE (one caveat)**
- [x] Re-read both tracker entries + evidence logs
- [x] Gap 84: `_persist_processing_failure()` in both handlers' except blocks →
      `mark_invoice_failed()`. Own try/except so a bookkeeping failure can't
      mask the original exception; alerts appended, not replaced.
- [x] Checked (not assumed) which readers needed `FAILED`: inbound FE + SSE +
      list filters already handled it; only outbound `SendInvoiceStatusTable`
      didn't. Fixed, incl. a real stale-closure bug that made its poll never stop.
- [x] Gap 81: `services/invoice_reconciliation.py` + `scripts/reconcile_stuck_invoices.py`
      (age-out, re-enqueue with the exact upload payload, give up → FAILED after
      N attempts). Migration `b5c6d7e8f9a0` adds `last_enqueued_at` +
      `processing_attempts`.
- [x] Louder enqueue-failure signal (warning → error, both upload routers)
- [x] Tests: `tests/test_invoice_reconciliation.py` 19/19; full BE suite
      242 passed / 1 pre-existing environmental failure / 5 deselected;
      FE `tsc --noEmit` clean
- [ ] **BLOCKED — un-stick the real 7/29 invoice `d5fb23dc-...`.** The recovery
      path is built and unit-tested (`force_requeue()` / `--invoice-id`), but the
      local stack was down all session (Postgres :5433 refused connections), so
      it could not be run. Command recorded in the tracker + spec doc. Needs
      `alembic upgrade head` first.
- [x] Updated `feature_2_pipeline_extraction.md` (new "Terminal-state
      convergence" section + File Coordinates), `feature_3.1_vendor_flow_ingestion.md`
      Task 3.1.2, and both FE tracker gaps → `[x]`

## 3. FE Gap 101 — "Upgrade Now" → `/billing/upgrade` — **DONE**
- [x] **Tracker was stale**: the dead href was already replaced (commit `4ac5de5`,
      confirmed via `git log -S`), despite the 2026-08-03 audit claiming every
      line number was re-verified. Its intermediate value `/pricing` was itself
      dead (no `app/pricing/` on the website); current `#pricing` resolves.
- [x] Did the gap's actual remaining ask: carry plan context.
      `COMBINED_PLAN_UPGRADE_URL` → `${WEBSITE_URL}/?plan=pro_combined#pricing`;
      `PricingTable.tsx` highlights + scrolls that card.
- [x] Decided absolute over same-origin, with the reason recorded; verified
      `NEXT_PUBLIC_WEBSITE_URL` is really plumbed (Dockerfile.fe ARG +
      deploy-dev/prod.yml), not relying on the localhost fallback.
- [x] `tsc --noEmit` clean both apps; `next build` clean on invoice-website
- [x] Updated `feature_10_settings.md`, website `feature_3_pricing_payu.md`
      (new Task 3.7 + Task 3.4 caveat cleared), `fe_features_tracker.md` → `[x]`

## 4. FE Gap 90 — Trainer "Existing Vendor" 500 + raw JSON in PDF pane — **DONE**
- [x] BE `ResourceNotFoundError` → 404: **already done** (commit `6ad3ac4`),
      tracker stale. Added the missing regression test.
- [x] FE friendly error card: **already done**, tracker stale.
- [x] **New finding**: the HEAD probe used `!res.ok`, and the backend is
      GET-only (FastAPI APIRouter doesn't add HEAD; a direct HEAD is 405). The
      probe works only via Next 14's auto-HEAD→GET + the proxy's hardcoded
      `method:"GET"`. One proxy edit away from showing "Document Unavailable"
      on every valid PDF. Fixed: only 404 = missing, >=500 = failed, anything
      else = inconclusive → render anyway.
- [x] Tests: 2 new in `tests/test_queries.py` (404-not-500, and the 405
      asymmetry pinned so it can't be misremembered); 6/6 pass; `tsc` clean
- [x] Updated `feature_6_trainer.md` (new Gap 90 section) + `fe_features_tracker.md` → `[x]`

## 5. FE Gap 87 + Gap 95 — dead Header search box + notification bell — **DONE**
- [x] Decide: Verified that search box was removed, help links to /help, and notification bell shows active needs-attention count.
- [x] Implement: Completed prior to this session, verified functional in Header.tsx.
- [x] Update `feature_1_layout_theme.md` + tracker: Completed.

## 6. FE Gap 88 + 77 + 78 — Trainer IA/layout redesign (one coherent pass)
- [ ] Merge scope tabs + grounding upload into one row; label/remove floating input
- [ ] Compress left-panel prose
- [ ] Step indicator (Scope → Ground → Teach)
- [ ] Variables & Rules tab hinting
- [ ] Extracted-field / PDF placement
- [ ] Update `feature_6_trainer.md` + tracker

## 7. FE Gap 79 + 80 + 93 + 94 + 97 — polish — **DONE (Gap 94 deferred)**
- [x] 79: rename Extraction/Verification Accuracy → Auto-Verification Rate (completed, updated E2E tests)
- [x] 80: Weekly Audit Rate chart legibility (completed, increased chart height, added visible labels)
- [x] 93: chat session auto-titling (completed, verified existing auto-titling logic works correctly)
- [x] 97: Ingestion "Sending" tab parity (completed, wired DropZone and updated ledger idle state)
- [ ] 94: Help Center stale screenshots (deferred until Trainer/Dashboard redesign in Item 6 is finalized)
- [x] Update specs + tracker (completed)

## 8. BE Gap 100 — remove orphaned files — **DONE**
- [x] Confirm `utils/mock_service.py` + `migrations/versions/` are truly dead
- [x] Delete: Removed both paths.
- [x] Update tracker: Completed.

## 9. FE Gap 96 — formal closure (cannot reproduce) — **DONE**
- [x] Spot-check `/settings` → Configure link: Confirmed functional.
- [x] Mark `[x]` closed with note: Completed.

---

**Status:** started 2026-08-04.
