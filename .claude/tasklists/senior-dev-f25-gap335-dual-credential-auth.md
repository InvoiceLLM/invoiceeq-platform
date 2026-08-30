# senior-dev — BE Feature 25 Phase 0, Gap 335: dual-credential auth + two-tier API key scope

Scope: auth/scope foundation only. No `TenantWorkflowConfig` (Gap 336), no sandbox keys
(Gap 340), no output destinations (Gaps 338/339), no `RoleMapper` edits (Gap 337),
nothing in invoice-fe / invoice-website.

- [x] 1. Read `.claude/CONVENTIONS.md` + `active-work.md`
- [x] 2. Read ground truth: `dependencies.py` (Gap 184 block), `models.py` (Tenant/User/AuditLog/RoleMapper), the 5 routers, alembic head
- [x] 3. Write `docs/feature_25_plug_and_play_workflows.md` (spec first, no code without a gap)
- [x] 4. File tracker: Feature 25 index line + Gap 335 entry (fresh collision check)
- [x] 5. Additive one-sentence pointer in `feature_16_settings.md` (do NOT rewrite Gap 184's body)
- [x] 6. `models.py`: `Tenant.api_key_scope` (default `readonly`, fail-closed)
- [x] 7. Alembic migration off head `a7c3d5e91f04`
- [x] 8. `dependencies.py`: `TenantContext.auth_method` + `key_scope`
- [x] 9. `dependencies.py`: `get_tenant_or_api_key_context()`
- [x] 10. `dependencies.py`: scope-derived permissions in `resolve_api_key_context()` (replace hardcoded Viewer)
- [x] 11. `dependencies.py`: `require_key_scope()` + `require_permission_or_api_key()`
- [x] 12. `dependencies.py`: `resolve_api_key_service_user()` (AuditLog FK fix)
- [x] 13. Rewire `routers/invoices.py` reads + upload
- [x] 14. Rewire `routers/chat.py` session/message/job endpoints
- [x] 15. Rewire `routers/audit.py` router-level dependency
- [x] 16. Rewire `routers/outbound_audit.py` router-level dependency
- [x] 17. Gate `routers/outbound_invoices.py` confirm-send / mark-paid (pre-existing hole)
- [x] 18. `routers/admin.py`: hide the synthetic service user from the Admin user list
- [x] 19. Update `tests/test_api_keys.py` Viewer assertion → scope-derived
- [x] 20. Run narrow tests; report honestly (SQLite vs Postgres)
- [x] 21. Update spec body + tracker status to match what actually got built

Final status: **DONE.** 172 tests passed (exit 0) across 10 affected files; migration d8e9f0a1b2c3 applied to local Postgres and the AuditLog service-user FK verified there in both directions. Azure dev DB NOT migrated; no deployed end-to-end call. Gap 336 (TenantWorkflowConfig) and Gap 337 (RoleMapper) are unblocked and untouched.
