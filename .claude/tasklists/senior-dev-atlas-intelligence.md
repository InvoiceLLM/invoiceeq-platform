# Feature 35: ATLAS Intelligence (BE) + Feature 24: the briefing (FE) — build
Spec: Prod_Invoice_LLM/apps/invoice-be/docs/feature_35_atlas_intelligence.md · Prod_Invoice_LLM/apps/invoice-fe/docs/feature_24_atlas_briefing.md
Branch: feature/atlas-intelligence (off master ca71223)
Started: 2026-09-20 16:05
Hard stop: 2026-09-20 20:05
Definition of done: every task below checked; every Verification Plan item run and cited;
spec body and tracker updated; changes uncommitted.
Status: tracks 0-3 + BE Gaps 714/716 complete; FE tasks 24.1-24.6 built and unit-verified 2026-09-20, uncommitted; 35.10 and 24.7 (live/screenshot verification) still open

## Track 0 — infra-devops
- [x] 35.0 Terra deployment (infra-devops). Create the `gpt-5.6-terra` deployment on the dev Azure OpenAI account first, by CLI, so the first live run is unblocked; then codify it in `infra/model-deployment.bicep` (the existing per-model deployment module, not a new file), add `AZURE_OPENAI_ATLAS_DEPLOYMENT_NAME` to the compute bicep modules, `.env.example`, `params.dev.json` / `params.prod.json`, and update `infra/README` and the cost table in `infra/monitoring/ai_control_tower_workbook.json` with Terra's price. Record capacity and price in the tracker.

## Track 1 — senior-dev
- [x] 35.1 `services/atlas_tools.py` — `ToolSpec`, registry, `tools_for(grants)`, `run_tool()`, and the ten adapters with record-id serialisers. `ask_sage` limited to one call per run inside `run_tool()`. Done 2026-09-20: `tests/test_atlas_tools.py` 21 passed on Postgres.
- [x] 35.2 `MockInvoiceLLM.bind_tools()` with a scripted tool-call sequence, so the loop is testable without Azure. Blocks every later test. Done 2026-09-20: `tests/test_atlas_mock_tools.py` 9 passed; returns real `AIMessage`s.
- [x] 35.3 `utils/model_registry.py` `atlas` role + `config.py` setting. Done 2026-09-20: `tests/test_model_registry.py` + `tests/test_no_hardcoding.py` 37 passed (the pinned `Role` set in `test_there_is_no_long_doc_role_after_29_10` was extended by one).

## Track 2 — senior-dev (after track 1)
- [x] 35.4 `agents/atlas_agent.py` — the loop with the three caps and the emitted-id set; `agents/atlas_prompts.py`. Done 2026-09-20: `tests/test_atlas_agent.py` 19 passed on Postgres; generator, caps 6/12/20s each emitting `truncated{reason}`, deterministic JSON parse (no `with_structured_output`).
- [x] 35.5 `services/atlas_contract.py` — `Citation`, `BriefingParagraph`, `BriefingEvent`, the two guards. Done 2026-09-20: `tests/test_atlas_briefing_contract.py` 20 passed on Postgres; `BriefingRun.rendered_tokens` added and filled in `run_tool()`; falsification test proves the guard is load-bearing. BE Gap 714 filed (pre-existing vendor-name flake in `tests/test_atlas_tools.py`). As built in spec §10.

## Gap work — BE Gap 714 (before track 3, founder: "fix gap 714 and then go track3")
- [x] BE Gap 714: `verbatim_references()` in `services/atlas_contract.py`, applied at all ten
  emitter call sites (skills x4, forecast x1, recon x3, doubt x1). Done 2026-09-20:
  `test_atlas_skills.py` + `test_atlas_forecast.py` **25 passed**; `test_atlas_tools.py`
  **21 passed x 20 consecutive runs**; all `test_atlas_*.py` + `test_no_hardcoding.py`
  **243 passed**. Falsification: helper stubbed ⇒ 5 failed. Spec §19, tracker `[x]`.

