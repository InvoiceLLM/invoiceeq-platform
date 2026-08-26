# infra-devops — Gap 322: 3-tier workbook redesign, live deploy

Founder-approved. Implements `feature_20_23_24_ops_workbook.md`'s "Workbook redesign — priority-ranked
information architecture (2026-08-26)" section (authoritative spec) into real JSON/bicep and deploys to
`rg-invoice-llm-dev`.

## Read first
- [x] `.claude/CONVENTIONS.md`, `active-work.md` (hard rule 5 — in-flight check)
- [x] `feature_20_23_24_ops_workbook.md`'s redesign section in full
- [x] Checked `.claude/tasklists/` for overlap: `senior-dev-gap323-band-recalibration.md` (code half of Fix
      11, DONE) and `senior-dev-workbook-redesign-spec.md` (docs-only spec, DONE) are direct predecessors,
      no conflict — this task is their implementation
- [x] Read both workbook JSONs in full (`cost_health_workbook.json` 27 items, `ai_control_tower_workbook.json`
      51 items), both wrapper bicep files, `alert-ai-eval-critical-only.bicep`, `ops_recommendation.py`
      `SCORE_BANDS`/category constants, `test_ops_recommendation.py`'s pin tests and xfail markers

## Design decisions (flagged for founder review in chat report)
- [x] Cost category recommendation card placed in Tier 1 only (not duplicated into Tier 3) — top task text
      says "container_health/cost → Tier 1" without the doc's "if founder wants it in both" hedge
- [x] AI Tower workbook has no Tier 1 section (no reliability/cost data lives there) — container_health/cost
      recommendation cards NOT duplicated onto AI Tower; only `ai_improvement` renders there (Tier 2)
- [x] "Spend by component (chat/extraction/judging)" — NOT built as a new panel; only Dashboard Insights
      latency was named in the founder's "Also add, new" list. Existing `a1`/`a2` cover Tier 3 on AI Tower;
      markdown notes the real split is a known future enhancement, not this pass
