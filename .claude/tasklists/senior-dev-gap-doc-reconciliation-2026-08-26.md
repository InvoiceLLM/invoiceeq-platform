# Doc-reconciliation pass — F20/23/24 tracker + spec, 2026-08-26

Docs-only. Additive corrections only (CONVENTIONS hard rule 4) — no approved text deleted or rewritten,
every fix lands as a dated `**Correction 2026-08-26:**` note next to the stale claim.
Source of truth for the 7 findings: the live-Azure-verified architect audit of 2026-08-26 (trusted,
not re-verified here — no `az` command is run by this task).

Files: `Prod_Invoice_LLM/apps/invoice-be/docs/be_features_tracker.md`,
`Prod_Invoice_LLM/apps/invoice-be/docs/feature_20_23_24_ops_workbook.md`.

- [x] 0. Read CONVENTIONS.md, `active-work.md`, both target docs; checked `.claude/tasklists/` — the only recent
      overlapping runs (Gaps 318/319/320) are all closed with a final status, so no parallel work on these two files
- [x] 1. Tracker: Feature 24 row `[~]` → `[x]` superseded + Correction note pointing at Gap 311 (code deleted 2026-08-25) — header line + checkbox changed, 10-item deletion list restated, body untouched
- [x] 2. Tracker: Feature 23 Phase 2 row `[~]` → `[x]` superseded + Correction note (old tabbed workbook deleted/replaced 2026-08-25) — verified on disk that `ai_control_tower.workbook.json` is gone and `llm_cost_rollup_nightly.kql` remains (so the "still unscheduled" half is kept, not over-closed)
- [x] 3. Tracker: Gap 295 `[ ]` → `[x]` + Correction note with the live budget evidence (₹20,000/mo, 50/75/95% actual); the ₹20,000-vs-₹24,600-forecast concern recorded as flagged-not-fixed
- [x] 4. Spec: blockers-table alert-rule row — corrected "deliberately not run" → deployed and live (`alert-ca-invoice-be-dev-cpu-high`, both criteria), original wording kept inline; table intro gained a 4-struck/4-open summary
- [x] 5. Spec: blockers-table `chat_turn`/GenAI-span/`AppRequests` row + nightly-job `FileNotFoundError` row — both struck through, resolved by the 2026-08-25T14:41Z image (`cb96d8f`) + the successful 2026-08-26T03:00 `caj-benchmark-eval-dev` run; each row states explicitly that `ops_recommendation` is NOT closed by it
- [x] 6. Spec: real-data-vs-structurally-empty table — `chat_turn` and `extraction_benchmark_run` → real data; `ops_recommendation` left structurally empty, with a clarification that it needs a *further* image (318/319 uncommitted), since "same refresh as the rows above" stopped parsing once those rows flipped
- [x] 7. Tracker: Gap 298 duplicate — canonical = the copy under `## Open Items / Gaps`; the copy under `## Feature 23` is now headed as the duplicate + "do not update this copy", its body kept verbatim below the header. The duplicate's 2 unique facts (standalone-template pattern; CI/CD's `az containerapp update` bypass of bicep) folded into the canonical entry. Cross-referenced by section name, not line number, since line numbers move. Both stay `[ ]` — genuinely still open.
- [x] 8. Tracker: Gap 292 — note added that the `AppRoleName = unknown_service` / missing `OTEL_SERVICE_NAME` finding is still unnumbered. Verified by repo-wide grep: exactly 1 hit across all of `Prod_Invoice_LLM/`, that paragraph itself. No number assigned, no fix attempted.
- [x] 9. Spec: knock-on consistency from item 5 — corrected the "Not yet built" prerequisite bullet's "one thing is still open" paragraph, the prerequisite Tasks line, and the open `[ ]` "Deploy the pending backend image" task (now `[x]`, with a NEW `[ ]` task for the *further* 318/319 image so that work isn't silently lost). Also added the live budget confirmation to the spec's own budget bullet so both docs now cite the same evidence for Gap 295.
- [x] 10. Verified rather than eyeballed. (i) Wrote a script that takes every line of both files **as of `HEAD`**,
      strips the leading `- \`[ ]\`` marker, and asserts it still appears in the working copy — then hand-checked the
      handful of flagged lines, which are all either my own 5 whole-line checkbox/header replacements (original body
      text confirmed present verbatim by a second substring check, 22/22 OK, 0 lost) or the pre-existing uncommitted
      Gap 318/319/320 edits from earlier sessions, not mine. (ii) `git diff` on the tracker: **9 deleted lines, of
      which 5 are mine and all 5 are line replacements whose content was carried forward**. (iii) Markdown table
      integrity checked programmatically — every table row in the spec has a consistent unescaped-pipe count
      (3 / 5 / 6 by table), no broken rows.
- [x] 11. Final status here; summary reported in chat, including the flag-only items.

Final status: **DONE.** All 7 corrections applied plus the 8th (unnumbered `AppRoleName` finding) noted-not-numbered.
Docs-only — no application code, bicep, test or `az` command touched, so no pytest run applies. Every fix is additive:
5 tracker lines and 6 spec lines were replaced in place, each carrying its original text forward inside the new text,
and everything else is new `**Correction 2026-08-26:**` / `**Note**` / `**Reconciliation**` blocks. Nothing was deleted.

Two items flagged for the founder rather than acted on (both deliberately out of scope):
1. **₹20,000 budget vs. ~₹24,600 forecast** — Gap 295 is genuinely fixed and live, but the amount sits below the
   forecast, so 50%/75% will likely fire every month. Possible follow-up; not changed.
2. **`AppRoleName = unknown_service`** — still unnumbered after 3 days; grep confirms exactly one mention in the whole
   of `Prod_Invoice_LLM/` (inside Gap 292). No number assigned, no fix attempted — founder call.

Two smaller things found while editing, recorded here rather than silently fixed or silently ignored:
3. The spec's `chat_turn` blocker row contained an **unescaped `|`** inside `` `GenAI | az.ai.openai` ``, which breaks
   that row's markdown table rendering. Escaped to `\|` while rewriting the row — rendered text identical.
4. Tasks line "AI Control Tower workbook built, deployed, live-verified (**49/49** items byte-identical)" is stale
   post-Gap-320 (it is 51 items now, and the doc's own header table says so). Left alone — Gap 320's residue, outside
   this pass's approved 7 + 1.
