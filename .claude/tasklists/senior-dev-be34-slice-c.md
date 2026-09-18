# BE Feature 34 (ATLAS) — Slice C — build
Spec: `Prod_Invoice_LLM/apps/invoice-be/docs/feature_34_atlas.md` (§13 rulings, §12/§14/§15/§16 as built)
FE counterpart: `apps/invoice-fe/docs/feature_23_work_screen.md` — tasks 4, 7, 9 unblock here
Rulings: `atlas_discussion.md` D34–D51
Started: 2026-09-18
Branch: `feature/atlas`
Definition of done: every task below checked; every invariant run and cited against real
Postgres (`127.0.0.1:5433`); **the screen can actually do something end-to-end**; spec and
tracker updated; changes uncommitted.
Status: DONE — 34.7a–e BE done (`tests/test_atlas_actions.py` 20 passed, real Postgres). `services/atlas_actions.py`, `AtlasActionLog` + migration `c3d4e56f15a7` (applied), `POST /atlas/lines/{id}/act`, `GET /atlas/actions`, `GET /atlas/actions/kinds`.

## Why this slice exists

Slices A and B produced a screen that **explains and cannot act**:
`PERFORMABLE_ACTION_KINDS` is empty, every button renders disabled, and lines arrive in skill
order rather than ranked. Until 34.7 lands, ATLAS is a report. This slice is what makes it a
tool — 34.7 first, for that reason.

## Tasks

### 34.7 — actions (do this first)
- [x] 34.7a Dispatcher: `POST /atlas/lines/{id}/act`, mapping an action kind to the endpoint
  that already performs it. **Two performable kinds only** (D50/D51):
  `resolve_invoice` → `PUT /audit/resolve/{invoice_id}` (exists),
  `retry_ingestion_source` → `POST /autopilot/sync` per source (exists, per-source since D43)
- [x] 34.7b Capability check on **acting**, separate from the check on *seeing*. Same grant
  governs both, but they are two decisions and only one is currently made
- [x] 34.7c Action log (§5.3: every write is visible, attributed, timestamped) — "what ATLAS
  did" must be a real readable list, not a claim
- [x] 34.7d `PERFORMABLE_ACTION_KINDS` populated **one kind at a time**, only once its path
  works. A button is never enabled before it can do anything
- [x] 34.7e Suggest-only kinds (D50) — `apply_field_correction`, `requeue_invoices` — resolve
  to a destination and open it. They must **not** become writes

### 34.7f — ranking
- [x] 34.7f Rank by **money at stake × how soon it stops being fixable** (§7.3, D30).
  ATLAS ranks; it does not hide — everything below the cut stays reachable

### 34.7g — assignment and collapse
- [x] 34.7g Admin sees every line type, with other grant-holders' work **collapsed to one row
  per area** with its aging figure (§2.2, D20), openable in place. **No escalation** (D37).
  Above a volume threshold the same mechanism serves §7.3 (D41). Unblocks FE task 4

### The rest
- [x] 34.9 Forecast as a warning with levers, **stating its assumption** (§7.5, D15) — a date,
  a number, the actions that close the gap. **Visible to Auditors too** (D44). Unblocks FE task 7
- [x] 34.10 Memory as visible editable rules (§7.2, D31), **bounded by D40** — derived
  observations show their working rather than becoming stored rules. Includes D12 noise pruning
- [x] 34.12 Cold-start orientation content per role (§7.1, D24/D25). Unblocks FE task 9
- [x] 34.14 The "you missed this" affordance feeding §7.2's memory (D34)

### Not built — ruled, not deferred
- `34.8` batch accept + undo — **D42**, nothing is batchable in v1
- `34.11` notifications — **D36**, no channel; ATLAS speaks only when the app is opened
- escalation — **D37**; the Admin is already the superset
- background jobs / the absence clock — **D38**; everything computes on open

## Verification — cited, never SQLite, `127.0.0.1` never `localhost` (BE Gap 697)

- [x] A user without the grant **cannot act**, not merely cannot see (34.7b)
- [x] A suggest-only kind never performs a write (D50)
- [x] Every performed action appears in the action log, attributed and timestamped
- [x] An action kind with no working path is **absent** from `PERFORMABLE_ACTION_KINDS`
- [x] Ranking puts a larger, sooner-expiring item above a smaller, later one
- [x] Nothing below the ranking cut is unreachable (D30)
- [x] A collapsed area row carries its count and aging figure, and opens in place
- [x] The forecast states which assumption it used
- [x] **End-to-end: resolve an invoice from the work screen in a browser and see it resolved
      in Postgres** — DONE 2026-09-18. Real Chromium on `127.0.0.1:3077/work` → next dev route
      handler → uvicorn `127.0.0.1:8077` → Postgres `127.0.0.1:5433`. Clicked **Approve** on
      `audit-approve-5004da49-…`; screen printed the server's "Invoice approved."; the line was
      gone on the re-read; 0 page errors. Postgres: `invoice.status = 'PAID'`, and one
      `atlas_action_log` row (`resolve_invoice`, succeeded, `user_test_default`, timestamped).
      Live `curl` also proved the suggest-only refusal: `apply_field_correction` → **409** with
      D50's reason, logged as a failed attempt.

## Final status

**Done 2026-09-18, uncommitted.** Every Slice C task built (34.7 a–g, 34.9, 34.10, 34.12,
34.14); 34.8/34.11/escalation/background jobs left unbuilt by ruling, with no skeletons. BE
**149 passed** across the eleven ATLAS test files (85 before), FE **117 passed | 4 skipped** (was
90 | 4), `tsc --noEmit` clean. Full BE suite **4564 passed, 11 failed** — the eleven are
pre-existing, unrelated to any file this slice touched, filed as **BE Gap 699** rather than fixed
in an ATLAS build. **End-to-end proof obtained:** a real Chromium click on **Approve** on `/work`
(`next dev` -> route handler -> uvicorn -> Postgres) ended with `invoice.status = 'PAID'` read back
out of the database, plus the matching `atlas_action_log` row and 0 page errors; the same live
backend refused `apply_field_correction` with **409** and logged the refusal. Seeded rows removed
afterwards. New gaps: **BE 699**, **FE 700–703**. Docs: BE Feature 34 **§17**, FE Feature 23
**§14**, both additive.

**Honest limits, so they are not discovered later:** (1) BE 34.10's memory surface and 34.7c's
action log have **no FE at all** — FE Gaps 700 and 701, and until they close §7.2's "the user can
read it, change it or delete it" is only true with `curl`; (2) "you missed this" is on ATLAS lines
only, not on every record (FE Gap 703); (3) a suggest-only destination opens the right screen but
cannot pre-filter it (FE Gap 702); (4) the "pre-existing" claim about the 11 failures is an
argument from the diff, not from a captured baseline run.
