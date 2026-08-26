# Active work — read before starting any task

_Last updated: 2026-08-25. Founder maintains this file. If it is more than ~1 week old, ask the founder before trusting it. Agents never edit this file — flag discrepancies in chat instead._

## Current direction
- Ops visibility: F24 Ops Digest deleted 2026-08-25 (design record in git, bce9e38); current path is one recommendation pass on the existing workbooks — see `feature_20_23_24_ops_workbook.md` (consolidated doc).
- Doc consolidation done 2026-08-25: four F20/23/24 docs → one, two F21 docs → one. Old filenames are gone; do not recreate them.
- CI/CD rule (reaffirmed, Gap 312): no test/benchmark execution in the deploy pipeline, ever.
- Gap 253 resolution pattern: execution-time regex SQL rewriter deleted, replaced by dialect-conditioned prompt rule — basis of CONVENTIONS.md hard rule 3.
- Chat prompts: shared CHAT_PERSONA_BLOCK retrofitted onto all 4 default prompts (Gap 313).
- Custom domain: Path B (Front Door + WAF) chosen; remaining work is manual/external (DNS, cert, Clerk prod cutover) — bicep compile-verified only, never applied.

## In flight
- senior-dev — F23 3-way model comparison (`.claude/tasklists/senior-dev-f23-3way-model-comparison.md`): sanity round done, three graded runs starting; items 7–15 open.
- senior-dev — arch-docs Gap 244 support (`senior-dev-arch-docs-gap244-support.md`): all items unchecked, no final status — founder to confirm whether abandoned or resuming before anyone touches it.

## Frozen / do not touch
- SAGE Phase 3 — gated on Gap 310's real-world result; 4 product decisions deliberately unresolved (see `feature_21_sage.md`). Do not start or "resolve" them.
- F24 Ops Digest — deleted; do not rebuild without a founder decision.
- Gap 225 verification scope — closed by product decision, arithmetic-only; do not build semantic checks.
- Gap 306 — known, deliberately NOT fixed; fix must be structural, no quick patches.
- SAP/QuickBooks integrations — deferred until confirmed paying customer.
- Monitoring Reader RBAC — declared, never deployed (open blocker, not frozen work).
- `files_logs/` — superseded pre-rebuild draft; ignore, don't reference, don't delete without founder call.

## Open contradictions (founder to resolve, agents just avoid)
- `infra-devops-custom-domain-integration.md` header says DONE, its final-status section says Paused — trust neither until reconciled.
- 2026-08-25 doc consolidation violated hard rule 4 (6 approved specs deleted/rewritten) — rule vs. practice needs a founder ruling (allow consolidations as an explicit exception, or don't).
- Gap-number mismatch: `gap_investigation_2026-08-13.md` uses provisional numbers (its "Gap 220" shipped as tracker Gap 223) — tracker numbers are authoritative.