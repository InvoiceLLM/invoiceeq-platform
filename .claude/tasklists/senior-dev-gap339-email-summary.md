# Gap 339 — email summary output destination (Feature 25 / Task 25.3, first half)

- [x] Fresh gap-number collision check — 339 free; all 9 repo-wide hits are forward
      references to this unbuilt work. True tracker max was 343 (342/343 landed earlier
      today); 344/345 are taken by the *website* tracker (Feature 7 hero switcher).
- [x] Read spec of record + real code (audit.py resolve, outbound_email.py, settings.py
      workflow validation, TenantEmailSender, Invoice/InvoiceLineItem/TaxItem)
- [x] `services/outbound_email.py` — `EmailAttachment` NamedTuple +
      `DEFAULT_ATTACHMENT_MIME_TYPE`; hardcoded `application/pdf` parameterized; new
      `attachments` list param. Legacy single-attachment form unchanged, defaults to pdf.
- [x] `services/invoice_export.py` (new) — one summary dict, two renderers
      (`build_invoice_csv` flat one-row-per-line-item, `build_invoice_json` nested),
      `export_filenames()` sanitising vendor-controlled invoice numbers.
- [x] `services/workflow_outputs.py` (new) — `deliver_email_summary()`; recipients from
      `TenantEmailSender` via `staff_notify.list_registered_emails`, keyed on the
      invoice's direction. Never raises.
- [x] `routers/audit.py` — single trigger inside `resolve_audit_invoice()` after the
      commit, `target_status == "PAID"` only; response gains `email_summary`.
- [x] `routers/settings.py` — `email_summary` moved into the AVAILABLE tuple;
      `_validate_destinations()` now `(values, db_session, tenant_id)` and 422s
      `email_summary` with no registered inbound sender (the hole Gap 336 never had to
      have).
- [x] `models.py` — stale `TenantWorkflowConfig` docstring/comment corrected. No column.
- [x] Tests: `tests/test_workflow_email_summary.py` (23 new cases);
      `tests/test_workflow_config.py` (+2 cases, 1 reparametrised, 1 re-pointed);
      `tests/test_audit.py` (response-shape assertion).
- [x] Runs — 23 passed (new file, 0 skipped) / 171 passed (workflow_config, audit,
      staff_notify, settings, api_keys, email_ingestion, support) / 86 passed
      (outbound_audit, outbound_ingestion, autopilot, rbac). 280 total, exit 0.
- [x] Real-Postgres evidence — `test_approve_sends_email_summary_on_postgres` PASSED in
      19.36s against `postgresql://…@localhost:5433/invoice_db`: JSONB
      `output_destinations` round-trip, recipient query against the real row, both
      credential paths through the real endpoint, both invoices PAID, full cleanup.
- [x] Spec doc body updated (Gap 339 section, File Coordinates, Tasks 25.3 split,
      Verification Plan §10/§11, additive notes on Gap 336's now-stale paragraphs)
- [x] Gap 339 filed in `docs/be_features_tracker.md` + Feature 25 index line updated

Status: complete. Backend only — no FE touched; `invoice-fe`'s wizard still shows the
"Not available yet — BE Gap 339" pill and needs its own FE gap. Gaps 338/340/341 untouched.
