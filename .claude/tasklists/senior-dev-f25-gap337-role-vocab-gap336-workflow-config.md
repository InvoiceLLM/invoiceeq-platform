# senior-dev — Feature 25: Gap 337 (retire "Viewer") then Gap 336 (TenantWorkflowConfig)

Two gaps, in sequence. 337 first (smaller, foundational), verified, then 336.

## Gap 337 — retire "Viewer" from the role vocabulary
- [x] 1. Read spec + ground truth (feature_25, feature_1.1_rbac, RoleMapper, dependencies.py Gap 335 code)
- [x] 2. Collision-check Gap numbers 336/337 fresh against the BE tracker — true max is **335**; 336/337 free (only referenced as *planned* in the F25 spec/tracker)
- [x] 3. `models.py::RoleMapper` — `NO_ROLE = "Restricted"` + `USER_FACING_ROLES = ("Admin","Auditor","Trainer")`; Viewer key/aliases retired
- [x] 4. `dependencies.py` — 6 sites: normalize_role default, unmapped fallback, org-mismatch clamp (x2), mock-token role, key-auth role + service-user role
- [x] 5. `routers/admin.py` — new-user default role + detach demotion target
- [x] 6. `agents/support_agent.py` — live 3-role copy now Admin/Auditor/Trainer (+ "everyone" line)
- [x] 7. Alembic data migration `e9f0a1b2c3d4` off the real head `d8e9f0a1b2c3`
- [x] 8. Tests: test_rbac (+4 new Gap 337 cases), test_api_keys, test_auth, test_audit, test_billing, setup_test_tenants
- [x] 9. `pytest tests/test_rbac.py tests/test_api_keys.py` -> **74 passed**; `tests/test_auth.py tests/test_audit.py tests/test_billing.py tests/test_settings.py` -> **94 passed**. Postgres: upgrade rewrote a seeded legacy 'Viewer' row to 'Restricted', downgrade restored it, probe row cleaned up
- [x] 10. Docs: feature_25 narrative, additive note in feature_1.1_rbac, tracker Gap 337 entry

## Gap 336 — TenantWorkflowConfig + wizard endpoint
- [x] 11. `models.py::TenantWorkflowConfig` (shaped after TenantAutopilotConfig)
- [x] 12. Alembic migration `f0a1b2c3d4e5` off the real head `e9f0a1b2c3d4`
- [x] 13. `routers/settings.py` — GET/PUT /settings/workflow, Admin-gated on **both** verbs (deviation from vendor-flow's open GET, recorded)
- [x] 14. audit_policy -> `Tenant.api_key_scope` write-through in one commit; GET **derives** the policy back from the tenant column so the two cannot drift
- [x] 15. Validation: 422 for `email_summary`/`drive_archive` naming the owning gap; validation before any write
- [x] 16. `tests/test_workflow_config.py` — 23 cases
- [x] 17. **23 passed**; regression set (workflow + settings + api_keys + auth) **108 passed**. Postgres: migration applied, jsonb types confirmed, `UniqueViolation` + `ForeignKeyViolation` both exercised for real, downgrade/upgrade round-tripped, probe rows cleaned up
- [x] 18. Docs: feature_25 (Gap 336 section, File Coordinates, Task 25.2, Verification Plan §6/§7), tracker Gap 336 entry + additive update on Gap 335

Final status: **both gaps complete and verified.** Gap 337 — 168 tests green across 6 files, data
migration `e9f0a1b2c3d4` exercised up and down on real Postgres. Gap 336 — 23 new tests + 108-test
regression green, migration `f0a1b2c3d4e5` plus UNIQUE/FK constraint behaviour proven on real
Postgres. All changes left uncommitted for review. Deviations recorded in the spec and tracker:
no `routers/workflows.py` (endpoints live in `settings.py`), GET is Admin-only, and
`chat_access="widget"` is accepted-but-inert pending Gap 341.
