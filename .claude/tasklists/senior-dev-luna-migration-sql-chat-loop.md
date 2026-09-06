# Luna migration (dev) + SQL/chat improvement loop — founder brief 2026-09-06

Source: decision.md in `docs/extraction_benchmark/runs/matrix-20260905T092330Z/`, with two founder overrides
(text-to-SQL → Luna not Terra; fast/chat → Luna not Astra). Final: primary = gpt-5.6-luna, fast = gpt-5.6-luna,
judge = gpt-5-mini, escalation = none. Corrected rule: cheapest within 1 point AND p95 <= baseline AND cost <= 2x cheapest qualifier.
Constraints: dev only, no prod params, judge stays gpt-5-mini, no extraction-prompt edits, no model changes in Step 3.

## STEP 1 — model changes (dev only)
- [x] Bicep: `azureOpenAiJudgeDeploymentName` param added (08-apps, sweep-jobs-only, 3 compute modules); builds clean.
- [x] `params.dev.json`: deployment/model = gpt-5.6-luna, version 2026-07-09, fast = luna, judge = gpt-5-mini.
- [x] Local `.env`: primary/fast luna, judge gpt-5-mini.
- [x] Live dev: `ca-invoice-be-dev`, `ca-queue-worker-dev` env set (luna/luna/gpt-5-mini, api 2024-10-21).
- [ ] Live dev jobs (6 `caj-*-dev`): same env vars.
- [ ] Delete `gpt-5.6-terra`, `gpt-5.6-sol`, `gpt-6-astra` in Azure; update `model-deployment.bicep` comment.
- [ ] Luna extraction run 2 and run 3, fresh tenants each (swap `tests/test_tenants_local.json` ids, gitignored).
- [ ] Gap 466: 3-run Luna table, deletions, corrected rule, judge param, live-env change. `.env.example` judge/fast lines.
- [ ] **[WAIT]** show 3-run table + deleted deployments.

## STEP 2 — harness gaps
- [ ] a. `--fresh-tenants` in `run_extraction_harness.py`: create 3 tenant rows per run so Status / Alert Type score again.
- [ ] b. SQL eval fixed denominator: timeouts/exceptions = wrong; report n + failure reasons (run_agent_eval / matrix digest).
- [ ] c. Extraction report: all ground-truth fields per invoice; composite (tax/total/line-F1) stays headline.
- [ ] d. Luna baseline on fixed harness → `docs/extraction_benchmark/runs/luna-baseline-<date>/`.
- [ ] Gap entry for a–c (harness = code). **[WAIT]** new baseline numbers.

## STEP 3 — SQL agent + chat prompt loop (Luna fixed)
- [ ] a. Failure taxonomy: one line per failed SQL query / chat turn (id, category, root-cause guess); counts by category. **[WAIT]** founder picks categories.
- [ ] b. Top-2 SQL + top-2 chat categories.
- [ ] c. Iterations 1–6, one change each, same golden set, keep only if primary metric up and no other metric −2 pts; log under `docs/extraction_benchmark/runs/sql-chat-loop-<date>/`. **[WAIT]** after iteration 3.
- [ ] d. Stop at 6 iterations or SQL ≥ 70% and chat pass ≥ 60%. **[WAIT]** at end.

## Deferred (from the 10-step list)
- Rollout plan dev → soak → prod: written after Step 2d; not applied.
- Workbook "Model comparison" panel: exists from Gap 466; verify after Step 2.

## Founder decisions 2026-09-06 (evening)
- Extraction: finalised on Luna (3 runs, 98.8/98.8/99.3). Closed.
- Chat WITHOUT attachment: judge/model = **gpt-5-mini** (full-record 52.8% pass vs Luna 37.1%). Luna stays primary/fast for extraction + doc-type.
- Chat context: **always send full records** — full Postgres invoice row (all columns incl. items/taxes/sa_alerts/notes/payment_instructions) AND the invoice's vector-DB chunks — instead of the SQL projection.
- Then: fix the 5 attachment agent gaps, re-run attachment+chat probe on Luna / gpt-5-mini / Terra.

