# senior-dev: Feature 25 final-gate follow-ups (Gap 353, Gap 354)

Two narrow, confirmed, non-blocking findings raised by the functional-tester
final regression gate for BE Feature 25 (`.claude/tasklists/functional-tester-plug-and-play-final-gate.md`,
evidence in `apps/invoice-be/docs/test_evidence/feature25_final_gate_2026-08-30/`).

Boundaries: these two fixes only. No full-suite re-run (already done by the
gate task). Narrow verification per this repo's own convention.

## Prep

- [x] Read CONVENTIONS.md, active-work.md, the gate tasklist + evidence logs
- [x] Read `services/sandbox.py::charge_sandbox_chat_message()` and
      `billing_quota.py::charge_free_quota()` (the idiom it mirrors)
- [x] Read `tests/test_sandbox_keys.py` concurrency test + `tests/test_rag.py`
      tenant-isolation test + `routers/chat.py:314` (isolation check confirmed
      present and untouched at 240/277/314/368)
- [x] Fresh gap-number collision check: repo-wide grep for `Gap 35[3-9]` across
      md/py/ts/tsx/json/bicep returned ZERO hits. Maxima at filing: BE 352
      (+ parallel reaper-scheduling 345), FE 327, website 351. Numbers treated
      as one global sequence since Gap 350. 353 and 354 taken.

## Gap 353 -- flaky reported `used` count (reporting bug, not security)

- [x] Fixed `charge_sandbox_chat_message()`: `charged_used` captured between the
      increment and `commit()` (lock still held); post-commit `refresh()`
      deleted. Docstring gained a Gap 353 paragraph; nothing else touched.
- [x] Confirmed the existing test ALREADY asserts distinct sequence numbers
      (`sorted(r["used"] ...) == list(range(1, limit+1))`, written by Gap 352).
      Left byte-for-byte alone -- no strengthening needed.
- [x] Repeated-run proof vs real Postgres, one fresh pytest PROCESS per run:
      BEFORE (fix temporarily reverted in place) **13 passed / 7 failed of 20
      = 35% failure**; AFTER **25 passed / 0 failed of 25**. 0.65^25 ~= 1.4e-5.
      Whole file: 52 passed, exit 0, nothing skipped.
      Log: `docs/test_evidence/feature25_final_gate_2026-08-30/03_gap353_repeated_run_before_after.txt`

## Gap 354 -- `test_rag.py::test_session_lifecycle_and_tenant_isolation` no
longer exercises the isolation branch post-Gap-335

- [x] Override repointed at `get_tenant_or_api_key_context`. Checked first for an
      established convention: grep of `tests/` found THIS is the only test
      overriding a tenant dependency at all (test_auth.py overrides
      get_authenticated_clerk_identity, test_autopilot.py get_session; every
      other dual-credential test sends a real X-API-Key header). Kept the local
      shape, repointed it -- no new pattern invented.
- [x] Guard added: the override is a named function recording each invocation,
      and the test asserts it was invoked before asserting the 403.
- [x] Proven able to FAIL three ways: (a) fixed + isolation intact -> passes;
      (b) `routers/chat.py:314` temporarily neutered to `if False:` -> fails
      `assert 200 == 403` WITH the new guard passing on that same run (proves
      the foreign-tenant path really executed); (c) override temporarily
      repointed back at `get_tenant_context` -> fails on the guard with its
      explanatory message. Both temporary edits backed up and restored, restores
      verified by grep + re-run.
      Log: `docs/test_evidence/feature25_final_gate_2026-08-30/04_gap354_fail_then_pass.txt`
- [x] Correction recorded: the test was FAILING (`assert 200 == 403`), not
      silently passing as the brief described. Same root cause, same fix.

## Filing

- [x] Gap 353 + Gap 354 entries in `be_features_tracker.md` (both `[x]`)
- [x] `feature_25_plug_and_play_workflows.md`: header follow-up note, Gap 340
      section §7 "Amended again by Gap 353" blockquote, Task 25.4 amendment,
      Task 25.1 amendment (Gap 354), new Verification Plan **§22**, and a
      closing pointer on §21's two open findings.
- [x] Two evidence logs filed under the gate's existing evidence folder.
- [x] Final narrow run: `pytest tests/test_sandbox_keys.py tests/test_rag.py`
      -> **110 passed, 1 failed** (the failure is the pre-existing, unrelated
      `test_process_crash_during_agent_leaves_no_orphan_user_message`
      `background_tasks` TypeError, already root-caused by the gate as failing
      identically on clean HEAD -- deliberately NOT fixed, out of scope, needs
      its own Gap).

STATUS: COMPLETE. Both fixes in, both proven (before/after for the race,
fail-then-pass for the isolation test). Changes left uncommitted. One item
flagged for a future Gap: the pre-existing `post_chat_message()`
`background_tasks` TypeError in test_rag.py.
