# invoice-be Test Coverage Map

Live record of what's actually automated vs. manually verified, and when. Maintained by `functional-tester` per `.claude/CONVENTIONS.md`. Not the same as a `feature_N_*.md`'s Verification Plan (stable design intent) — this is the running log of real test execution.

Automated suite lives at `apps/invoice-be/tests/` (pytest, see `docs/feature_13_test_benchmark_suite.md`).

| Gap / Feature | Test type | Automated or manual | Last verified | Evidence |
|---|---|---|---|---|
| Gap 131 (Google Drive / Salesforce `redirect_uri_mismatch`) | Manual, real backend, real dev Google/Salesforce OAuth client IDs, Playwright headless nav to real authorize URLs | Manual | 2026-08-11 | `test_evidence/gap131_179_oauth_dev_verification/` (2 screenshots + README + log) — CONFIRMED-FIXED in dev: `GET /connectors/auth-url/{provider}` returns the correct `.env`-configured `redirect_uri`, both Google and Salesforce accept it (real sign-in screens render, no `redirect_uri_mismatch`). Full token exchange not completable by an automated agent (same limitation as FE's Gap 96 evidence). Prod out of scope (placeholder OAuth creds, no prod RG yet) |
| *(remaining gaps — populate as functional-tester runs scenarios)* | | | | |
