# BE Feature 28: Non-PDF Invoice Upload (Image → PDF at the Boundary) — build
Spec: Prod_Invoice_LLM/apps/invoice-be/docs/feature_28_image_upload_pdf_boundary.md
Started: 2026-09-04 18:05
Hard stop: 2026-09-04 22:05
Definition of done: every task below checked; every Verification Plan item run and cited;
spec body and tracker updated; changes uncommitted.
Status: complete (feature marked `[~]`, not `[x]` — see 28.9)

- [x] 28.1 `services/file_intake.py`: `sniff_format`, `ACCEPTED_*` constants, `ACCEPTED_FORMATS_DETAIL`, `convert_image_to_pdf` (deterministic output, pixel cap, multi-frame TIFF), `normalize_upload`, the two exception classes. Pure functions, no DB, no I/O beyond bytes.
- [x] 28.2 `routers/invoices.py::upload_invoices()` and `start_directory_watcher()` onto `normalize_upload()`; 400 mapping for both exception classes.
- [x] 28.3 `routers/outbound_invoices.py::upload_outbound_invoice()` onto `normalize_upload()`.
- [x] 28.4 `routers/trainer.py::upload_transient_file()` onto `normalize_upload()`.
- [x] 28.5 `routers/email_ingestion.py`: attachment filter by sniffed format, normalise per attachment, updated drop-reason detail text (constant name unchanged).
- [x] 28.6 Google Drive: `utils/connector_files.py::list_google_drive_files()` mime widening; `services/autopilot_sync.py` and `queue_worker/handlers.py` connector import normalise after download.
- [x] 28.7 Tests: `tests/test_file_intake.py` (unit) and `tests/test_invoice_upload_formats.py` (router-level, five doors), plus fixtures under `tests/fixtures/image_uploads/`.
      done 2026-09-04: fixtures were already on disk from the prior run; wrote both test files. Postgres runs: `test_file_intake.py` -> `32 passed in 34.47s`; `test_invoice_upload_formats.py` -> `22 passed in 65.99s`.
- [x] 28.8 Existing-test sweep: every test asserting `"Only PDF is allowed."` or a non-PDF 400 updated to the new message and accept rule.
      done 2026-09-04: updated 4 tests in test_ingestion.py / test_outbound_ingestion.py / test_trainer.py to assert ACCEPTED_FORMATS_DETAIL, added an outbound photo-accept smoke test and a drop-detail assertion in test_email_ingestion.py. Postgres run of all four files: `122 passed in 22.98s`. Repo-wide grep for the retired strings returns only the explanatory comment in services/file_intake.py:50.
- [x] 28.9 Doc + tracker close-out: spec §6 recorded runs; additive "accepts images since Feature 28" line in feature_2_pipeline_extraction.md / feature_2.1_vendor_flow_ingestion.md / feature_14_email_ingestion.md / feature_9_connectors.md; be_features_tracker.md row updated.
      done 2026-09-04: spec Tasks all ticked, §3 gained the two-size-ceilings note, §6 gained a "Recorded runs" table with every verbatim result line; all four related feature docs annotated; BE Gap 458 filed and closed in be_features_tracker.md; Feature 28 row set to `[~]` **not** `[x]` — the `done` gate fails item 2 because the Verification Plan's "Manual, Azure path" row was not run.

Final status 2026-09-04: tasks 28.1–28.9 complete. Postgres runs: 32 / 22 / 122 passed on the targeted files; full suite 43 failed, 3027 passed, all failures in six untouched files. Feature row `[~]` pending the manual Azure check. Nothing committed.
