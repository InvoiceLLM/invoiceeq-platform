# Active work — read before starting any task

_Last updated: 2026-09-02. Founder maintains this file. If it is more than ~1 week old, ask the founder before trusting it. Agents never edit this file — flag discrepancies in chat instead._

> **Note on this revision (2026-09-02):** the sections below were refreshed by the Wave 0
> documentation-reconciliation dispatch, which was explicitly scoped to update this file.
> That conflicts with the "agents never edit this file" line above, which is left in place
> unchanged; the founder should decide whether that rule now reads "agents never edit this
> file *unless the approved scope names it*" or whether this update should be reverted.
> Flagged rather than silently resolved.

## Current direction
- **Feature 27 (generic extraction) and Feature 26 Part 2 (chat attached documents) are the active build.** Both are behind flags defaulting `False` — `ENABLE_GENERIC_EXTRACTION` and `ENABLE_GENERIC_DOC_CHAT` — and **neither is safe to enable in a user-facing deployment**. F27: correct behind the flag on the extraction/verification path, but a classified non-invoice has no FE surface, so it is invisible to whoever uploaded it (§2A/N1's rollout gate, half-closed by G14, still shut on G11). F26 Part 2: none of §P2.8's answer contract reaches the browser from a real backend at all (see Open contradictions).
- Neither feature has executed test evidence proportional to what has shipped. Several slices are **code-complete and unverified**: F27's `tests/test_documents_table.py` has no recorded run and its Alembic migration has never been applied to Postgres; F26's flag-OFF parity tests and H12's Playwright spec have no recorded run either. Treat "built" in those trackers as "written and reviewed", not "proven".
- Ops visibility: F24 Ops Digest deleted 2026-08-25 (design record in git, bce9e38); current path is one recommendation pass on the existing workbooks — see `feature_20_23_24_ops_workbook.md` (consolidated doc).
- Doc consolidation done 2026-08-25: four F20/23/24 docs → one, two F21 docs → one. Old filenames are gone; do not recreate them.
- CI/CD rule (reaffirmed, Gap 312): no test/benchmark execution in the deploy pipeline, ever.
- Gap 253 resolution pattern: execution-time regex SQL rewriter deleted, replaced by dialect-conditioned prompt rule — basis of CONVENTIONS.md hard rule 3.
- Chat prompts: shared CHAT_PERSONA_BLOCK retrofitted onto all 4 default prompts (Gap 313).
- Custom domain: Path B (Front Door + WAF) chosen; remaining work is manual/external (DNS, cert, Clerk prod cutover) — bicep compile-verified only, never applied.

## In flight
- **Feature 27 — open items.** G6's remainder (E9's `UnknownFlowDirectionError` fail-loud), G8 (`document_to_base64_images` + image dispatch), G11 `[~]` (FE: `DropZone` accept-list widening **blocked** on there being no mechanism to expose a backend `ENABLE_*` flag to the FE, and no documents-list surface), **task F** (fixture sourcing, at ~2 of 10 document types — this is what blocks verification), and **task V** (not started; blocked on F). Also open and needing a scoped dispatch: §2A/A4/F5's required ingestion-dedup ruling, never made in code or prose (BE Gap 381).
- **Feature 26 Part 2 — open items.** H6 (Tier 3 candidate matching), H6b (`compare_documents()` + the L1–L3 line-item matcher; sequenced last), H7 (async wiring — do not flip the flag), H8 (`scripts/sweep_chat_attachments.py`; the TTL setting itself already exists from H4), H9 (infra: `chat-doc-ttl-job-only.bicep`, infra-devops), H13 (additive FE spec section in `feature_5_chat.md`), and the **V** tasks (§P2.10 against Postgres + real Redis, including V-25's live-model injection probe — functional-tester's, never attempted).
- ~~senior-dev — F23 3-way model comparison~~ — **closed 2026-09-01, not completed**: superseded by a founder decision, recorded in the tasklist and in the Feature 23 Phase 4 tracker entry. No longer in flight. (A GPT-4o-only rerun, dropping the Ollama arm, is named there as optional future work.)
- senior-dev — arch-docs Gap 244 support (`senior-dev-arch-docs-gap244-support.md`): **stale** — untouched since 2026-08-18, every item still unchecked, status line still says "In progress". Founder to confirm whether abandoned or resuming before anyone touches it. Unchanged from the 2026-08-25 entry.

## Frozen / do not touch
- **No taxonomy/schema amendment work** — the founder's draft A/B-series proposal — starts until **F27's existing ledger closes** (G6 remainder, G8, G11, F, V, and the A4/F5 ruling) **and its flag-safety equality test passes against real Postgres**. Amending the taxonomy on top of an unverified ledger would put two unproven layers underneath each other.
- SAGE Phase 3 — gated on Gap 310's real-world result; 4 product decisions deliberately unresolved (see `feature_21_sage.md`). Do not start or "resolve" them.
- F24 Ops Digest — deleted; do not rebuild without a founder decision.
- Gap 225 verification scope — closed by product decision, arithmetic-only; do not build semantic checks.
- Gap 306 — known, deliberately NOT fixed; fix must be structural, no quick patches.
- SAP/QuickBooks integrations — deferred until confirmed paying customer.
- Monitoring Reader RBAC — declared, never deployed (open blocker, not frozen work).
- `files_logs/` — superseded pre-rebuild draft; ignore, don't reference, don't delete without founder call.

## Open contradictions (founder to resolve, agents just avoid)
- **BE/FE Gap 378 number collision — resolved by disambiguation on 2026-09-02, NOT re-opened.** 378 is used once per tracker for unrelated work: **BE Gap 378** = Feature 26 Part 2 task H5; **FE Gap 378** = Feature 27 task G11. Neither was renumbered (both are referenced from several files; renumbering would orphan those references) — both entries carry a disambiguation note, and the numbering rule now lives under "Open Items / Gaps" in `be_features_tracker.md`. **Always write "BE Gap 378" / "FE Gap 378", never a bare "Gap 378".**
- **Unfiled BE item — the chat answer-contract plumbing.** `routers/chat.py::MessageResponse` declares only `content`/`generated_sql`/`citations`/`status`/`job_id`/`error_message`, and `run_sync_chat_turn()` persists the assistant `ChatMessage` row with `content`/`generated_sql`/`citations`/`result_invoice_ids` — so **every** Feature 26 attachment key is dropped before serialisation and a session reload has nothing to restore. Nothing on §P2.8's contract reaches a browser from a real backend, regardless of what H11 renders or H12 wires. Not filed as its own gap: it needs a founder call on persist-vs-transient (persisted columns / side table vs. transient response fields).
- `infra-devops-custom-domain-integration.md` header says DONE, its final-status section says Paused — trust neither until reconciled.
- 2026-08-25 doc consolidation violated hard rule 4 (6 approved specs deleted/rewritten) — rule vs. practice needs a founder ruling (allow consolidations as an explicit exception, or don't).
- Gap-number mismatch: `gap_investigation_2026-08-13.md` uses provisional numbers (its "Gap 220" shipped as tracker Gap 223) — tracker numbers are authoritative. Same class of problem, live right now in code: `agents/query_agent.py` and `tests/test_chat_doc_content_branch.py` cite "Gap 380" for work that is **BE Gap 382**.
