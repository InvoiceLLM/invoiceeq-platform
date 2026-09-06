# Feature 29: LLM Optimisation — build
Spec: Prod_Invoice_LLM/apps/invoice-be/docs/feature_29_llm_optimisation.md
Started: 2026-09-06 20:26
Hard stop: 2026-09-06 22:26 (founder: "Hardstop after 2 hr or if the whole solution development and testing is completed before that")
Definition of done: every task below checked; every Verification Plan item run and cited;
spec body and tracker updated; changes uncommitted.
Status: stopped at hard stop (22:26, 2026-09-06)

Approval (founder, 2026-09-06, this conversation): "Approved to implement the whole feature solution to Azure env".
All nine §11 decisions ruled the same day; see the spec.

Supersedes `senior-dev-luna-migration-sql-chat-loop.md` (Step 5 items 5.5/5.6 = 29.7/29.8; Step 1 leftovers = 29.1;
Step 2 = 29.4; Step 4 = 29.5). That tasklist is closed into this one.

Execution order inside the 2-hour window (spec §10): 29.7 → 29.8 → 29.1 → 29.2 → 29.3 → 29.4 → 29.5 → 29.6 → 29.9 → 29.12
→ 29.10 → 29.11 → 29.13 → 29.14 → 29.15 → 29.16 → 29.17 → 29.18 → 29.19 → 29.20. Whatever is unticked at 22:26 stays
unticked with a note; nothing is ticked in a batch. Full-suite checkpoints after 29.8, 29.12, 29.10, 29.17.

Preflight notes (2026-09-06 20:26): nothing frozen is touched. `active-work.md` open contradiction "chat answer-contract
plumbing" (`routers/chat.py::MessageResponse` drops attachment keys) affects 29.9's provenance — file a Gap, do not
silently widen the response model.

## Track A — close the migration
- [ ] 29.1 Registry: 5.6-family context → 1.05M/922k; `recall_note` on Luna; `long_doc` role + `get_long_doc_llm()` (falls back to fast). **Delete `gpt-5.6-sol` and `gpt-6-astra` now; keep `gpt-5.6-terra` until 29.10 decides the long_doc role** (decision 9). Update `model-deployment.bicep` comment. Set luna/luna/gpt-5-mini env on the six `caj-*-dev` jobs.
  - NOT STARTED at the hard stop. No file touched, no `az` command run. Next action: `utils/model_registry.py` context 1.05M/922k + `recall_note`, `get_long_doc_llm()`, delete the `gpt-5.6-sol` and `gpt-6-astra` deployments, then `az containerapp job update` on the six `caj-*-dev` jobs.
- [ ] 29.2 Judge calibration: `tests/golden_calibration.json` with **30 hand-graded turns now, 100 with two raters before 29.13's flag flips** (decision 4); `run_agent_eval.py --calibration-set` reports Cohen's κ; **κ < 0.6 blocks every later accuracy claim in this feature.**
  - NOT STARTED at the hard stop. Nothing written. **Note the standing gate: kappa < 0.6 blocks every later accuracy claim in this feature — the 29.8 probe numbers above are NOT judge-scored (deterministic regex grading), so they are unaffected by it.**
- [ ] 29.3 Failure taxonomy: `run_agent_eval.py --taxonomy` tags every failed golden turn with one of {no_route, no_evidence, wrong_evidence, no_computation, narration, judge}; baseline counts recorded.
  - NOT STARTED at the hard stop. Nothing written.
- [ ] 29.4 Harness fixes from tasklist Step 2: `--fresh-tenants`; SQL eval fixed denominator (timeouts = wrong, n reported); extraction report lists all ground-truth fields with the composite as headline. Luna baseline re-run on the fixed harness → `runs/luna-baseline-<date>/`.
  - NOT STARTED at the hard stop. Nothing written. The Luna baseline re-run it calls for has not been done.

## Track B — evidence and contract (chat without attachment)
- [ ] 29.5 `fetch_full_records()` + `full_record_block()`; wired into the SQL route after ids are known and into the general route when the resolver binds an invoice; **cap = 25** (decision 1); **summary call on gpt-5-mini for this route, Luna stays on the attachment branches** (decision 2). Golden re-run; target: `no_evidence` bucket → 0.
  - NOT STARTED at the hard stop. `services/full_records.py` does not exist. This is the highest-value remaining task (22.2% -> 52.8% measured).
- [ ] 29.6 `check_line_arithmetic()` in `document_comparison.py`; wired into `_computed_figures_block_for()`; the three line-check golden cases pass with the figure computed.
  - NOT STARTED at the hard stop. Nothing written.
