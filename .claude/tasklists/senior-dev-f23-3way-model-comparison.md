# Feature 23 loose end #1 — 3-way model comparison (real run)

Goal: an actual side-by-side comparison of gpt-5-mini (baseline) vs GPT-4o vs Ollama llama3.2:latest
over the golden bank, with real pass rate / scores / cost / latency, written into
`docs/feature_23_ai_control_tower.md`.

- [ ] 1. Read conventions, feature 23 doc's candidate-model sections, `scripts/run_agent_eval.py`
- [ ] 2. Inspect `benchmarks/agent_eval_golden_sample.py` — confirm 35 cases, tenant spread (base + India/US/EU)
- [ ] 3. Check `_candidate_model()` for tenant assumptions (Wave 3 regional tenants)
- [ ] 4. Confirm env: Azure OpenAI key, `gpt-4o` deployment reachable, `ca-ollama-eval-dev` reachable from this IP
- [ ] 5. Sanity run: small case subset per provider (baseline / gpt-4o / ollama), no persist
- [ ] 6. Decide + state final run size (full 35 vs representative subset) with cost reasoning
- [ ] 7. Run baseline gpt-5-mini with `--persist-candidate` equivalent (baseline persists by default)
- [ ] 8. Run GPT-4o with `--provider azure --model gpt-4o --api-version 2024-08-01-preview --persist-candidate`
- [ ] 9. Run Ollama with `--provider ollama --model llama3.2:latest --persist-candidate`
- [ ] 10. Build comparison table from the three output JSONs (pass rate, 6 scores, cost/turn, latency/turn)
- [ ] 11. Note provider-specific harness issues found (context window, tool-calling, truncation)
- [ ] 12. If a bug had to be fixed: add regression test + run existing suite
- [ ] 13. Write comparison section + real cost + recommendation into `feature_23_ai_control_tower.md`
- [ ] 14. Update `be_features_tracker.md` status/Gap entry
- [ ] 15. Leave uncommitted

Status: starting.
