# Feature 23 loose end #1 — 3-way model comparison (real run)

Goal: an actual side-by-side comparison of gpt-5-mini (baseline) vs GPT-4o vs Ollama llama3.2:latest
over the golden bank, with real pass rate / scores / cost / latency, written into
`docs/feature_23_ai_control_tower.md`.

- [x] 1. Read conventions, feature 23 doc's candidate-model sections, `scripts/run_agent_eval.py`
- [x] 2. Inspect `benchmarks/agent_eval_golden_sample.py` — 35 cases confirmed (20 base + 5 India + 5 US + 5 EU)
- [x] 3. Check `_candidate_model()` for tenant assumptions — **none**. It patches only the `get_llm`
      binding in the 3 chat modules; tenant scoping is entirely per-case (`run_turn` passes
      `case.tenant_id`, `main` passes `stats_for_tenant`/`chunks_for_tenant`). Proven live: the US-tenant
      case `us_zero_tax_exemption_reason` ran correctly under all three providers in the sanity round.
      **No bug to fix, so no regression test added.**
- [x] 4. Env confirmed: Azure key present, `gpt-5-mini` + `gpt-4o` deployments live, `ca-ollama-eval-dev`
      reachable (dev IP 122.167.116.167 is in its allow list). Local Postgres (`localhost:5433`) is
      **down** → persist target is a scratch SQLite `agent_eval_run` (see step 6).
- [x] 5. Sanity round, 3 cases (`greeting_no_tool`, `titan_steel_payment_status`,
      `us_zero_tax_exemption_reason`), no persist:
      - baseline gpt-5-mini: 2m50s, 0 errors, pass 0.667
      - gpt-4o: 1m16s, 0 errors, pass 0.333 — **refuses to emit SQL**, `generated_sql` empty on both SQL cases
      - ollama llama3.2: 6m57s, 0 errors, pass 0.333 — **prompt truncated**, `tokens_in` pinned at exactly
        2050 on both `sql_generation` calls vs ~5400 on Azure
- [x] 6. Run-size decision: **identical 12-case representative subset for all three models**, not 35.
      Reasons: (a) the doc's own comparability rule is "run each candidate through the *identical* set",
      so a 35-case baseline vs a 12-case Ollama would not be a comparison; (b) Ollama on the deployed
      2 vCPU CPU-only replica runs ~2m20s/case and hits ACA's 240s ingress timeout on the fuller cases,
      so 35 would be ~3h of mostly-504s; (c) `large_invoice_full_detail` is deliberately excluded — the
      harness docstring already states its faithfulness is not comparable (judge truncates context at
      12k chars vs its ~100k-char record), so it would add real cost on 3 models for zero comparative
      signal. Subset covers SQL/RAG/CHAT routes, all 4 tenants, and all 6 scored axes.
      Persist: scratch SQLite, **not** the dev Postgres — see finding in step 11.
- [ ] 7. Baseline gpt-5-mini, 12 cases, `--persist-url` scratch sqlite
- [ ] 8. GPT-4o, same 12, `--provider azure --model gpt-4o --api-version 2024-08-01-preview --persist-candidate`
- [ ] 9. Ollama llama3.2:latest, same 12, `--provider ollama --persist-candidate`
- [ ] 10. Comparison table built from the three output JSONs + the SQLite rows
- [ ] 11. Provider-specific findings recorded
- [ ] 12. No bug in the candidate mechanism itself → no new regression test. Re-run existing suite.
- [ ] 13. Comparison section written into `feature_23_ai_control_tower.md`
- [ ] 14. Tracker updated
- [ ] 15. Left uncommitted

Status: sanity round done, findings already material. Starting the three graded runs.

**Closed 2026-09-01, not completed — superseded by a founder decision, not abandoned silently.**
Items 7-15 will not run. Found during the 2026-09-01 security pass (F6): `ca-ollama-eval-dev`
had zero traffic since deploy day, and this task's own step 5 sanity round already recorded
the disqualifier — llama3.2's prompt truncates at exactly 2050 tokens vs ~5400 on Azure, and
per-case latency (~2m20s) sits close to ACA's 240s job timeout on the deployed 2 vCPU sizing.
That is a structural ceiling on this hardware, not something a fuller 35-case run would have
resolved. Founder decision: remove the Ollama infra rather than keep it idle waiting for steps
7-15. `ca-ollama-eval-dev`, its CAE storage link, and `infra/ollama-eval-only.bicep` removed;
see `be_features_tracker.md`'s Feature 23 Phase 4 entry for the full record. Worth noting for
whoever picks up a GPT-4o comparison later: step 5's sanity round also showed GPT-4o scoring
0.333 on the same subset (refused to emit SQL on both SQL cases) — that candidate is untouched
and still deployed, but its own result here was not clean either; steps 7/8/10/11/13/14 would
still be real, useful work if GPT-4o alone (baseline vs GPT-4o, dropping the Ollama arm) is
ever picked back up.
