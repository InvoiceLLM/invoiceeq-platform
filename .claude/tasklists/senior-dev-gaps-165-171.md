# senior-dev — FE Gaps 165-171 (Settings / Connectors / Admin / Trainer), 2026-08-05→06

- [x] Gap 167a — Admin Console tile in `app/settings/page.tsx` gated behind `isAdmin` (`role === "Admin"` from `useAuth()`), via a typed `IntegrationTile.adminOnly`
- [x] Gap 167b — `/admin`: "Access Restricted" early return, 401/403 vs. other-failure handling in `loadUsers`, self row + per-user role read from real data
- [x] Gap 168a — backend `DELETE /api/v1/admin/users/{user_ref}` (`remove_tenant_user`): self/Admin guards, tenant-scoped 404, audit-log detach instead of an FK-breaking delete
- [x] Gap 168b — new FE route `app/api/admin/users/[userRef]/route.ts`: backend first, then Clerk account delete; partial success reported honestly
- [x] Gap 168c — `handleRemoveUser` confirms, awaits, drops the row only on success, surfaces errors
- [x] Gap 165 — honest relabel ("Default Browse Folder" / "Start here next time") + new `lib/connectorFolderShortcut.ts`; explorer breadcrumb fixes the id-as-name bug; `ConnectorBrowseBar` now reads *and* writes the shortcut
- [x] Gap 166 — `handleImportSelected` checks `res.ok` per file, aborts on first failure, renders `importError`
- [x] Gap 169 — banner links `${NEXT_PUBLIC_WEBSITE_URL}/login`
- [x] Gap 170 — `handleUploadFile` captures `session.vendorName` (new_vendor only); + scope-switch fallback and a history guard against the empty-vendor→Global resolution
- [x] Gap 171 — `chatDisabledReason` → `QnAPanel disabledReason`: input/chips/send disabled, reason shown inline, typed text never cleared unsent; toast backstop in `handleSendMessage`
- [x] `npx tsc --noEmit` clean (run mid-way and again after the final edits)
- [x] `python -m py_compile routers/admin.py` clean
- [x] Tracker Gaps 165-171 flipped to `[x]`, closed 2026-08-06, with per-gap verification notes
- [x] Feature docs updated: `feature_10_settings.md` (tile gate + admin console), `feature_7_connectors.md` (folder-mapping correction + Task 7.3 import fix), `feature_6_trainer.md` (Gaps 170/171 section)

Not done, deliberately: no automated test added for the new DELETE endpoint — `pytest` is not installed in this workspace's Python env, so the backend suite could not be run at all, and the endpoint has not been exercised against a live backend. Playwright e2e not run (needs a running app).

Status: complete. Changes left uncommitted.
