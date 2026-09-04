# Gap 427 — Autopilot sync history: per-file rows -> runs

- [x] 1. models.py: TenantAutopilotLog + batch_id / trigger / source_file_name, index (tenant_id, batch_id)
- [x] 2. Alembic migration (nullable cols + index); single head before/after
- [x] 3. services/autopilot_sync.py: thread batch_id/trigger/file_name through _write_log; NO_NEW_FILES row
- [x] 4. routers/autopilot.py: GET /history returns runs; GET /history/{batch_id}/files; /history/legacy/files
- [x] 5. tests/test_autopilot.py: grouping, status derivation, legacy bucket, tenant isolation, NO_NEW_FILES
- [x] 6. Run tests/test_autopilot.py on real Postgres
- [x] 7. Docs: feature_9_connectors.md body + be_features_tracker.md Gap 427

Final status: DONE, uncommitted. Migration a1b2c3d4e5f7 (single alembic head before and
after). `pytest tests/test_autopilot.py -q` -> 33 passed in 14.69s against real Postgres
(localhost:5433) with the migration applied. Nothing committed or pushed.