## Track 3 — senior-dev (after track 2)
- [x] 35.6 `models.AtlasBriefing` + migration + `services/atlas_briefing_cache.py`. Done 2026-09-20: migration `d6e7f8a9b0c1_atlas_briefings` on head `c5d6e7f8a9b0`, applied (`alembic current` = `d6e7f8a9b0c1 (head)`); `tests/test_atlas_briefing_cache.py` **13 passed** on Postgres, including the unique constraint asserted by direct insert.
- [x] 35.7 `GET /atlas/briefing` SSE route: history check → welcome, cache replay, fresh run, store. Done 2026-09-20: sync generator on `StreamingResponse` (BE Gap 602 precedent), four paths, `error`+`done` on any exception.
- [x] 35.8 Cache invalidation hooks in dismiss, act, memory add. Done 2026-09-20: one line each, asserted through the real endpoints on the `stale` column.
- [x] 35.9 Interview: `POST /atlas/briefing/answer`, `RuleSource.INTERVIEW`. Done 2026-09-20: question validation confirmed already in the loop (track 2) and deliberately not duplicated. `tests/test_atlas_briefing_router.py` **23 passed**.
- [x] Track-3 checkpoint: full BE suite on Postgres. Done 2026-09-20: `69 failed, 4931 passed, 9 skipped, 5 deselected in 1194.76s`. **Zero new failures** -- the same suite on a clean `git worktree` of master `ca71223` gives `69 failed, 4818 passed, 9 skipped, 5 deselected in 901.08s` and the sorted FAILED lists are byte-identical (+113 passing = tracks 1-3). The cited baseline of 11 is stale; filed as **BE Gap 715**. Two modules (`test_gap674_freight_verification.py`, `test_gap676_diagnostic_retry.py`) fail to collect on both runs and were `--ignore`d -- also in Gap 715.

## Gap work — BE Gap 716 (after track 3, founder: "give the AI the alerts", then "after fix run the same input again")
- [x] BE Gap 716: the first live Terra run on VPI wrote about RAJ-2009 / NAT-2007 without the
  word "duplicate", VPI-OUT-2014 was reachable by no tool, and the Admin never called `forecast`.
  Four parts: `list_lines` rows gain `doubt` + `alerts`; new `invoices` tool (inbound AND
  outbound, alerts + low-confidence keys, `can_audit`/Admin); role-based pre-fetch in
  `run_briefing()` counted against the 12-invocation cap; one prompt sentence.
  Done 2026-09-20: `test_atlas_tools.py` + `test_atlas_agent.py` **52 passed**; all
  `test_atlas_*.py` + `test_no_hardcoding.py` **291 passed**; falsification both halves
  (**1 failed** with the alerts stubbed out, **7 failed** with the pre-fetch stubbed out).
  Same input re-run live on VPI/Admin/Terra: four paragraphs, 0 dropped, $0.024168 — both
  duplicates named in the first two paragraphs, VPI-OUT-2014 cited through `invoices`.
  Spec §12, tracker `[x]`.

