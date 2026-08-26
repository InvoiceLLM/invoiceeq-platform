# senior-dev — Workbook redesign spec (docs-only)

Task: document the founder-approved 2026-08-26 redesign of both ops workbooks (Cost + Health, AI Control
Tower) into `Prod_Invoice_LLM/apps/invoice-be/docs/feature_20_23_24_ops_workbook.md`, additive per
CONVENTIONS hard rule 4. **Docs only** — no workbook JSON, no bicep, no production code. infra-devops
implements from the section this task writes.

- [x] Read `.claude/CONVENTIONS.md` and `active-work.md` (hard rule 5 — in-flight check)
- [x] Read the existing `feature_20_23_24_ops_workbook.md` in full (558 lines) to find the additive insertion point
- [x] Check `.claude/tasklists/` for overlapping in-flight work — `infra-devops-gap320-workbook-recommendation-panel.md` (2026-08-26) is the immediate predecessor; no conflict, this task writes the spec its successor will implement
- [x] Verify every panel name in the founder's 10-item fix list actually exists in the two workbook JSONs
      (27 items in `cost_health_workbook.json`, 51 in `ai_control_tower_workbook.json` — all 10 confirmed)
- [x] Extract and read the current `query` + `tileSettings` of each of the 10 named panels, so the fix list
      records the *actual* current text rather than a paraphrase
- [x] Verify the Dashboard Insights root cause against `routers/dashboard.py::get_dashboard_insights`
      (Gap 30 / Gap 279 docstring — 13-19.5s synchronous Azure OpenAI call on a cache miss: confirmed)
- [x] Verify the n=3-guard argument's precedent in `services/ops_recommendation.py` (~line 1007 —
      confirmed verbatim: "no sampling error to guard against")
- [x] Verify fix-list item 9's "now resolved" claim — Gaps 318/319/320 **are** committed (`f9aa0c5`);
      the session-start git snapshot showing `ops_recommendation.py` as untracked was stale
- [x] Find the band-pinning coupling that constrains item 11 (recalibration): `d1-latest-pass-rate` is
      pinned to `services/ops_recommendation.py::SCORE_BANDS["pass_rate"]` by
      `tests/test_ops_recommendation.py::test_each_band_is_still_the_live_panels_band`; `d2-accuracy` is
      **not** in that parametrize list, so it would drift silently
- [x] Write the new section "## Workbook redesign — priority-ranked information architecture (2026-08-26)"
      into `feature_20_23_24_ops_workbook.md` (additive, appended after the blockers table / before Tasks)
- [x] Add the tier→panel mapping table, the fix list (10 items, one per panel, with current-state evidence),
      the API-latency findings table, and the explicit out-of-scope list
- [x] Update `be_features_tracker.md` — recorded under Feature 20/23/24's task list; gap number is a
      founder call (321 is already reserved by Gap 307's closure note for the online judge)
- [x] Final status line below

**Final status: COMPLETE.** Docs-only, as scoped. `feature_20_23_24_ops_workbook.md` gained one new
section (additive, nothing rewritten or deleted); `be_features_tracker.md` gained one unnumbered
`[ ]` design-approved entry under the F20/23/24 task list. No workbook JSON, bicep or production code
touched. Two things escalated in the summary rather than decided here: the gap number (founder assigns),
and the `d1` band-recalibration's coupling to a pinned test constant (needs its own gap because it is a
production-code change, per the repo's no-code-without-gap rule).
