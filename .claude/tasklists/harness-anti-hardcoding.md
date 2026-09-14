# Anti-hardcoding harness — build tasklist

Founder ask 2026-09-13: "can u create some hooks or any other harness to avoid hardcoded fixes",
then "keep the chat with attachment business intelligence part and build the harness."
Feature 30 work list is PARKED — nothing in this task touches product code.

Layers 1, 2, 3, 5 in scope. Layer 4 (fixture mutation runner) scoped separately, not built here.

- [x] 1. `.claude/hooks/check_hardcoding.py` — PostToolUse literal scanner (advisory, exit 2)
- [x] 2. `.claude/hooks/check_gap_entry.py` — Stop gate, source changed without a tracker entry
- [x] 3. `.claude/settings.json` — register both hooks (project-shared; settings.local.json keeps permissions)
- [x] 4. `Prod_Invoice_LLM/apps/invoice-be/tests/test_no_hardcoding.py` — guard tests in the real suite
- [x] 5. `.claude/skills/gap-work/SKILL.md` + `done/SKILL.md` — defect-class / call-site-count / boundary items
- [x] 6. Self-test: run the scanner on a known-bad and known-good sample; run the guard tests on Postgres
- [x] 7. Report — including whatever the guard tests find in the existing tree

Status: COMPLETE (layers 1,2,3,5). Layer 4 (fixture mutation runner) not built — scoped separately.

Self-test result: scanner fires 6/6 on a planted probe (GSTIN, VAT, DOC_ID, DOMAIN_LIST,
RAW_FIGURE, FIXTURE_ECHO), silent on a comment, on SHA-256, on a money()-formatted line and on
a `hardcode-ok:` suppression. Probe file removed.

Guard suite on real Postgres venv: `2 passed, 2 failed` — both failures are REAL findings in
the existing tree, not guard defects:
  - 10 unformatted money claims in services/attachment_insights.py (= Gap 509 at :1124/:1141/:1191,
    Gap 511 at :509, plus 6 uncatalogued in the bank-reconcile card at :780-:817 and :896)
  - 1 document id literal at agents/query_agent.py:3935 ('TSD-620458')
Left failing deliberately and reported to the founder — standing rule: every failure is
discussed with options before it is fixed.
