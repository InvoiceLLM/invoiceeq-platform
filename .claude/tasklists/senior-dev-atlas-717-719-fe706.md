# ATLAS follow-ups — BE Gaps 717/718/719, FE Gap 706, grading doc (2026-09-20)

Founder approval: "lets fix all five" (2026-09-20). Branch feature/atlas-intelligence.

- [x] Read evidence, expected doc, agent/tools/cache/routers, FE briefing files
- [x] BE Gap 717 — `alert_open` on rows + deterministic appended paragraph for uncited open alerts
- [x] BE Gap 717 tests (omitted flagged invoice appended · PAID not appended · dismissed not appended · falsification)
- [x] BE Gap 718 — deterministic duplicate interview question when the model asked none
- [x] BE Gap 718 tests (fires on VPI-shaped fixture · not when a rule mentions either number · never two)
- [x] BE Gap 719 — invalidate briefing wherever role/can_* are written (list every site)
- [x] BE Gap 719 test via the real endpoint → today's row stale=true
- [x] FE Gap 706 — citation labels from data, id kept in title/aria-label; map passed from WorkScreen
- [x] FE tests + `npm run typecheck`
- [x] Grading fix — docs/atlas_admin_vpi_expected.md §2/§6 real ids + MATCH rule + additive note
- [x] Re-run Admin/Auditor/Trainer briefings on VPI with real Terra, explicit GrantSets
- [x] Grade re-runs into docs/test_evidence/atlas_intelligence_2026-09-20/rerun_after_717_719/
- [x] tests/test_atlas_*.py + test_no_hardcoding.py; FE unit suite
- [x] Specs (BE §13 additive, FE additive) + trackers (BE 717/718/719, FE 706)

Final status 2026-09-20: all five items done, uncommitted in the working tree. BE 305 atlas/no-hardcoding tests + 60 rbac/dependency-span tests green on real Postgres; FE 199 unit tests green; three live Terra re-runs filed under docs/test_evidence/atlas_intelligence_2026-09-20/rerun_after_717_719/.
