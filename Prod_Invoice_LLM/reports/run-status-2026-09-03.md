# Autonomous build run 2 — Features 26 & 27
Start 2026-09-03 00:28 local. Hardstop 03:28.
Email unavailable (proved run 1: no MTA, no SMTP env, MCP mail unauthenticated). Not retrying.

[01:05] mins left: 143 | persona: senior-dev
in progress: F27 R7 done, committing; next F27 R8 (doc_attributes)
landed since last: F27 R7 — DOC_TYPES 10->14, families, 4 overlays, PACKING_LIST fold, E5 deferred list deterministic, T-C-6. 728 passed across 10 suites.
gaps filed: none this task (no defects found)
blockers: none

[02:00] mins left: 88 | persona: senior-dev
in progress: F27 R8 done, committing; next F27 R9 (ADVISORY family)
landed since last: F27 R8 — services/doc_attributes.py (direction/subtype/correction/markers/ids/cumulative, all pure Python), doc_attributes JSONB on Invoice+Document, migration a6b7c8d9e0f1 APPLIED to Postgres, node+handler wiring, 40 new tests. 729 passed across 10 suites.
gaps filed: 393 (Invoice.doc_type never written since G9)
blockers: none

[02:25] mins left: 63 | persona: senior-dev
in progress: F27 R9 done, committing; next F26 R9 (Tier 3) per the run order
landed since last: F27 R9 — ADVISORY_FAMILY + _ADVISORY_RUBRIC, ReferencedDocument/DeductionItem schemas, referenced_documents[]/payment_deductions[], family stance, T-R-8 (6 tests). 735 passed.
gaps filed: none this task
blockers: none
note: A7 named its field `deductions[]`, which collides with InvoiceExtractionSchema's own `deductions` and broke A2's disjointness invariant. Renamed to `payment_deductions` -- deviation recorded in code + commit.
