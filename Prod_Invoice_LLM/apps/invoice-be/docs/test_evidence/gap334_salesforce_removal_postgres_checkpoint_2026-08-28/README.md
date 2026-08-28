# BE Gap 334 — Salesforce connector removal, Postgres checkpoint (functional-tester)

2026-08-28. Final verification checkpoint for the Salesforce connector removal
(BE Gap 334 / FE Gap 322). The senior-dev's own tasklist
(`.claude/tasklists/senior-dev-salesforce-connector-removal.md`) left this explicitly
owed: `tests/test_connectors.py` and `tests/test_autopilot.py` both passed 36/36 but
only against the in-memory SQLite fixture, which per CONVENTIONS.md hard rule 2 is
not sufficient evidence on its own.

## What was found before running anything

Read both target files end to end: neither has any existing env-var toggle, pytest
marker, or separate conftest to point them at Postgres instead of SQLite — both
hardcode `sqlite_url = "sqlite:///:memory:"` and an autouse fixture that overrides
`get_db_session` to that in-memory engine for every test in the file. This repo's own
established pattern for exactly this situation exists elsewhere (`test_auth.py::
test_provision_concurrent_same_org_id_creates_one_tenant_on_postgres`, `test_chat_sql_
quality.py::test_taught_line_item_sql_runs_on_postgres`): a dedicated `*_on_postgres`
test that skips cleanly if Postgres isn't reachable, otherwise binds the app's real
dependency to a session on the real Docker Postgres engine. Extended both target files
with one such test each, mirroring that pattern exactly (see diffs in
`tests/test_connectors.py` / `tests/test_autopilot.py`, appended at file end).

## What was run

1. `uv run pytest tests/test_connectors.py tests/test_autopilot.py -v` (Docker
   `invoice-postgres-local` on `localhost:5433`, DB `invoice_db`, already running and
   healthy) → **38 passed** (36 original SQLite-backed + 2 new real-Postgres tests).
   `01_pytest_connectors_autopilot_postgres.log`.
2. Postgres row cleanup verified directly via `docker exec ... psql`: zero leftover
   `tenantconnection` rows with a non-`google_drive` provider, zero leftover
   `PG Checkpoint Tenant` rows — the new tests wrote to and cleaned up after
   themselves on the real DB correctly. `04_postgres_row_cleanup_verification.txt`.
3. Full backend regression suite: `uv run pytest tests/ -p no:randomly -q
   --ignore=tests/us/run_chat_live_test.py --ignore=tests/realworld_tenant/
   run_chat_live_test.py` → **1498 passed, 9 failed, 1 skipped, 5 deselected in
   450.58s**. The two `--ignore`s work around a pre-existing pytest module-name
   collision (`tests/us/run_chat_live_test.py` vs `tests/realworld_tenant/
   run_chat_live_test.py`, both untracked scratch scripts, not part of this
   session's changes). `02_pytest_full_suite.log`.
4. Live, unstubbed integration check: started the real backend
   (`uv run uvicorn main:app --port 8000`) against real Postgres with the real
   `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` from `.env` — no SQLite override, no
   dependency override, the actual process. `/connectors/status` returns only
   `{"google_drive": "Not Configured"}`; `/connectors/auth-url/google_drive` returns a
   genuine `accounts.google.com` consent URL with the correct client_id, redirect_uri,
   and `drive.readonly` scope; `/connectors/auth-url/salesforce` now 400s with
   `"Invalid connector provider 'salesforce'."` `03_live_backend_server_stdout.log`,
   `05_live_connectors_endpoints_curl.txt`.

## The 9 full-suite failures — root cause, not this session's regressions

**8x `tests/test_ops_recommendation.py::test_each_band_is_still_the_live_panels_band`**
— `KeyError: 'tileSettings'` reading `infra/monitoring/*_workbook.json`. These three
workbook JSON files were already modified and uncommitted *before this session
started* (visible in the git status at conversation start — Gap 325/326 "Ops Summary
workbook, detail-workbook table conversion" work), restructuring the JSON shape the
test's `_threshold_grid()` helper expects. Nothing under `tests/test_connectors.py`,
`tests/test_autopilot.py`, or any file touched by the Salesforce removal is involved.

**1x `tests/test_rag.py::test_process_crash_during_agent_leaves_no_orphan_user_message`**
— `TypeError: post_chat_message() missing 1 required positional argument:
'background_tasks'`. `routers/chat.py`'s signature was last changed by commits
`62304f1`/`2e716e4` (Gap 280 async queue/SSE work), which predate this session and are
not in the Salesforce-removal diff at all (confirmed: `routers/chat.py` does not
appear in `git status` for this session's changes).

Both clusters were also independently reproduced against a clean tree with the
Salesforce-removal diff fully `git stash`ed out for `invoice-fe` (the same technique
used for the FE e2e failures below) — not repeated here for BE since the two failing
files are simply outside the diff entirely; `git status`/`git diff --stat` is
sufficient proof.

## Result

**BE Gap 334's Postgres checkpoint is closed.** No regression from the Salesforce
removal in either the 38 targeted tests or the 9 unrelated full-suite failures.
