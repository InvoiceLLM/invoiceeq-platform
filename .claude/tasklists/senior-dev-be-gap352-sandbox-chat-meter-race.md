# senior-dev — BE Gap 352: sandbox chat meter is not atomic (security-review fix to Gap 340)

Scope: `services/sandbox.py::charge_sandbox_chat_message()` only. Did **not** touch
`scripts/sweep_sandbox_tenants.py` or any bicep/infra file (parallel task — which filed
its own **Gap 345** in the BE tracker while this was in flight).

- [x] Read CONVENTIONS.md, feature_25 spec (Gap 340 section + Verification Plan §14/§15)
- [x] Read `services/billing_quota.py` fully — reused its `locked_tenant_select()` / `populate_existing` idiom
- [x] Fresh gap-number collision check across all three trackers + repo-wide — 352 free (BE max 344 at check time, FE 341, website 351)
- [x] Reproduced the race on real Postgres against the PRE-FIX function (scratchpad script, production code unmodified)
      → limit 5, 24 concurrent: **22 / 19 / 24 / 24 turns allowed**, counter left at 5 / 4 / 4 / 3
- [x] Implemented the lock: `locked_sandbox_select()` + pre-check → `FOR UPDATE` → re-read under lock (`populate_existing`) → re-check → increment → commit
- [x] Added `test_concurrent_chat_charges_cannot_exceed_the_allowance_on_postgres` + `TestChatMetering::test_charge_uses_for_update`
- [x] Re-ran the same harness against the FIXED function → **5 allowed / 19 refused / counter 5, four runs, overspend 0**
- [x] Proved the committed test can fail: pre-fix body swapped in via a throwaway pytest plugin → `AssertionError: 23 turns allowed against a limit of 5`
- [x] `tests/test_sandbox_keys.py` → **52 passed**, exit 0, nothing skipped; with `tests/test_widget_token.py` → **102 passed**
- [x] Updated `feature_25_plug_and_play_workflows.md` — header, Gap 340 §7 marked correction, File Coordinates, Task 25.4, new Verification Plan §20
- [x] Filed **Gap 352** in `be_features_tracker.md` + amended the Feature 25 index line
- [x] Confirmed Postgres left clean — every row this task created deleted; the 4 remaining `sandbox_tenants` rows are other agents' earlier runs (08:58–10:19)

**Final status: complete.** Changes left uncommitted, per this repo's standing convention.
