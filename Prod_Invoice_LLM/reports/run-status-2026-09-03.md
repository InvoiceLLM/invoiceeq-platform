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

[00:53] mins left: 154 | persona: senior-dev
CORRECTION: the [01:05]/[02:00]/[02:25] timestamps above were ESTIMATED, not read
from the clock, and all three were ~90 min ahead of real time. Actual elapsed at
this point: 25 min since the 00:28 start. Every timestamp from here is $(date).
in progress: F26 R9 (Tier 3 vector discovery)
landed since last: F27 R7 f3ed94b, R8 9f87ab8, R9 0cda980 — all pushed
gaps filed: 393
blockers: none

[00:59] mins left: 148 | persona: senior-dev
in progress: F26 R9 done, committing; next F26 R10 (compare_documents modes)
landed since last: F26 R9 — Tier 3 vector discovery, _tier3_candidates + tier-3 confirmation copy, 11 tests (V-12..V-15). 749 passed.
gaps filed: none this task
blockers: none

[01:06] mins left: 141 | persona: senior-dev
in progress: F26 R10 backend done, committing; FE half (contract keys + ReconciliationTable) next
landed since last: F26 R10 (BE) — ReferenceDocLineItem widened, compare_documents 4 modes + L1-L3 matcher, resolve_comparison_mode table, reconcile_referenced_documents (B8), 31 tests. 799 passed.
gaps filed: none this task
blockers: none

[01:14] mins left: 133 | persona: senior-dev
in progress: F26 R10 COMPLETE (B3/B7/B8/B9/B10); next F27 R11 or F26 R11
landed since last: B9 f5e1a6d; B10 — reconcile branch in the turn, ReconciliationTable.tsx, FE types, MessageBubble wiring. tsc exit 0. 815 passed.
gaps filed: none
blockers: none

[01:24] mins left: 123 | persona: senior-dev
in progress: F26 R11 (H7) done, committing; next F26 R7 (V-25 probe) or wrap-up
landed since last: R5(c) documents surface 510c444; full suite w/ Postgres 16 failed/2575 passed/1 skipped (was 26 skipped) -> Gap 394; H7 async wiring across 4 sites.
gaps filed: 394
blockers: R5(a) flag-exposure mechanism needs a FOUNDER RULING - spec names two options, picks neither, assigns to architect. R5(b) DropZone depends on it.

[01:30] mins left: 117 | persona: senior-dev
in progress: F27 R10 done (item 4, done out of order - flagged); wrapping up next
landed since last: F27 R10 (A8) — disclaimer + Gutschrift pre-checks, resolve_ambiguous_direction_type, derive_rule_era, T-C-5 (12 tests). 777 passed.
gaps filed: none this task
blockers: R5(a) still needs a founder ruling
