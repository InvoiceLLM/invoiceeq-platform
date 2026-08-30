# Gap 338 — Google Drive write-back (`drive_archive` output destination)

Feature 25 / Task 25.3, second half. Same convergence point and same
never-raises contract as Gap 339's `email_summary`, not a parallel mechanism.

- [x] 1. Read the spec of record + Gap 339's implementation (workflow_outputs, invoice_export, settings validation, audit trigger)
- [x] 2. Fresh gap-number collision check across the BE tracker + repo-wide
- [x] 3. OAuth scope: `drive.file` added alongside the existing `drive.readonly` in `routers/connectors.py` (both real + mock auth URLs)
- [x] 4. `utils/connector_oauth.py` — tokeninfo probe: granted-scope detection + `drive.file`/`drive` write check
- [x] 5. `utils/connector_files.py` — `upload_google_drive_file()` + app-owned archive folder find-or-create
- [x] 6. `services/invoice_export.py` — share the filename sanitiser, add the PDF filename (no third serializer)
- [x] 7. `services/workflow_outputs.py` — `drive_archive_readiness()` (the re-consent detector) + `deliver_drive_archive()` (never raises)
- [x] 8. `routers/settings.py` — `drive_archive` into AVAILABLE, "connected + adequately scoped" validation in `_validate_destinations()`
- [x] 9. `routers/audit.py` — trigger next to the Gap 339 block, PAID only, response gains `drive_archive`
- [x] 10. `tests/test_workflow_drive_archive.py` — new file, Drive API mocked, incl. a real-Postgres checkpoint
- [x] 11. Update `tests/test_workflow_config.py` (drive_archive no longer 422'd) and `tests/test_audit.py` (exact-response assertion)
- [x] 12. Run the affected test files only; capture the Postgres evidence -- 147 passed across 7 files, 0 skipped; the Postgres checkpoint ran against localhost:5433/invoice_db
- [x] 13. `infra/THIRD_PARTY_INTEGRATIONS_SETUP.md` — additive scope note (both scopes on the consent screen, the app-created folder, the reconnect requirement)
- [x] 14. Spec body (`feature_25_plug_and_play_workflows.md` — new Gap 338 section, File Coordinates, Task 25.3 closed, Verification Plan §12/§13) + tracker Gap 338 entry filed

Final status: **done 2026-08-30.** Gap 338 built and verified — 147 tests passed
across 7 affected files, 0 skipped, including a real-Postgres checkpoint
(`test_approve_archives_to_drive_on_postgres`, PASSED, localhost:5433) that
proves both credential paths *and* the reconnect-required path. Drive API calls
mocked (no Google account here); no schema change; no forced re-auth for
already-connected tenants. Left uncommitted per repo convention. Not done and
not claimed: the Google Cloud Console consent-screen scope addition (manual
operator step) and the FE surface.
