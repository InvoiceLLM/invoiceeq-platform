# senior-dev — Group 2: chat SQL quality (BE Gaps 241, 242, 237 step 2 + step-3 hedge bug)

Scope: `Prod_Invoice_LLM/apps/invoice-be/agents/query_agent.py` only (SQL `system_prompt` rules
+ `run_query_agent()` hedge). Tests in a new `tests/test_chat_sql_quality.py`.
Barred (owned by the concurrent RAG pass): `chroma_client.py`, `queue_worker/handlers.py`,
`queue_worker/outbound_handlers.py`, `routers/audit.py`, `routers/outbound_audit.py`, `tests/test_rag.py`.
Do not touch invoice-fe (FE Gaps 240/241/242 are different defects with the same numbers).

## Steps

- [x] 1. Read CONVENTIONS, BE Gaps 237/241/242, gap237 repro evidence + harness, `query_agent.py`
- [x] 2. Baseline: 8 runs of `tests/gap237_sql_repro.py` against a private backend on port 8100
      (port 8000 left alone for the concurrent agent). **Before: correct 3/8, no_sql 5/8,
      branch_drop 0/8, hedge fired 0/8.** Evidence:
      `docs/test_evidence/gap237_step2_fix_2026-08-17/raw_turns_before_*.json`.
      Harness gained two additive env overrides (`GAP237_BASE_URL`, `GAP237_EVIDENCE_DIR`),
      defaults unchanged.
- [x] 3. Gaps 241+242: SQL prompt rules 6b (standard four-column OR group: `tags`, `items`,
      `vendor_name`, `customer_name`) and 6c (never decompose a multi-word phrase into
      single-word branches; "or"-joined alternatives are separate whole phrases)
- [x] 4. Gap 237 step 2: new `get_prior_turn_sql()` + `PREVIOUS TURN'S SQL` prompt block + rule 9
      (reuse the prior WHERE clause verbatim, add with AND, never drop an OR branch)
- [x] 5. New failure mode (`sql: null` on a follow-up): rule 8a (history is not a data source),
      one forced regeneration retry (`_NULL_SQL_FOLLOWUP_RETRY_DIRECTIVE`), and an explicit
      `_NO_FRESH_QUERY_NOTE` on the reply if it still declines
- [x] 6. Step-3 hedge bug: now compares against the *referenced* number (grounded by requiring it
      to appear in the prior reply's text) instead of the prior turn's total row count; stays
      silent when the current turn harvested 0 ids
- [x] 6d. NEW (2026-08-18): live run on merged master hit
      `psycopg2.errors.UndefinedFunction: function lower(jsonb) does not exist` on a large
      fraction of tag/item chat queries. The prompt's own canonical example told the model to
      write `LOWER(tags) LIKE ...` and claimed it "works in both SQLite and Postgres" -- false:
      `tags`/`items`/`sa_alerts` are JSONB on Postgres (models.py `JSON_VARIANT`). Rules 6 and 6b
      now use `LOWER(CAST(tags AS TEXT))`. Verified directly against the dev Postgres
      (`LOWER(tags)` -> UndefinedFunction; `tags::text` and `CAST(tags AS TEXT)` both OK) and
      against SQLite (`CAST(... AS TEXT)` OK; `tags::text` -> "unrecognized token: :"), which is
      why CAST, not `::text`, is the canonical form.
- [x] 7. Unit tests (`tests/test_chat_sql_quality.py`, 32 tests incl. 4 new jsonb-cast ones, 2 of
      which execute the predicate against the real SQLite/Postgres engines) — all pass.
      Full backend suite: **616 passed, 5 deselected** (`pytest tests/ -q`, 2026-08-18).
- [x] 8. Live statistical verification (2026-08-18, private backends on :8100 fixed / :8200
      deliberately-reverted; :8000 left free). 8 runs of `tests/gap237_sql_repro.py`:
      **after: correct 8/8, no_sql 0/8, branch_drop 0/8, hedge 0/8** vs. baseline 3/8, 5/8, 0/8, 0/8.
      jsonb-cast before/after via new `tests/gap6d_jsonb_cast_probe.py` + server logs:
      **pre-fix 13 `lower(jsonb) does not exist` aborts over 16 chat messages, fixed 0 over 32.**
      Evidence + scorer + logs: `docs/test_evidence/gap237_jsonb_cast_2026-08-18/`.
- [x] 9. Tracker `docs/be_features_tracker.md`: Gap 237 `[~]`→`[x]`, Gaps 241/242 `[ ]`→`[x]`, each with
      a fix note; plus a gap-number-collision warning block above 241/242.
      Spec body: **`docs/feature_6_rag.md`, not `feature_4_queries_pdf.md`** — the brief named
      feature_4, but that spec covers the REST `/invoices` list/PDF endpoints and never mentions
      `query_agent.py`; feature_6_rag.md's File Coordinates own it. Updated there: File
      Coordinates (new functions/constants), the SQL-route functionality narrative, the now-stale
      Aug-17 Gap 237 bullet, a new "Recent Fixes (Aug 17–18, 2026) — chat SQL route" section, and
      the Verification Plan.

## Status

Started 2026-08-17, completed 2026-08-18. All 9 steps done. Full BE suite 616 passed / 0 failed.
Gap-number collision with the unmerged `feature/contact-us-and-support-tickets` branch (its own
BE/FE Gaps 240/241/242) is recorded in the tracker for whoever merges it — not resolved here.