## Track 4 — senior-dev (FE) + functional-tester (after track 3)
- [x] 24.1 `lib/atlasBriefing.ts` — types, `parseBriefingFrame()`, `validateCitations()`. Done 2026-09-20: the six event payload types + `BriefingEvent` union, `parseBriefingFrame()`/`parseBriefingEvent()`, and the one deterministic check. `invoice` is exempt from `knownIds` (§7 ruling 2 is unreachable otherwise — spec §8.2).
- [x] 24.2 `app/api/atlas/briefing/route.ts` and `answer/route.ts` proxies. Done 2026-09-20: streamed `GET` (pipes `upstream.body`, not `proxyJson`), `POST` via `proxyJson`; a backend 4xx becomes an `error`+`done` frame pair, never a blank panel. `tests/unit/atlas-briefing-proxy.test.ts` **3 passed**.
- [x] 24.3 `Briefing.tsx` — stream lifecycle, event dispatch, rejected counter, refresh note. Done 2026-09-20: one `EventSource` per mount, closed on `done`; fixture of 3 valid + 1 uncited + 1 unknown-id renders 3 and says **2 paragraphs withheld**; truncated line, error body, `from cache` vs model footer.
- [x] 24.4 `BriefingParagraph.tsx` — citation links and the scroll-to-line highlight. Done 2026-09-20: `recommendation` scrolls + toggles `.atlas-briefing-cited` for 2 s, `invoice` links to `/invoices/review/<id>`, `rule`/`action` open and scroll to the memory panel / action log.
- [x] 24.5 `BriefingQuestion.tsx` — answer flow. Done 2026-09-20: posts `{question_text, answer}`, renders the returned rule text + the refresh note; a second `question` frame is never rendered and is counted in the visible withheld tally.
- [x] 24.6 `WorkScreen.tsx` — mount after payload, pass `knownIds`, wire `onNeedsRefresh` into the dismiss and act handlers. Done 2026-09-20: mounted at the TOP after the outcome line (§7 ruling 1); no stream is opened while the lines are loading, and a dismiss or an act shows the note and opens no second stream. Full invoice-fe unit suite **195 passed | 4 skipped**, `npm run typecheck` clean.
- [x] 35.10 End-to-end on the VPI tenant, three roles, real Terra: cited-id set comparison, cost recorded. Done 2026-09-20 (functional-tester): docs/test_evidence/atlas_intelligence_2026-09-20/ -- 3 raw SSE captures + DB rows, cache proof and dismiss/stale/regenerate proof both confirmed, grading_admin/auditor/trainer.md filed. Admin 0/2/10 (M/P/Miss), Auditor 0/0/4 + 1 MUST-NOT violation (runway line reachable despite cash_position/forecast meant to be excluded), Trainer 0/1/2 + 2 MUST-NOT violations (audit-approve and invoices-tool content reaching a can_train-only caller). Question never fired in any of 6 runs. Four candidate gaps noted in README, none filed/fixed per scope.
- [x] 24.7 Screenshot verification on the VPI tenant, three roles, against the real BE. Done 2026-09-20 (functional-tester): work_admin.png / work_auditor.png / work_trainer.png (full-page, 1280x720, DISABLE_CLERK_AUTH + ALLOW_MOCK_AUTH via Playwright, same technique as vpi_demo_atlas_2026-09-18), plus work_admin_citation_click.png (citation highlight confirmed) and work_admin_after_dismiss.png (refresh note confirmed). Tenant state (atlas_briefings, atlas_dismissals, users role flags) restored and verified at end.

---

**Final status 2026-09-20:** BE Gap 714 fixed and closed (`[x]`, spec §19). Tracks 0-3 built and verified on real Postgres; all `tests/test_atlas_*.py` + `test_no_hardcoding.py` + `test_model_registry.py` **312 passed**. Track-3 checkpoint run: the full backend suite is `69 failed, 4931 passed` with **zero new failures** against a clean-master worktree (`69 failed, 4818 passed`, identical FAILED list) -- the stale 11-failure baseline and two uncollectable extraction test modules are filed as **BE Gap 715**. Nothing committed; every change is in the Changes panel.

**Track 4 status 2026-09-20 (senior-dev, FE):** 24.1-24.6 built on `feature/atlas-intelligence`, uncommitted. `npm run typecheck` clean; `npx vitest run` in invoice-fe: **195 passed | 4 skipped (199)**, 16 files passed, 1 skipped (`atlas-live-backend.test.tsx`, needs a live BE); the two new files alone **32 passed**. FE Feature 24 spec gained an additive **§8 As built** (three deviations recorded, incl. the `invoice` exemption that makes §7 ruling 2 reachable); tracker row is `[~]` until 24.7. No gap filed: no defect was found in existing code. Remaining: **35.10** (end-to-end on VPI, three roles, real Terra) and **24.7** (screenshots) -- both functional-tester work, neither started.
