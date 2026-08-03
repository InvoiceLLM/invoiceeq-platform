# senior-dev — log 5 Settings-tab audit findings as Gap entries

Task: documentation only. Add 5 new Gap entries to
`Prod_Invoice_LLM/apps/invoice-fe/docs/fe_features_tracker.md`, all found during
the 2026-08-03 Settings-tab audit. No code changes, no fixes, no other tracker edits.

(Item 5 added mid-run by the coordinator — was originally a 4-item task.)

## Steps

- [x] 0. Determine next free Gap number in the FE tracker (confirm nothing above 99 exists)
      — Grepped every `Gap \d+` occurrence in the file; highest is 99 (no 100+ anywhere,
        incl. no cross-reference). BE tracker's Gap 100 is a separate numbering space.
        **Assigning 100, 101, 102, 103** (+ **104** for the late-added item 5).
- [x] 1. Verify + log **Gap 100**: fake role gate on `/settings` root (`app/settings/page.tsx` `CURRENT_ROLE`)
      — confirmed line 20 literal, consumed at line 55, drives `isAdmin` at `ServiceFlowToggles.tsx:120`.
- [x] 2. Verify + log **Gap 101**: dead `/billing/upgrade` link (`ServiceFlowToggles.tsx:103`)
      — confirmed no `app/billing/` in invoice-fe at all; invoice-website has only `success/` + `failed/`.
- [x] 3. Verify + log **Gap 102**: fake Disconnect on Connectors (`page.tsx:147-169`)
      — confirmed `connectors.py` has 5 routes, none DELETE; no FE proxy route either.
- [x] 4. Verify + log **Gap 103**: duplicate outbound-sender editor
      — confirmed both components GET+PUT `/api/settings/service-flow` for the same field, mount-snapshot only.
- [x] 5. Verify + log **Gap 104** (late addition): `/admin` built but absent from `Sidebar.tsx` nav
      — confirmed `app/admin/page.tsx` exists; `Sidebar.tsx` lines 38-49 list 7 items, no `/admin`.
- [x] 6. Final check — all 5 entries `[ ]`, numbering sequential 100-104, no other file touched

## Status

Complete. All 5 gaps (100-104) logged in `fe_features_tracker.md` under a new
`## Settings Tab Audit (2026-08-03)` section. Documentation only — no code changed.
