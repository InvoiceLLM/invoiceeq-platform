# infra-devops — Gap 325: Ops Summary workbook + tiles→table conversion, live deploy

Founder-approved, fully-hashed-out design (2026-08-26). Part 1: new standalone "Ops Summary" workbook
(1 table, 4 rows). Part 2: convert both existing detail workbooks (`cost_health_workbook.json`,
`ai_control_tower_workbook.json`) from tile-cards to grid tables (3 named exceptions stay charts), add
"Recent Activity" comment fields to Infrastructure panels, rename section headers. Deploy live to
`rg-invoice-llm-dev`, same 4-rung verification standard.

## Read first
- [x] `.claude/CONVENTIONS.md`, `active-work.md` (hard rule 5 — in-flight check)
- [x] Confirmed no conflict: `infra-devops-gap322-workbook-redesign-deploy.md`,
      `senior-dev-gap323-band-recalibration.md`, `senior-dev-workbook-redesign-spec.md` are all COMPLETE,
      direct predecessors this task builds on, not concurrent work
- [x] Confirmed Gap 325 does not collide — tracker's max gap number is 323 (`grep -oE "Gap [0-9]+"`,
      no Gap 324/325 anywhere in the repo)
- [x] Read `services/ops_recommendation.py` in full — category vocab, `Finding`/`CategoryRecommendation`
      shapes, `SCORE_BANDS`
- [x] Read `telemetry.py`'s `track_ops_recommendation` / `track_azure_cost_snapshot` — confirmed exact
      event attribute names (`worst_severity`, `red_count`/`yellow_count`, `findings` JSON string,
      `budget_percent_used`, `day_over_day_change_pct`) and confirmed `metrics` is NOT mirrored onto
      `ops_recommendation` (pass_rate for AI Health must come from `findings`, not a metrics field)
- [x] Read both workbook JSONs and both wrapper bicep files in full, plus `rbac-monitoring-cost-only.bicep`
      as the 3rd file-naming/pattern reference the founder named
- [x] Live `az` access confirmed (`rg-invoice-llm-dev`, workspace `law-invoicellm-dev`,
      customerId `a0f26ce7-43d6-457d-9f7b-47e36af39a02`)

## Design decisions (flagged for founder review in chat report)
- [x] Grid column threshold coloring: used `formatter: 18` (Workbooks' grid-column Thresholds formatter,
      not `formatter: 8` which is the tile Big-Number formatter) — same `thresholdsOptions: "colors"` /
      `thresholdsGrid` payload shape as the tile version, just placed under `gridSettings.formatters`
      instead of `tileSettings.leftContent`. This is the schema-correct choice per Microsoft's Workbooks
      grid-column formatter enum; flagged since the prompt hedged with "formatter: 8" as a candidate too.
- [x] `d5-trend-over-runs` / `e3-trend` / `alerts-trend`: these 3 currently have **no** `visualization` key
      at all (default grid already, not tiles) — technically outside the literal "tiles→grid" conversion
      rule. Since the founder's explicit intent is "stay as a line/area chart, NOT a table" and a
      no-`visualization` type-3 item renders as a grid/table today, converted these 3 to
      `"visualization": "linechart"` explicitly rather than leaving them as the table they already are —
      the founder's stated exception only makes sense read this way.
- [x] Ops Summary Status column: normalized to a single 5-value vocabulary across all 4 rows
      (`healthy`/`warning`/`critical`/`degraded`/`no data`) so one `thresholdsGrid` colors every row
      correctly — `worked`→healthy, `recommend`+red→critical, `recommend`+yellow→warning,
      `no_data`/`insufficient_data`→"no data"; API Health emits `healthy`/`degraded`/`no data` directly
      per the founder's literal 3-state spec for that row.
- [x] Infrastructure/Cost/AI Health "What's flagged": broadened from "only when status==recommend" to
      "whenever status != worked" — a `no_data` row's explanation (e.g. "Monitoring Reader grant... never
      deployed") is genuinely useful and was going to render as a blank cell otherwise, which reads as a
      rendering bug rather than an honest "not measured" state.
