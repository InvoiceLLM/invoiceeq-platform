# Eval & Observability — Pending Gaps Tracker
## Feature 23 (AI Control Tower) — Remaining Work

**Last updated:** 2026-08-25
**Status:** Feature 23 infrastructure is shipped. These gaps are what remains open.

> Each gap has its own implementation file under `docs/eval_gaps/`.

---

## Summary Table

| Gap | Title | Priority | Dev | Prod | Effort | Owner |
|-----|-------|----------|-----|------|--------|-------|
| [GAP-A](./eval_gaps/gap_a_production_quality_judge.md) | Enable Production Quality Judge | P1-CRITICAL | Test only | Enable flag | 4 hrs | Backend |
| [GAP-B](./eval_gaps/gap_b_stop_reason_persistence.md) | Persist stop_reason on ChatMessage | P1-CRITICAL | Schema + code | Deploy migration | 4 hrs | Backend |
| [GAP-C](./eval_gaps/gap_c_extraction_false_positive.md) | Fix Extraction False Positive (25% FP rate) | P1-CRITICAL | Fix + re-run | Validate in prod | 3 hrs | Backend |
| [GAP-D](./eval_gaps/gap_d_online_signals_scheduling.md) | Verify Online Signals Job is Running | P2-HIGH | Local test | ACA Job schedule | 2 hrs | DevOps |
| [GAP-E](./eval_gaps/gap_e_langsmith_wiring.md) | Wire LangSmith Tracing | P2-HIGH | Real key needed | Separate project | 30 min | Any |
| [GAP-F](./eval_gaps/gap_f_golden_bank_expansion.md) | Expand Agent Eval Golden Bank | P2-HIGH | Add cases locally | Run nightly | 6 hrs | Backend/QA |
| [GAP-G](./eval_gaps/gap_g_skipped_benchmark_cases.md) | Fix 8 SKIPPED Benchmark Cases | P3-MEDIUM | Investigate | Include in nightly | 2 hrs | Backend |
| [GAP-H](./eval_gaps/gap_h_kql_run_source_filter.md) | Audit KQL for run_source filter | P3-MEDIUM | N/A | Review workbooks | 1 hr | DevOps |
| [GAP-I](./eval_gaps/gap_i_model_comparison_schedule.md) | Schedule Model Comparison Runs | P4-LOW | Ad-hoc only | ACA Job nightly | 4 hrs | DevOps |

---

## Current Benchmark Baseline (23 Aug 2026)

| Metric | Result | Target | Status |
|--------|--------|--------|--------|
| Alert Recall | 100.0% | > 90% | PASS |
| False Positive Rate | 25.0% | < 10% | FAIL - GAP-C |
| Document Precision | 83.3% | > 95% | FAIL - GAP-C |
| Field Accuracy (clean) | 100.0% | > 99% | PASS |
| Production Quality Judge | OFF | ON | OPEN - GAP-A |
| stop_reason persisted | No | Yes | OPEN - GAP-B |
| Online Signals Scheduled | Unknown | Every 6h | CHECK - GAP-D |

---

## Reading Order for New Team Members

1. Read `telemetry.py` -- the event vocabulary everything emits
2. Read `services/agent_eval.py` module docstring -- the LLM judge and its 4 failure modes found in production
3. Read `docs/extraction_benchmark/runs/live-latest.md` -- current numbers
4. Then read the gap files in priority order above