## STEP 4 — full-record chat context (new; needs a Gap + spec note in feature_6_rag.md)
- [ ] 4a. Gap entry: symptom (2–13 col projection, 9/36 turns with no rows, 0 vector chunks), evidence = `chat_context_audit.md`, fix = full-record block.
- [ ] 4b. SQL route: after the generated SQL identifies invoice ids, fetch those invoices' FULL rows (all columns, JSON parsed) and their Chroma chunks; put both in the summary prompt. Cap: N invoices (founder to set; experiment used whole tenant = 9).
- [ ] 4c. CHAT/general route: when no SQL ran but the question names an invoice/vendor/amount, resolve candidates and send full records too (removes the 9 "no rows" turns).
- [ ] 4d. Re-run golden chat on gpt-5-mini + Luna; compare with as-is and with the experiment.

## STEP 5 — attachment agent gaps (one Gap each, one change per iteration, probe re-run after each)
- [x] 5.1 Reconcile summary lists each reference (number, amount, outcome, matched invoice) instead of counts — `query_agent.py` ~L5280.
- [x] 5.2 Reconcile intent keywords: pay/pays/paid/settle/remit/covers; REMITTANCE_ADVICE + STATEMENT_OF_ACCOUNT default to reconcile — ~L4323.
- [x] 5.3 **Widened by founder call to a signed money ledger over ALL money doc types** (invoice/proforma/debit +1, credit/receipt/remittance -1; PO/quotation/order-confirmation/contract = the agreed figure; delivery note/GRN/statement contribute nothing). `compute_amount_owed()` in `document_comparison.py` + `_amount_owed_block()` on BOTH attachment branches. Gap 472. Unit-verified 114 passed; probe re-run owed.
- [x] 5.4 **Reshaped by founder call**: NOT raw text into the money prompt (that reverses the 'hostile text cannot reach the figures' invariant and still cannot produce $123.75). Instead the rate is parsed and the expected figure computed in Python; the document's words cross over only as a quoted, injection-fenced span beside a computed number. Gap 473. Routing keywords added too — B4 fell to the clarify card first.
- [ ] 5.5 Two attachments + invoice question: compare each doc to its own matched invoice and merge; doc-to-doc only on explicit "compare these two" — dispatch ~L5727.
- [ ] 5.6 Re-run 16-turn probe (cache flushed, fresh sessions) on Luna, gpt-5-mini, Terra; report.

## Status
Nothing committed. Steps 1-3 measurement done 2026-09-06; Step 4 not started.
Step 5 progress: 5.1 + 5.2 = Gap 470 (verified); the pre-existing failure found on resume = Gap 471 (fixed);
5.3 = Gap 472, a signed money ledger over ALL money doc types, not credit-note arithmetic (founder call);
5.4 = Gap 473, deterministic contract-rate extraction + computed expected figure, with the document's own
words entering the money prompt ONLY as a fenced quote beside a Python-computed number (founder call).
A pattern worth noting across 470/472/473: every one of these turns ALSO failed to route - the question fell
to the "read or compare?" clarify card before any logic could run. Each gap fixed its own keyword shortfall.
Evidence: `test_compare_documents.py` 51 passed (19 added across 472+473), `test_chat_attachments.py` 42 passed
(8 added), combined with sweep / direction-aware / reconciliation / chat_document_search -> **139 passed in 43.85s**
(real Postgres).
Next: 5.5 (probe turn B5 - two attachments plus an invoice question compared to each other instead of each to its
own invoice; this is also why A4 lands on the doc-to-doc branch), then 5.6 - the 16-turn probe re-run on
Luna / gpt-5-mini / Terra, which Gaps 470, 472 and 473 all need before they tick. Full-suite checkpoint owed at
the end of the track.

## Closed 2026-09-06 22:14
Superseded by `senior-dev-be29-llm-optimisation.md` (Feature 29). Items 5.5/5.6 done there as 29.7/29.8; Steps 1, 2 and 4 carried as 29.1, 29.4, 29.5.