- [x] Infrastructure Key metric: shows "not measured" (not "0 app(s) with an issue") when status is
      `no_data`/`insufficient_data` — the raw red_count+yellow_count math technically already reads 0 when
      no data was collected, which would silently read as a false-green "0 issues" instead of "unmeasured".
- [x] AI Health "Recent Activity": picks the single highest-severity `Finding.detail` (red before yellow)
      out of the mirrored `findings` JSON array — matches the founder's "most severe finding" instruction.
- [x] AI Health Key metric (pass rate): extracted from `findings[].field == "pass_rate"` when present
      (guaranteed present whenever pass_rate is out of band, which covers tonight's real data); falls back
      to "n/a — see AI Control Tower Section D" on a run where pass_rate was in-band and therefore never
      became a Finding (the mirrored event carries no raw metrics to fall back to).
- [x] API Health "Recent Activity" spike detection: hourly-binned by feature area with a `Requests >= 5`
      floor to avoid a single-request 100%-error-rate false spike; only renders when the worst bucket is
      >=5% (same bar as the row's own degraded threshold).

## Implementation — Part 1: new Ops Summary workbook
- [x] Live-tested every sub-query piece by piece via `az monitor log-analytics query` before assembling
      (latest ops_recommendation per category, azure_cost_snapshot budget_pct/day-over-day,
      ContainerAppSystemLogs_CL allowed-reason distribution + latest event, AppRequests 24h error rate +
      hourly worst-area spike, ai_improvement findings JSON parse)
- [x] Assembled the combined 4-row `union` query (one query, not 4 separate panels — cleanest KQL shape
      given all 4 rows share the same 7-column output schema)
- [x] Ran the full assembled query live twice (before and after two correctness fixes) — confirmed real
      4-row output, see be_features_tracker.md Gap 325 entry for the actual data
- [x] `infra/monitoring/ops_summary_workbook.json` — new file, 1 table panel + header/footer markdown,
      `gridSettings.formatters` threshold coloring on Status
- [x] `infra/workbook-ops-summary-only.bicep` — new file, new pinned GUID
      `7107048d-2102-4882-ae14-f1e51c8bc21d`, `loadTextContent()` pattern matching the other 2 wrappers

## Implementation — Part 2: cost_health_workbook.json tiles→table conversion
- [x] Convert every `"visualization": "tiles"` panel to a plain grid (remove `visualization`/`tileSettings`)
- [x] Preserve coloring via `gridSettings.formatters` (`formatter: 18`) on panels that had a real
      `thresholdsGrid` (not just the all-blue "Default" no-op ones, which convert with no formatter at all)
- [x] Add "Recent Activity" comment column (ContainerAppSystemLogs_CL-derived, same filtered/translated
      source as Part 1) to the container-status/container-restarts/db-status-* panels
- [x] Add explicit markdown subheaders for Containers / Database / Cache / Message Queue / Alerts under
      Reliability, where not already implicit
- [x] `alerts-trend` — explicitly set `"visualization": "linechart"` (see design decision above)

## Implementation — Part 2: ai_control_tower_workbook.json tiles→table conversion
- [x] Convert every `"visualization": "tiles"` panel to a plain grid, same coloring-preservation rule
- [x] `d5-trend-over-runs` / `e3-trend` — explicitly set `"visualization": "linechart"` (see design decision)
- [x] Section D header text → confirm/rename to read "Nightly Test Quality"
- [x] Section E header text → confirm/rename to read "Extraction Quality"
- [x] Section G header text → confirm/rename to read "Real Usage"

## Verification — Rung A: bicep build
- [x] `az bicep build` on `workbook-ops-summary-only.bicep`, `workbook-cost-health-only.bicep`,
      `workbook-ai-control-tower-only.bicep` — 0 errors
- [x] All 3 JSONs parse as valid JSON (`node -e "JSON.parse(...)"`) and shape-checked against Workbooks
      schema conventions (unique `name`s, `gridSettings`/`tileSettings` pairing, no dangling `visualization`)

## Verification — Rung B: what-if
- [x] `az deployment group what-if` on all 3 templates — Ops Summary shows `Create`, the two existing ones
      show `Modify`, not `Create`

## Verification — Rung C: deploy
- [x] `az deployment group create` on all 3 — record `provisioningState`

## Verification — Rung D: pull-back proof
- [x] `az rest ...canFetchContent=true` on all 3, deep-compared item-by-item against local files
- [x] Live query proof: ran the Ops Summary's 4-row query live, reported actual 4 rows
- [x] Ran >=2 "Recent Activity" queries live (Infrastructure ContainerAppSystemLogs_CL-derived + one more),
      confirmed real translated sentences, not raw event codes
- [x] Spot-checked >=3 converted tile→table panels (1 Cost+Health, 1 AI Control Tower, 1 with real
      threshold coloring) render with `gridSettings` intact post-deploy

## Docs
- [x] `be_features_tracker.md` — new Gap 325 entry, `[x]`, full evidence, gap-number confirmation note
- [x] `feature_20_23_24_ops_workbook.md` — additive section: Ops Summary workbook design, taxonomy,
      tile→table conversion, updated panel-inventory counts for all 3 files

## Final status
**COMPLETE.** All 4 verification rungs passed across all 3 templates; deployed live to `rg-invoice-llm-dev`.

- New: `infra/monitoring/ops_summary_workbook.json` (4 items) + `infra/workbook-ops-summary-only.bicep`
  (pinned GUID `7107048d-2102-4882-ae14-f1e51c8bc21d`).
- `cost_health_workbook.json`: 30 → 34 items (17 tiles→grid conversions, 4 new subheaders, 2 panels
  rewritten with real per-app Recent Activity, 1 panel converted to an explicit line chart).
- `ai_control_tower_workbook.json`: stays 55 items (32 tiles→grid conversions, 2 panels converted to
  explicit line charts, 3 section headers renamed).
- Rung A: `az bicep build` 0 errors on all 3 templates; all 3 JSONs valid, no leftover `tiles`/`tileSettings`,
  no duplicate item names.
- Rung B: `what-if` — Ops Summary `1 to create` (expected), Cost+Health `1 to modify`, AI Control Tower
  `1 to modify`. Exactly as required.
- Rung C: `az deployment group create` — `provisioningState: Succeeded` on all 3.
- Rung D: initial `az rest`-to-file pull-back showed a false diff on em-dash characters, traced to `az`'s own
  Windows-console output re-encoding (not a real data problem — confirmed via `efbfbd`/U+FFFD byte
  inspection). Re-pulled all 3 via direct authenticated `curl` against the Resource Manager REST endpoint
  (bypassing `az`'s encoding layer) — all 3 byte-identical to local source (4/4, 34/34, 55/55 items).
- Live query proof: the Ops Summary's real 4-row output run and re-run live against `law-invoicellm-dev`,
  reported in `be_features_tracker.md`'s Gap 325 entry (Infrastructure's relative-time field advanced
  26m→45m→46m across repeated runs, proving live not cached data). 4 Recent Activity queries run live
  (container-status per-app, container-restarts, db-status-postgres-liveness, db-status-redis) — at least 2
  confirmed real translated sentences, not raw event codes; the redis one correctly returned blank on
  below-threshold real data (never fabricated).
- Spot-check: 3 converted tile→table panels (`cost-trend-budget`, `d1-latest-pass-rate`, `container-status`)
  confirmed structurally intact `gridSettings.formatters` in the post-deploy pulled-back JSON. Visual color
  rendering not eyeballed in the Portal — no portal access in this environment (same constraint as Gap 322).
- Docs: `be_features_tracker.md` new Gap 325 entry (`[x]`, full evidence, gap-number-collision check
  documented); `feature_20_23_24_ops_workbook.md` gained 2 additive updates (a staleness-correction note on
  the Gap 322 section, and a full new "Ops Summary workbook + tile→table conversion" section) — nothing
  rewritten, per hard rule 4.
- Reported in chat, no `reports/infra/` file, per infra-devops's standing exception.
