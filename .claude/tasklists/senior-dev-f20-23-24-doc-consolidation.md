# Feature 20/23/24 doc consolidation (documentation only)

Scope: merge three observability docs + one status doc into one `feature_20_23_24_ops_workbook.md`.
No code/test/infra files touched.

- [x] Read `.claude/CONVENTIONS.md`
- [x] Read `feature_24_ops_digest_agent.md` (full)
- [x] Read `feature_20_23_24_implementation_status.md` (full)
- [x] Read `feature_20_observability_monitoring_alerts.md` (structure + "As built" / blockers)
- [x] Read `feature_23_ai_control_tower.md` (selective: Wave 5 workbook section, tasks, action-group facts)
- [x] Confirm workbook field inventories against `cost_health_workbook.json` (25 items) +
      `ai_control_tower_workbook.json` (49 items) — read-only, via `json.load`
- [x] Verify blockers rather than copying them: `benchmark-gate` argparse failure (from the
      infra-devops deploy tasklist + `deploy-dev.yml`'s real `needs:`/`if:`), `Monitoring Reader`
      not granted, `sendgrid-key-secret` absent from `ca-invoice-be-dev`, action-group `-critical`
      split not deployed, Stage 8 ACR/naming drift
- [x] Corrected two stale claims found while verifying: the AI Control Tower workbook **is**
      deployed (2026-08-24, `c1168d95-…`, 49/49 items byte-identical) and the ops_digest files
      **are** committed (`bce9e38`), contradicting the old docs' "not deployed"/"untracked"
- [x] Write `feature_20_23_24_ops_workbook.md` (verbatim sample table checked: 28 + 41 rows)
- [x] Delete the four superseded docs
- [x] Fix cross-refs in `be_features_tracker.md` (28 occurrences, filename-only replacement)
- [x] Fix cross-refs in `fe_features_tracker.md` (1) and `docs/extraction_benchmark/README.md` (1)
- [x] Update `Prod_Invoice_LLM/docs/guides/application_doc_summary.txt` step 8 (doc count 24 → 27,
      consolidation noted)
- [x] Repo-wide grep: no dead doc links remain; only code/bicep/kql, historical `.claude/tasklists/`
      and the intentional "replaced by" mentions still name the old files
- [x] Report back

**Final status:** Complete. 1 doc created, 4 deleted, 4 files repointed. No code, test, bicep or
workbook JSON touched. All changes left uncommitted.
