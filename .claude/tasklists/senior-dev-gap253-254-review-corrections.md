# senior-dev — Gap 253 / 254 architect-review corrections (in-place)

Correcting the uncommitted Gap 253 + Gap 254 implementation already in the working
tree. 11 numbered fixes from the architect review, plus verification + docs.

## Steps

- [x] 0. Read current state (query_agent.py, support_agent.py, both test files, tracker
      Gap 253/254, feature_6_rag.md, feature_19, SupportChatWindow.tsx). Establish
      baseline pytest + reproduce the two confirmed defects by hand.
- [x] 1. **Fix 1** — replace runtime regex SQL translation with dialect-conditioned
      rule 6d prompt text. Add `_sql_dialect_name(db_session)`; build rule 6d from a
      Postgres or SQLite variant; delete the rewriter block in `execute_generated_sql`.
- [x] 2. **Fix 2** — NULL / non-array `items` guard taught in rule 6d for both engines
      (`jsonb_typeof(items)='array'` CASE / `json_valid`+`json_type` CASE).
- [x] 3. **Fix 3** — `_harvest_invoice_ids_via_companion_query` line-item-aware path so
      `result_invoice_ids` is non-empty for 6d queries (Gap 231 picker + Gap 237 hedge).
- [x] 4. **Fix 4** — rule 9 sentence authorising a FROM-clause change (adding the
      line-item join) on a narrowing line-item follow-up, WHERE contract intact.
- [x] 5. **Fix 5** — rule 6d selects `currency` (rule 7); summary format uses the row's
      currency code, never a hardcoded `$`.
- [x] 6. **Fix 6** — Gap 254 "data" example: drop `"data"` from `export_reports`, add
      keyword-specificity tie-break.
- [x] 7. **Fix 7** — un-shadow `ERROR_TRIGGERS` (drop `payu`/`checkout` from `billing`);
      add a screening test over every trigger phrasing; keep
      `test_error_keyword_triggers_escalation` green.
- [x] 8. **Fix 8** — descope the history-aware follow-up sub-feature; remove the step-4
      block + its test; record the descope in the tracker as a follow-up gap.
- [x] 9. **Fix 9** — FE: neutral low-confidence state in `SupportChatWindow.tsx` (+ BE
      `low_confidence` flag on the chat response). Deliberate scope expansion.
- [x] 10. **Fix 10** — attempted, **NOT achievable here**. No PostgreSQL reachable:
      `DATABASE_URL` → `localhost:5433` connection refused; Docker daemon not
      running; no local Postgres install (`/c/Program Files/PostgreSQL` absent,
      no `psql`/`pg_ctl`/`initdb` on PATH). `test_taught_line_item_sql_runs_on_postgres`
      is written in the existing skip-when-absent shape and **skipped**. Filed as
      **BE Gap 255** rather than buried as a footnote.
- [x] 11. **Fix 11** — old tasklist marked SUPERSEDED with a delta list (its
      "teach both dialects in one prompt" step 2(c), the descoped
      `WITH ORDINALITY`/`line_index` + FE citation steps 7–8, and the different
      harvester fix all called out).
- [x] 12. Tests: SQLite + Postgres execution probes for rule 6d (mirroring
      `test_recommended_cast_form_runs_on_{sqlite,postgres}`), harvester test,
      NULL/malformed-items test, support keyword-shadow screen.
- [x] 13. Full backend suite: **691 passed, 2 failed, 6 skipped** — both failures
      `test_connectors.py` Salesforce OAuth needing local Redis:6379, confirmed
      identical on a stashed clean tree. FE `npx tsc --noEmit` clean; ESLint is
      not configured in this app so no lint result claimed.
- [x] 14. Docs: BE tracker (Gap 253 `[x]`, Gap 254 `[~]`, new Gaps 255/256),
      `feature_6_rag.md`, `feature_19_*.md`, `test_coverage_map.md`, plus the FE
      half (`fe_features_tracker.md` Gap 243, `feature_15_*.md`).

## Status

**Complete.** All 11 review fixes applied. Two things deliberately left open and
recorded as their own gaps rather than claimed done: rule 6d's PostgreSQL form is
unexecuted (Gap 255 — no Postgres in this environment), and the support
assistant's history-aware follow-up is descoped pending an API contract change
(Gap 256). All changes uncommitted.