- [ ] 29.9 `_answer_contract_gate()` + `_abstain_payload()` on every route; provenance on every claim. Abstain wording per decision 3: name what is missing, state what *is* on file, offer the nearest next step.
  - NOT STARTED at the hard stop. **Blocked in part by Gap 474** (filed today): provenance that never leaves the process is not provenance, and `MessageResponse` drops the attachment keys. Gap 474 carries a proposed fix and needs a founder go before the response model is widened.
- [ ] 29.12 Answer cache keyed on `(tenant, plan-or-normalised-question, attachment ids)`; the content branch's documented cache bypass becomes unnecessary and is removed.
  - NOT STARTED at the hard stop. Nothing written.

## Track C — attachments
- [x] 29.7 Two attachments + invoice question: per-document comparison against each one's own invoice, merged; doc-to-doc only on explicit request. Probe turn B5 passes; A4 leaves the pair branch.
- [x] 29.8 `scripts/attach_chat_eval.py` versioned; 16-turn probe re-run on Luna / gpt-5-mini / Terra with cache flushed and fresh sessions; results recorded under Gaps 470, 472, 473 and this feature. **Gaps 470/472/473 tick here.**
- [ ] 29.10 `tests/golden_long_doc.json` (5 cases: multi-page contract, 3-page statement, 2 long POs, long delivery note); Terra vs Luna on the attachment branches; role decided by the 2-pt rule; env + bicep for `AZURE_OPENAI_LONG_DOC_DEPLOYMENT_NAME`.
  - NOT STARTED at the hard stop. **Now also carries the Terra leg of 29.8's probe**, which stalled and was killed at the hard stop; Terra is the `long_doc` candidate, so re-running it here is the right place rather than repeating 29.8.

## Track D — grounding and the generic layer
- [ ] 29.11 `resolve_entities()`; automatic clarify on 0/>1; keyword lists demoted to fallback behind `ENABLE_CHAT_PLANNER=false` (still on) — measured by clarify-card rate on the probe → 0 for resolvable questions.
  - NOT STARTED at the hard stop. Nothing written.
- [ ] 29.13 `plan_turn()` + `CAPABILITIES` registry, flag-gated, **attachment branches first** (decision 8), gated by the 16-turn probe; then all routes once the golden set shows no regression and the 100-turn calibration (decision 4) is in; keyword lists deleted one release after the flag defaults on.
  - NOT STARTED at the hard stop. Nothing written. Gated on 29.2's 100-turn calibration in any case.
- [ ] 29.14 Semantic layer: 4 views + `METRICS` + `query_metric()` with a parameterised `WHERE tenant_id = :t` enforced by the AST guard, no RLS (decision 6); schema link prefers a metric; `alembic upgrade head` once. Target on the golden SQL set: +15 pts exec-correct vs 29.4's baseline.
  - NOT STARTED at the hard stop. No migration written, no Alembic revision created.
- [ ] 29.15 Certified examples: table + Chroma index + `retrieve_examples()` (certified only) replacing the C4 static examples tail; seeded from every golden case whose SQL is verified; `certify_example()`. **Global rows only at first; `tenant_id` nullable for the flywheel** (decision 5).
  - NOT STARTED at the hard stop. No migration written.
- [ ] 29.16 Knowledge layer: `knowledge_{tenant}` collection, `KnowledgeDoc`, `index_knowledge()`, `lookup_glossary()`, `lookup_rule()`; glossary seeded (total / grand total / net / tax / due).
  - NOT STARTED at the hard stop. Nothing written.
- [ ] 29.17 Regional rule cards — **India first** — one paragraph each with `source_url`, `effective_from`, `owner = founder`, `review_at`; the session drafts each card from a primary source it has fetched and cites (CBIC/GSTN), indexes it, and the founder spot-checks a sample (decision 7); then EU (EN 16931, mandates), then US. Playbooks (20–40) alongside. Compliance `verify` capability: deterministic field checks against a rule card's checklist.
  - NOT STARTED at the hard stop. **No rule card was authored, and none should be back-filled from memory** — decision 7 requires a primary source fetched and cited per card. No WebFetch against cbic.gov.in / gst.gov.in was made in this window.
- [ ] 29.18 Reranker (Cohere rerank-v4 on Foundry) between bge-m3 and the LLM — **only after** RAG recall@k is instrumented in 29.5 and shows ranking, not retrieval, as the limit. Chat tier pinned to minimal reasoning effort.
  - NOT STARTED at the hard stop. Correctly blocked anyway: it needs 29.5's recall instrumentation first.
