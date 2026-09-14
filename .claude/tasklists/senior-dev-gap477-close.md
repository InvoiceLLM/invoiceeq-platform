# BE Gap 477 — finish the remaining items (2026-09-14)

- [x] Read `.claude/CONVENTIONS.md`, gap-work / done / verify-postgres skills, the full Gap 477 entry
- [x] Baseline the four "environment failure" files on real Postgres → all green, which contradicted the entry
- [x] Found why: commit `3415840` **deleted** the 5 tests (2 autopilot, 1 connectors, 2 workflow `*_on_postgres`)
- [x] Restore all 5 with assertions unchanged (`git apply -R` for autopilot, old-blob append for the other three)
- [x] Reproduce the real failures: `3 failed, 65 passed` (autopilot/connectors), `1 failed, 22 passed` (email summary)
- [x] Fix 1 — `_mock_auth_tenant_id()`: seed under the tenant mock auth actually resolves (3 tests)
- [x] Fix 2 — `b"%PDF-1.4 ..."` download fixtures for Feature 28's `normalize_upload()` sniffing (2 tests)
- [x] Strengthen the email recipient assertion to the registered inbound allowlist (set equality)
- [x] Fix 3 — rename both live scripts to `live_chat_check.py` (plain `mv`: both dirs are git-ignored, `git mv` refuses)
- [x] Update every live reference (pyproject, benchmarks, sibling live scripts, live-run markdown, forward-looking spec guidance); historical run citations deliberately unchanged
- [x] Verify: 23 / 31 / 68 / 126 passed, `--collect-only -q tests` → `3945/3950 tests collected (5 deselected)` with no `--ignore`
- [x] Spec bodies: `feature_25` §11/§13, `feature_9` Verification Plan, rename notes in `feature_17`/`feature_25`/`feature_28`/`feature_30`
- [x] Tracker: Gap 477 new dated bullet + `[~]` → `[x]`

Final status: done, uncommitted. Full suite not run here — orchestrator runs it at the track checkpoint.
