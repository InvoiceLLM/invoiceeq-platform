# senior-dev — BE Gap 344: tenant adoption ignores a live API key

Started 2026-08-30. Standalone security fix, found during Feature 25's security review.
Explicitly **not** Gap 340 (sandbox keys) or Gap 341 (widget token) — those are a separate,
larger task landing after this one.

## Ground truth before writing code

- [x] Read `.claude/CONVENTIONS.md` + `active-work.md`
- [x] Read `routers/auth.py` in full — `_tenant_adoption_blockers()`, `provision_tenant()`,
      `_mint_provisioning_api_key()`, `_TENANT_SCOPED_TABLES`
- [x] Verified the real columns on `models.py::Tenant`: `api_key_hash` / `api_key_salt` /
      `api_key_prefix` are all `str | None = Field(default=None)` → NULL means "no key".
      `api_key_scope` is NOT NULL with default `"readonly"`, so it is **not** a usable signal.
- [x] Ordering check for Gap 342: `_mint_provisioning_api_key()` runs only on the
      create-a-new-tenant branch, *after* the adoption-vs-create decision has already been made
      and after the adoption branch has returned. No new tenant is ever re-evaluated for
      adoption in the same request.
- [x] Confirmed the only two writers of `api_key_hash` are `routers/auth.py:210`
      (provisioning mint) and `routers/settings.py:286` (`rotate_api_key`)
- [x] Fresh gap-number collision check — BE tracker max is **343**; repo-wide grep for
      `Gap 344` outside `invoice-website` returns nothing. 344 is free.
      (Website tracker's 345–349 are a separate numbering space.)
- [x] Confirmed `feature_1_auth.md` owns `_tenant_adoption_blockers()` (File Coordinates line 6),
      not `feature_1.1_rbac.md` or `feature_16_settings.md`

## Work

- [x] File the Gap 344 entry in `be_features_tracker.md` (Feature 1)
- [x] `routers/auth.py::_tenant_adoption_blockers()` — add the live-API-key blocker
- [x] Tests in `tests/test_auth.py` — the exact failure scenario + the unaffected-new-tenant case
- [x] Read-only check of real dev Postgres for tenants already in the bad state
- [x] Run `tests/test_auth.py` against real Postgres
- [x] Update `feature_1_auth.md` (additive note)

## Final status

Built and verified 2026-08-30. `tests/test_auth.py` **57 passed** against real Postgres
(`localhost:5433/invoice_db`, container `invoice-postgres-local`), including the
Postgres-only concurrency test — confirmed running, not skipped. No tenant in the local dev
database is in the bad state (0 rows). The Azure-hosted dev DB could not be checked: reading
the credential from Key Vault was denied by the permission classifier — surfaced to the
founder, not worked around. Left uncommitted.
