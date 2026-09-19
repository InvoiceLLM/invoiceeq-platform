# FE Gaps 700–703 — the four surfaces Slice C's backend has and the FE does not
Specs: `apps/invoice-fe/docs/feature_23_work_screen.md` §14, **§15 (written by this run)** ·
`apps/invoice-be/docs/feature_34_atlas.md` §17
Rulings: `atlas_discussion.md` D12, D31, D34, D40, D50
Started: 2026-09-18
Branch: `feature/atlas`
Definition of done: all four gaps `[x]` in `fe_features_tracker.md`; `npx vitest run` and
`tsc --noEmit` green and cited; **each surface shown working against a live backend**, not a
fixture; changes uncommitted.
Status: **done — all four closed, uncommitted on top of `2baf8bb`**

## Why these four are one task

Slice C built four backends with no screen. Each is a promise the product makes and currently
keeps only through `curl`. They share one shape — a served endpoint nobody can reach — which is
the same seam FE Feature 23 exists to close.

## Baselines — do not regress

- FE `npx vitest run` → **117 passed | 4 skipped**; `npx tsc --noEmit` → clean
- BE ATLAS files → **149 passed** on real Postgres (`127.0.0.1:5433`, never `localhost` — BE Gap 697)
- 11 backend failures are **pre-existing** — confirmed 2026-09-18 by running them in a worktree
  at `2baf8bb`, the commit before Slice C: same 11. They are BE Gap 699, inherited from master.
  Do not try to fix them and do not count them as a regression.
  *(Not touched by this run: no backend file was changed at all.)*

## Tasks

- [x] **FE Gap 700 — the memory surface.** `atlas_memory_rules` has full CRUD and hard delete,
  and no UI. §7.2 / D31: "everything ATLAS learns becomes a visible, editable rule in plain
  language ... a wrong lesson that cannot be found haunts the system forever" — currently true
  only with `curl`. Needs: list, edit, **hard delete** (never soft — founder rule), and D12's
  noise-pruning suggestions rendered, which today are computed and seen by nobody.
  **D40 bound:** derived observations (vendor baselines) are **not** memory rules and must not
  appear here — they show their working on the line instead.
  **Built:** `components/atlas/MemoryPanel.tsx` (list · inline edit · active toggle · hard delete ·
  "tell me something" · D12 suggestions with an accept control), `fetchAtlasMemory()` /
  `addMemoryRule()` / `editMemoryRule()` / `deleteMemoryRule()` in `lib/atlas.ts`,
  `app/api/atlas/memory/route.ts` + `memory/[id]/route.ts`, mounted in `WorkScreen`.
  D40 held structurally: one source of rows, asserted by a test over the calls made.
- [x] **FE Gap 701 — the action log.** `GET /atlas/actions` is served and displayed nowhere.
  §5.3 makes "what ATLAS did is a real list" a **boundary**, not a feature — a list only a
  developer can query does not satisfy it. Show successes **and refusals**, attributed and
  timestamped, tenant-wide (§2.2).
  **Built:** `components/atlas/ActionLog.tsx` (collapsed, newest-first as sent, refusal rows
  styled and labelled separately, re-reads on open), `fetchAtlasActions()`,
  `app/api/atlas/actions/route.ts`, mounted in `WorkScreen`.
- [x] **FE Gap 702 — suggest-only destinations do not filter.** "Open the stuck list" opens the
  whole list. No query string is appended and `/invoices` reads no parameter. Fix **both ends**,
  or the parameter one side sends and no page reads is the F33/F22 seam in miniature — which is
  precisely what this feature was written to prevent.
  **Built, both ends in one change:** `actionDestination()` sends `?status=PROCESSING` /
  `?vendor=<target_id>` (chosen from what each emitter actually selects on);
  `app/invoices/page.tsx` reads both via `useSearchParams()` behind a `Suspense` boundary;
  `FilterBar` gained `initialFilters`, which outranks the saved set and makes the filter visible.
  `params.invoice_ids` deliberately not sent — `GET /invoices` has no id-set filter.
- [x] **FE Gap 703 — "you missed this" is ATLAS-only.** D34 says "on any record". It is least
  available exactly where a miss is noticed: on a record ATLAS said nothing about. Put it on the
  record surfaces, not only on ATLAS lines.
  **Built:** `MissedThis` mounted on `app/invoices/review/[id]/page.tsx`, `app/trainer/page.tsx`
  and `components/ingestion/IngestionHistoryTable.tsx` — the last is this product's documents
  list, since FE Gap 464 folded `app/documents/page.tsx` into History. The record's own kind is
  passed through unchanged; nothing is capability-gated.

## Verification

- [x] A memory rule can be read, edited and **hard deleted** from the UI, and the delete is gone
      from Postgres — not flagged, not retained
      *(rule `7fba5265-…` created, edited and deleted in a real browser; 0 rows by id and 0 by
      text afterwards, and `atlas_memory_rules` has no `deleted_at` column to hide in)*
- [x] A derived vendor baseline never appears as an editable memory rule (D40)
      *(one source of rows, asserted in `atlas-memory.test.tsx`; the backend's own
      `test_no_emitter_writes_to_the_memory_store` is the other half)*
- [x] The action log shows a **refused** action as well as a successful one
      *(live: "Invoice approved." plus the 409 on `apply_field_correction` and two 422s)*
- [x] A suggest-only destination lands on a **filtered** view, and the target page reads the
      parameter it is sent
      *(live: `/invoices?status=PROCESSING` → `GET /api/invoices?limit=8&offset=0&status=PROCESSING`,
      stuck row shown, other row hidden; the vendor filter is the mirror of it)*
- [x] "You missed this" is reachable from a record ATLAS never mentioned
      *(live: reported from the invoice review console; `atlas_missed_reports` row with the
      description unedited, plus the memory rule it created, both read back out of Postgres)*
- [x] `npx vitest run` ≥ 117 passed, `npx tsc --noEmit` clean
      → **155 passed | 4 skipped**, `tsc` clean
- [x] **End-to-end against a live backend for each of the four** — a fixture is not this proof
      *(real Chromium → `next dev :3077` → `uvicorn 127.0.0.1:8077` → Postgres `127.0.0.1:5433`;
      transcript in FE Feature 23 §15.6; every seeded row removed afterwards)*

## Docs

- [x] `feature_23_work_screen.md` §15 appended (additive; §1–§14 untouched)
- [x] `fe_features_tracker.md` — Gaps 700–703 `[x]` with closure notes, plus a section for the batch

## Final status

All four closed and proven live; **155 passed | 4 skipped**, `tsc` clean; nothing committed —
the change sits uncommitted on top of `2baf8bb` for review in the Changes panel.
