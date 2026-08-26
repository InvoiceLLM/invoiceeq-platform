# senior-dev — Gap 305: the 2 dead online signals (post-Gap-316 root cause)

Scope (founder-directed): before anyone builds the `Microsoft.App/jobs` resource for
`scripts/emit_online_signals_job.py`, root-cause the 2 of 5 signals that Gap 316 (SAGE deletion)
left degenerate. Fix if genuinely fixable without touching frozen SAGE Phase 3 work; otherwise
recommend retire-or-hold and let the founder rule.

## Boundary check (do this first)

- [x] 1. Read `.claude/CONVENTIONS.md` + `active-work.md`.
- [x] 2. Frozen-path check: `active-work.md` freezes "SAGE Phase 3 — gated on Gap 310's real-world
      result; 4 product decisions deliberately unresolved (see `feature_21_sage.md`)".
      **No collision.** SAGE and `feature_21_sage.md` were both *deleted* by Gap 316 on the same
      day (2026-08-25) that `active-work.md` was last updated — there is no SAGE code, no
      `ENABLE_AGENTIC_SAGE` flag and no `feature_21_sage.md` left to touch. All work below is
      confined to `services/online_eval_signals.py` + its test file. Flagged as a doc discrepancy
      in the report; **not** resolved here (agents never edit `active-work.md`).
- [x] 3. In-flight check: no tasklist touches `online_eval_signals.py`. Nearest neighbours
      (`senior-dev-gap305-online-signal-caller.md`, `senior-dev-feature21-sage-orchestrator-deletion.md`)
      both closed. No parallel work.

## Investigation

- [x] 4. Read Gap 316's tracker entry in full (`be_features_tracker.md:1268-1282`). It already
      names the casualty itself: *"`services/online_eval_signals.py`'s `clarification_rate`/
      `budget_exhaustion_rate` signals, which parse `stop_reason`/clarification state only SAGE
      ever produced and are now permanently degenerate ... `services/online_eval_signals.py`
      itself was not touched (telemetry was out of scope for this change)."*
- [x] 5. Read `scripts/emit_online_signals_job.py` + `services/online_eval_signals.py` in full.
- [x] 6. Traced the exact broken read for each signal (see findings below).
- [x] 7. Checked every candidate surviving source before concluding: `ChatMessage` (no
      `stop_reason` column — `models.py:186-211`), `AgentEvalRun.notes` (writer stopped emitting
      `stop_reason=`, `run_agent_eval.py:713-716`), `chat_turn` telemetry event (has
      `stop_reason`, but it is Log Analytics, not Postgres).
- [x] 8. Checked the downstream consumer: workbook `f1-breached-signals` keys off `breached`
      alone, so a permanently-unmeasurable signal renders **green "ok"**; `b6-stop-reasons`
      already queries live `chat_turn.stop_reason` and is mislabelled "SAGE-only ... structurally
      empty".

## Findings — split verdict, not "2 dead signals"

- [x] 9. **`budget_exhaustion_rate` — dead forever, not fixable.** Numerator *and* denominator
      come only from `stop_reason=` fragments in `AgentEvalRun.notes`. Gap 316 removed the
      `stop_reason=` note fragment from `scripts/run_agent_eval.py`, so no new row can ever carry
      one, and the *concept* is gone too: `MAX_TOOL_CALLS` / `tool_call_budget_exhausted` appear
      in **zero** live code files (only docs, old JSON fixtures, and this module + its tests).
      Denominator is permanently 0 → `value=None`, `breached=False`. Nothing to recompute from.
- [x] 10. **`clarification_rate` — only half dead; Gap 316's "permanently degenerate" is an
      overstatement for this one.** Its headline `value`/`numerator`/`denominator` come from
      `_chat_messages()` + `looks_like_clarification()` over `chat_message` assistant rows —
      **zero SAGE dependency, still measuring real traffic.** Only the 3 `detail` fields
      (`offline_exact_clarification_turns`, `offline_turns_with_a_stop_reason`,
      `offline_exact_rate`) are dead. Its *caveat text* is now false and that is the real harm.
- [x] 11. Verdict: **case 3 for signal 1 (not fixable — founder must rule on retire), case
      "fixable, and it is the caveat that was broken" for signal 2.** No design decision taken.

## Change made (narrow, no behaviour change, no design call)

- [x] 12. `services/online_eval_signals.py` — corrected every statement that names deleted code
      (`agents/sage_orchestrator.py`, `_clarify_node`, `ask_clarifying_question`,
      `ENABLE_AGENTIC_SAGE`) and every claim that is now false. Most consequential: the
      `clarification_rate` caveat told a reader "a near-zero live rate is expected today and is a
      configuration fact, not a quality result" — which would make a founder dismiss a **real**
      rising clarification rate as a flag artifact. Deliberately did **not** delete either signal,
      change any computed value, add an event field, or touch the workbook JSON — all four are
      the founder's call or infra's.
- [x] 13. `tests/test_online_eval_signals.py` — new "Gap 305 / Gap 316" section, 4 tests, all
      driving the real functions against a real DB session, pinning the post-deletion contract.
- [x] 14. `pytest tests/test_online_eval_signals.py tests/test_emit_online_signals_job.py
      -p no:randomly` → **51 passed** (47 baseline + 4 new). One pre-existing test
      (`test_budget_exhaustion_declares_itself_offline_only_and_names_the_gap`) asserted on the
      old caveat's `"GAP:"` to-do marker and was updated to the stronger claim the caveat now
      makes — same intent, which is that this signal may never present itself as a production
      measurement. Mutation-checked: reintroducing `stop_reason=` into the reproduced
      `run_agent_eval.py` note string fails **exactly** the 2 budget/offline tests, nothing else.
      **SQLite run, no Postgres run** (hard rule 2, stated not glossed) — no SQL, filter or
      computation changed in this pass, so there is no dialect-sensitive behaviour to re-verify.
- [x] 15. `ruff check` clean on both touched files.

## Docs

- [x] 16. `be_features_tracker.md` — Gap 305 entry extended with the split verdict, the evidence,
      and the founder decision that is now blocking the `Microsoft.App/jobs` build. Additive only.
- [x] 17. `feature_20_23_24_ops_workbook.md` — Section F row correction, the `b6` "structurally
      empty" correction, and the `f1-breached-signals` green-tile finding. Additive only.
- [x] 18. Incident worth recording: a `git stash` used to measure the pre-change test baseline
      timed out mid-command and left the two edited files stashed. Recovered with `git stash pop`
      (verified: `git diff --stat` shows both files modified, 4 new tests present). Baseline was
      instead derived arithmetically from the run that included the new tests (51 total − 4 new
      = 47). No `git stash` used again in this pass.

Final status: **complete — no frozen-path collision.** `budget_exhaustion_rate` is dead forever
and needs a founder ruling (recommend: drop to 4 signals, ship, and read budget/abnormal-stop
behaviour off the already-live `chat_turn.stop_reason` instead). `clarification_rate` is **not**
dead — its live half works and its caveat has been corrected. Two mislabelled deployed workbook
panels found and reported, not changed (infra scope). Changes left uncommitted.
