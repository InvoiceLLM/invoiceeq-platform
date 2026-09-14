# BE Gap 480 — abstain turns graded on accuracy alone (option (c))

- [x] Read the Gap 480 entry, `.claude/CONVENTIONS.md`, `/gap-work`, `/done`, `/verify-postgres`
- [x] Re-read the entry against current code: `decide_pass()` (Gap 479 rule), `run_agent_eval.run_turn/score_turn`, `_answer_contract_gate()`, `turn.answer_gate`, `result["judge_evidence"]`
- [x] Find the deterministic signal — and correct the entry's premise: the failing case refused
      through the null-SQL path (`turn_status=declined`/`stop_reason=sql_declined`), never touching
      `answer_gate`. Signal = union of the two enumerated states, read off `judge_evidence`.
- [x] State the defect class + call sites in the entry (1 decision point, 2 callers, 2 signal sites)
- [x] `agents/query_agent.py` — publish `answer_gate`/`turn_status`/`stop_reason` on `judge_evidence`
- [x] `services/agent_eval.py` — `is_abstain_turn()`, `EvalScores.abstained`, `score_answer(abstained=)`,
      `decide_pass()` drops faithfulness from the vote in both branches
- [x] `scripts/run_agent_eval.py` — record the four fields per turn, pass the flag into `score_answer()`
- [x] `services/online_quality_judge.py` — same signal, so live traffic shares the rule
- [x] `tests/test_judge_gap480.py` — property sweep + 4 mutated refusal fixtures + wiring pins
- [x] Postgres runs: test_agent_eval `97 passed`; test_judge_gap480 `51 passed`; eval set `238 passed`;
      judge_evidence consumers `190 passed`; test_no_hardcoding `4 passed`
- [x] Spec `feature_29_llm_optimisation.md` — §2.3 note, §5 File Coordinates rows, build-note amendment
- [x] Tracker Gap 480 → `[x]` with class, call sites, boundary, verbatim evidence; 29.9 note annotated
- [x] Left uncommitted

Final status: done. Task 29.9's own `[~]` marker and the 28/36 re-scoring of the 2026-09-07 run are
deliberately left for the founder — neither was in scope.
