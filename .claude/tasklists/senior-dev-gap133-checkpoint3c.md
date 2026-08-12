# Gap 133 — Checkpoint 3c (residual security findings from the 3b review)

Scope: backend only (`dependencies.py`, `routers/auth.py`, `tests/test_auth.py`) plus doc updates.
3b fixes stay as-is; this pass closes what the 3b fix did *not* check.

- [x] 1. HIGH — `provision_tenant` binds `body.clerk_org_id` to the verified token's `org_id` claim (403 on mismatch). Closes findings 1, 3, 5-exploitability.
- [x] 2. HIGH — `dependencies.py`: `TenantContext.role` (and derived can_train/can_audit/can_load) must fall back to the persisted `User.role` when `org_matches` is false — never trust `org_role` from a token whose org isn't this tenant's.
- [x] 3. MEDIUM — `admin_email` sourced from the verified token's `email`/`email_address` claim, not the request body; admin `User` insert wrapped in `IntegrityError` handling (no bare 500).
- [x] 4. MEDIUM — domain-tenant adoption additionally requires: default `billing_plan`, no PayU ids/`paid_through`, and no rows in any tenant-scoped table (invoices, connections, audit logs, templates, chat, email senders, webhooks).
- [x] 5. LOW — no raw DB constraint text (`e.orig`) in the 409 body; log it server-side instead.
- [x] 6. Finding 8 (out of scope, comment only) — document at the `tenant_id` claim check that the claim must come from `public_metadata`/org shortcode, never `unsafe_metadata`, if it is ever added.
- [x] 7. (16 new tests, `tests/test_auth.py` 26 -> 42, all passing) Regression tests in `tests/test_auth.py` for each of the 5 fixes.
- [x] 8. (`pytest tests/` -> 332 passed, 1 failed: pre-existing local-Redis `test_salesforce_pkce_flow`, confirmed failing identically on a stashed tree) Run the full backend suite for real.
- [x] 9. (all 6 scenarios run over real HTTP against real RS256 verification; every one reproduces pre-fix and is closed post-fix) Re-derive the reviewer's 5 repro scenarios against the fixed code.
- [x] 10. Update `feature_1_auth.md` + `be_features_tracker.md` Gap 133 (append a 3c section, don't overwrite 3b).

Explicitly NOT fixed here: finding 7 (adoption-branch TOCTOU race) — still open, reported.

**Final status (2026-08-12): complete.** All 5 findings fixed and verified live (before+after, real RS256 verification over HTTP); test_auth.py 26 -> 42 passing, full suite 332 passed / 1 pre-existing Redis failure. Finding 7 (adoption TOCTOU) remains open, partially mitigated, documented in the tracker. Changes left uncommitted.