- [ ] 29.19 Flywheel: `chat_correction` table, `record_correction()` on thumbs-down, `promote_to_example()`; control-tower workbook panel "chat quality trend" (pass %, abstain %, bucket counts by week) fed from `agent_eval_summary`.
  - NOT STARTED at the hard stop. Nothing written.

## Track E — rollout
- [ ] 29.20 Rollout plan dev → soak → prod written (not applied); prod params untouched.
  - NOT STARTED at the hard stop. Nothing written.

## Log
- 20:26 tasklist created; senior-dev dispatched in background; status mailer started (every 10 min → sbanerji@admsofttech.com).
- 20:31 29.7 start — read spec §5/§6/§11, CONVENTIONS, Gaps 470-473, `_run_attached_document_turn()` routing (line 4718) and `_run_attachment_pair_branch()` (line 5301). Plan: extract the attachment-vs-invoice computation into a reusable helper, add `_wants_doc_to_doc()` + `_run_attachment_multi_invoice_branch()`, reroute the two-attachment case.
- 20:40 29.7 DONE and ticked. `_wants_doc_to_doc()` + `_compare_attachment_to_invoices()` + `_run_attachment_multi_invoice_branch()` in `agents/query_agent.py`; routing rerouted; clarify-card bypass for two-document turns. Evidence: `pytest tests/test_chat_attachments.py -q` -> `47 passed in 26.63s` (42 -> 47); six attachment files together -> `144 passed in 37.73s` (139 -> 144). Tracker bullet 29.7 written; spec Build note added under section 6 (three deviations: any-confirmed not both; comparison verb required; clarify-card bypass).
- 20:41 29.8 start - formalise the 16-turn probe as `scripts/attach_chat_eval.py`.
- 20:45 29.8 - found the previous session's ad-hoc probe + its 8 PDFs in a scratchpad; wrote `scripts/attach_chat_eval.py` (versioned: argparse, `--flush-cache` via redis, UTC-stamped fresh sessions, deployments-in-force recorded in the JSON).
- 20:53 restarted backend + worker: the running uvicorn was started 18:41, BEFORE 29.7's code, so it would have measured the old branch. Killed by command line, restarted from `.venv`.
- 20:56 Luna probe run 1: **14/16** (was 8/16). BUT reading the answers, A4 PASSED on a WRONG net (475.20; the answer is 432.00) and B5 still ran the doc-to-doc diff. Two real defects, neither visible in the pass count.
- 21:07 filed and fixed **Gap 475** (credit note printing its own total negative was double-negated: sign taken from the doc type AND from the printed sign) and **Gap 476** (29.7's `_DOC_TO_DOC_PATTERN` matched the bare phrase "both documents", which is B5's opening words). 4 tests added; `pytest tests/test_compare_documents.py tests/test_chat_attachments.py -q` -> `102 passed in 17.96s`.
- 21:16 Luna probe run 2, after the fixes: **16/16** (single-doc 9/9, two-doc 3/3, no-attachment 4/4, p95 8.3s). A4 = 432.0 and equals the PO total; B5 = per-document, Redwood tax under-charged 123.75 vs 90.00 with the contract span quoted.
- 21:33 gpt-5-mini: **15/16** (was 10/16). Sole failure B2 is a grading artefact - the model says the quantities match and then mentions an extra freight line, tripping the `forbidden` pattern.
- 21:44 Terra leg started; stalled with an empty log for ~55 min and was killed at 22:05. Not run. Moved to 29.10, which is where the long_doc role is decided anyway.
- 22:06 `.env` restored from backup to luna/luna; backend + worker restarted on it and healthy. The machine is as it was found.
- 22:07 tracker written: Gaps 470/472/473 ticked with the probe evidence; Gaps 474 (filed, NOT fixed - needs founder go), 475 and 476 filed with symptom/root cause/fix/evidence; Feature 29 row carries the 29.7 and 29.8 bullets.
- 22:12 STOPPED AT HARD STOP. 2 of 20 tasks ticked (29.7, 29.8), both actually verified against real Postgres and real dev Azure. 18 unticked, each with a one-line state note above. **Nothing committed** - every change is uncommitted in the working tree. Full-suite checkpoint after 29.8 was NOT run (no time); the six attachment-related files were run instead and are green at `144 passed`, plus `102 passed` on the two files the Gap 475/476 fixes touch.

## Final status (hand-back 2026-09-06 22:14)
Stopped at the founder's 2-hour hard stop. 2/20 ticked and verified (29.7, 29.8); Gaps 470/472/473 closed on the probe re-run; Gaps 475/476 filed and fixed; Gap 474 filed, awaiting founder go. 18 tasks not started, each with a state note above. No Azure change made. Nothing committed; HEAD unchanged. Next session resumes at 29.5 (full records) then 29.1.
