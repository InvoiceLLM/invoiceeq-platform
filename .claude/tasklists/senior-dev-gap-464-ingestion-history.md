# Gap 464 — durable ingestion History screen, replacing the standalone Documents page

Founder-approved 2026-09-05. Number collision-checked repo-wide (461/462 used, 463 is
the concurrent builder agent's, 464 free).

## Backend
- [x] `models.py`: new `IngestionBatch` (batch_id, tenant_id, flow_direction, trigger,
      file_count, started_at, archived_at). Nothing added to `TenantAutopilotLog`.
- [x] Alembic migration + backfill (`d5e6f7a8b9c0`; `b2c3d4e5f6a7` was taken) from existing `Invoice`/`Document` batch_ids. Single head.
- [x] `routers/ingestion_history.py` — list runs, run files drill-down, archive one,
      archive all, unarchive. Autopilot merged read-only from `TenantAutopilotLog`.
- [x] Write an `IngestionBatch` row at each ingestion entry point: manual upload
      (`routers/invoices.py`), outbound (`routers/outbound_invoices.py`, minimal edit —
      Gap 463 agent owns that file), email (`routers/email_ingestion.py`), connector.
- [x] Surface `dropped_inbound_emails` (needed `archived_at` on that table too) as rejected runs.
- [x] Register router in `main.py`.

## Frontend
- [x] Next.js proxy routes for the new endpoints (5: list, files, archive, unarchive, archive-all).
- [x] History screen (`app/history/page.tsx`) + `components/ingestion/IngestionHistoryTable.tsx`.
- [x] Filters: Manual/Email/Connector/Autopilot, Receiving/Sending, Archived.
- [x] `Sidebar.tsx`: Documents out, History in. `app/documents/page.tsx` deleted.
- [x] Ingest `StatusTable` left alone.

## Verification
- [x] Migration up/down/up against real Postgres on a scratch DB, single head `d5e6f7a8b9c0`; also applied to the dev DB.
- [x] New narrow test file `tests/test_ingestion_history.py` -> **7 passed in 12.13s**, incl. the aggregate-isolation assertion (documents never
      enter invoice aggregates).
- [x] Full BE suite -> **43 failed, 3113 passed** (baseline failure set, name for name). Control run ignoring only the new file -> **43 failed, 3106 passed**.
- [x] FE `node node_modules/typescript/bin/tsc --noEmit` exit 0; `e2e/ingestion-history.spec.ts` -> **5 passed (54.1s)**.

## Docs
- [x] `apps/invoice-fe/docs/feature_3_ingestion.md` - additive section.
- [x] Feature 27 R5(c) note: surface moved (row amended + additive superseded section).
- [x] BE + FE tracker Gap 464 entries (both re-read immediately before writing; Gap 463's entries verified intact after).

Status: code-complete. `done` gate run: items 1, 3, 4, 5, 6, 8 yes with citations;
item 7 not applicable (not functional-tester work); **item 2 NO** — the live
dev-stack end-to-end run was not performed. Both Gap 464 tracker entries are
therefore `[~]`, not `[x]`.

Owed and NOT claimed: no live dev-stack run. Every `/api/**` call in the Playwright
spec is stubbed, so the request shapes and rendering are proven and the wiring to a
real backend is not. Recorded in both tracker entries and both spec sections.

Flagged for the founder: `main.py` carries only the Gap 464 router registration. The
coordinator's note said the paused model-registry effort also edits `main.py`; it does
not, in the current tree. Not restored or investigated further - out of scope, and that
work is explicitly do-not-touch.