- [x] Panels not named in the tier field list (Section A's a3-a5, B, C, F on AI Tower) kept as an appended
      "Supplementary operational detail" area below the 3 tiers — not deleted, not force-fit into a tier
- [x] `n=3` golden-bank guard removed only on `d1-latest-pass-rate` (the only panel the top task names for
      this) — `d2-accuracy`/d3/d4 guards untouched, only d1's and d2-accuracy's colour bands move

## Implementation — cost_health_workbook.json
- [x] Fix 1: `cost-trend-budget` — top-1→toscalar/equality pattern, stale-snapshot age surfaced in Detail
- [x] Fix 2: `db-status-redis-liveness` — "N/A — not configured in this tier" (blue) when metric absent
- [x] Fix 3: `db-status-postgres-liveness` — real-time window (15 min) + 6h blip count in Detail
- [x] Fix 4: `alerts-trend` — real `bin(fired, 1d)` daily binning, grid not tiles
- [x] New: `dashboard-insights-latency` panel (Tier 1 Speed) — cache-hit/miss bimodal split, observability only
- [x] Restructure into Tier 1 (Cost awareness / Reliability / Speed) + Tier 3 (Cost Reduction); inline
      `cost` and `container_health` recommendation cards; bottom-of-page grid removed

## Implementation — ai_control_tower_workbook.json
- [x] Fix 5: `a5-genai-dependency-duration` — add `run_source == "production"` filter (copy `b6` pattern)
- [x] Fix 6: delete `a6-sage-per-tool-cost` outright; update `section-a-header` to drop the stale SAGE note
- [x] Fix 7: `b6-stop-reasons` — retitle, replace hardcoded Detail with a real derived share-of-turns string
- [x] Fix 8: `e2-confusion-cells` — top-1→toscalar/equality pattern
- [x] Fix 10: `f1-breached-signals` — read `value`, render null value as "not measured" (blue), not green
- [x] Fix 11: `d1-latest-pass-rate` red<0.60/yellow<0.75 + n=3 guard removed; `d2-accuracy` red<0.75/yellow<0.90
- [x] Restructure into Tier 2 (nightly + real-usage chat quality, extraction quality) + Tier 3 (cost) +
      Supplementary detail (A3-A5, B, C, F); inline `ai_improvement` recommendation card only; bottom grid removed

## Implementation — alert-ai-eval-critical-only.bicep
- [x] `passRateRedBelow` default `'0.20'` → `'0.60'`
- [x] `accuracyRedBelow` default `'0.40'` → `'0.75'`
- [x] `description` string's `pass_rate<0.20`/`accuracy<0.40` → `0.60`/`0.75`
- [x] Header comment block's threshold-source table numbers updated to match

## Verification — Rung A: bicep build
- [x] `az bicep build` on `workbook-cost-health-only.bicep`, `workbook-ai-control-tower-only.bicep`,
      `alert-ai-eval-critical-only.bicep` — 0 errors
- [x] Both JSONs parse as valid JSON and validated shape-wise against workbook schema expectations

## Verification — Rung B: what-if
- [x] `az deployment group what-if` on all 3 templates — confirm `Modify`, not `Create`, on existing pinned resources

## Verification — Rung C: deploy
- [x] `az deployment group create` on all 3 — record `provisioningState`

## Verification — Rung D: pull-back proof
- [x] `az rest` deep-compare both workbooks item-by-item (serializedData) against local files
- [x] `az monitor scheduled-query show` confirming alert's new threshold values live
- [x] Run live queries for d1/d2 bands + the two toscalar conversions against real Log Analytics —
      confirm tonight's real numbers (25.7% pass rate, 60% accuracy) now render red

## Verification — backend test
- [x] `pytest tests/test_ops_recommendation.py` — confirm the two `xfail(strict=True)` tests now XPASS
      (reported as failures under strict) — proves the JSON mirror is byte-exact to the Python constants
- [x] Follow-up cleanup: remove the two `_AWAITING_JSON_MIRROR` markers + the transitional
      `test_the_two_recalibrated_bands_still_await_their_json_mirror` test now that the mirror landed,
      re-run to confirm full green

## Docs
- [x] `be_features_tracker.md` — Gap 322 `[x]` with full evidence
- [x] `feature_20_23_24_ops_workbook.md` — mark fix list items 1-11 implemented, update panel-inventory counts

## Final status
**COMPLETE — all 4 rungs, all 3 templates, deployed live to `rg-invoice-llm-dev`.**

- `cost_health_workbook.json`: 27 → 30 items. `ai_control_tower_workbook.json`: 51 → 55 items.
- Rung A (bicep build): 0 errors on all 3 templates; both JSONs structurally valid (schema shape, unique
  names, `tileSettings`/`visualization` pairing).
- Rung B (what-if): all 3 `~ Modify` on the pinned existing resources, none `Create`.
- Rung C (deploy): all 3 `provisioningState: Succeeded`.
- Rung D (pull-back): both workbooks byte-identical to local files (30/30, 55/55 items, `dict ==` true);
  alert's live query/description confirmed reading `0.60`/`0.75`.
- Live query proof: ran d1, d2-accuracy, e2-confusion-cells, cost-trend-budget (the 4 explicitly required)
  plus db-status-redis-liveness, db-status-postgres-liveness, alerts-trend, a5, b6, f1,
  dashboard-insights-latency, and all 3 inline recommendation cards — every query executed cleanly against
  real `law-invoicellm-dev` data. d2-accuracy's live value (0.625) demonstrably flips green→red under the
  new band, the clearest proof the recalibration changes real coloring.
- Backend test: `pytest tests/test_ops_recommendation.py` confirmed XPASS on the two transitional params,
  then cleaned up (`_AWAITING_JSON_MIRROR` markers + transitional test removed) → 84 passed, 0 xfailed.
  `ruff check` clean.
- Docs: `be_features_tracker.md` Gap 322 (new, `[x]`) and Gap 323 (correction note appended) updated;
  `feature_20_23_24_ops_workbook.md`'s redesign section given an "Implemented" note per fix item (1-11) and
  Tasks-list checkboxes flipped to `[x]` — all additive per hard rule 4.
- Reported in chat, no `reports/infra/` file, per infra-devops's standing exception.
