# Feature 24: Ops Digest Agent

**Status: built 2026-08-23, code complete, not deployed.** Collection, tier split, LLM synthesis,
rendering, delivery and the scheduled-job template all exist and have been exercised against real
Azure data. What has *not* happened is a deploy: the job resource does not exist in
`rg-invoice-llm-dev`, and the reasons are recorded in "As built" below rather than treated as a
formality.

**Built 2026-08-23 (first pass)**: `services/ops_digest_routing.py::classify()` — the two-tier decision function
only, not the agent itself. Takes one signal (an Azure Monitor alert, trusting its existing
critical/info action-group assignment from `alert-rules.bicep`, or an AI-eval finding, matched against
the named exceptions below) and returns `"critical"` or `"digest"`. 11 tests,
`tests/test_ops_digest_routing.py`, all passing — including one that caught a real bug during
development: the full-outage check originally fired on *any* replica shortfall (e.g. 4 of 5 running),
not a true zero-replica outage, which would have paged on ordinary rolling restarts. Fixed before
merge. **Honest limitation, stated in the module docstring**: the full-outage exception has no real
data source yet — nothing in this codebase currently computes "replicas down" as a signal, so that
specific exception is scaffolding until Wave 2's dashboard work provides it. **Still true after the
second pass** — see "The full-outage exception is still dormant" below. Nothing was invented to
make it look finished.

**Built 2026-08-23 (second pass)**: everything else — see "As built" below.

## Why this exists

Feature 19/20 (Azure cost + health/performance) and Feature 23 (AI eval/observability) each produce
real signal — alerts, metrics, eval scores — but reading it all directly floods the team. This feature
is the triage/synthesis layer that sits across both: it reads what they produce, decides what actually
needs a human's attention right now versus what can wait for a periodic summary, and writes a **brief
analysis** for anything it surfaces so a decision can be made quickly without digging through raw data.

**Internal-only.** This is never customer-facing — same access boundary as the Azure Workbooks/portal
today.

## Two tiers, not one

| Tier | Delivery | What lands here |
|---|---|---|
| **Critical** | Immediate, real-time | Existing Sev 1 alerts (crash-loop, data-loss risk) **plus** named exceptions below, regardless of their tagged severity |
| **Digest** | Batched, a few times a day | Everything else — Sev 2/3 alerts, cost trends, health metrics, AI-eval results |

**Named "always critical" exceptions** (agreed 2026-08-23):
1. Data-loss-risk alerts — already the case today, carried forward
2. **Full outage** — all replicas of an app down, not one replica restarting (which is normal/
   self-healing and belongs in the digest, not here)
3. **The audit/benchmark job itself failing to run** (Feature 23's Track 1/2 scheduler) — a silent
   scheduler failure is worse than any single bad metric, since nobody would know to look
4. A **sharp/sudden** AI quality-score drop (a cliff, not gradual drift) — drift belongs in the digest

**Deliberately no "never critical" exceptions yet.** The existing alert-tuning pass (commit `dd5c58c`)
already downgraded the genuinely noisy cases (transient throttle bursts, etc.) to Sev 2/3. Adding a
"never page" list before real noise has been observed would be premature — revisit if something
specific proves annoying in practice, not before.

## What the digest actually contains

Not a raw alert dump. For each area:

- **Fired-and-resolved-on-its-own items**: compressed into one short line each (what, roughly when,
  that it self-resolved) — not full detail, since nothing needs a decision.
- **Items that need a decision**: a brief analysis per item — what happened, likely cause, suggested
  action — so the reader can decide without re-deriving the diagnosis themselves.

**Area 1 (cost)**: what changed and why (a spend spike, a forecast overshoot), not just the number.

**Area 2 (health/perf)**: what happened and likely cause (a specific container's restart pattern, a
scaling event and its trigger), not just "CPU was high."

**Area 3 (AI eval)**: which soft metric moved and — using Feature 23's cost-vs-quality distinction and
its soft-metric-to-component map (faithfulness → context, relevance → trace/routing, persona-fit →
persona wording, etc.) — a suggestion of *where* to look, not just that quality dropped.

## Cadence

**Every 6 hours: `0 1,7,13,19 * * *` UTC** = 01:00 / 07:00 / 13:00 / 19:00 UTC, i.e. 06:30 / 12:30 /
18:30 / 00:30 IST. Four runs a day is the "a few times a day" agreed on 2026-08-23, now made
specific.

Two things pinned this to those exact hours rather than a round `*/6`:

* **The window and the schedule are the same number by construction.**
  `OPS_DIGEST_WINDOW_HOURS` defaults to 6 and the cron is every 6 hours. A window shorter than the
  schedule silently drops whatever happened in the gap; a longer one repeats items in consecutive
  digests. Both files say so at the point of definition (`config.py`, `08-apps.bicep`).
* **The odd hours avoid a collision.** `caj-overdue-sweep-dev` is on `0 2 * * *`, so 01:00 keeps the
  digest off the same minute as another job on the same Container Apps environment.

The 00:30 IST run is deliberately not a problem: this is the digest tier, so it is an email and a
Teams message, not a page. That is the whole point of the two-tier split.

## As built (2026-08-23)

### Files

| File | What it is |
|---|---|
| `services/ops_digest_routing.py` | `classify()` — the two-tier decision (first pass, unchanged) |
| `services/ops_digest_collect.py` | `DigestItem`, `collect_alert_items()`, `collect_cost_items()`, `collect_ai_eval_items()`, `collect_all()` |
| `services/ops_digest.py` | `split_by_tier()`, `partition_digest_items()`, `compress_self_resolved()`, `build_synthesis_prompt()`, `synthesize_digest()`, `render_digest()`, `build_digest()`, `run_ops_digest()` |
| `services/ops_digest_delivery.py` | `resolve_critical_channel()`, `build_common_alert_schema_payload()`, `deliver_digest()` |
| `scripts/ops_digest_job.py` | The scheduled entrypoint (`--dry-run`, `--no-llm`, `--json`, `--window-hours`, `--send-empty`, `--print-channel`) |
| `services/azure_cost.py` | One added function, `arm_request()` — a public name for the existing managed-identity/CLI token chain + 429 retry, so the ARG and action-group calls do not grow a second auth path |
| `telemetry.py` | `OPS_DIGEST_EVENT_NAME` + `track_ops_digest_run()` |
| `config.py` | 7 `OPS_DIGEST_*` settings (deployment-varying only; data thresholds are module constants in `ops_digest_collect.py`) |
| `infra/modules/compute/scheduled-job.bicep` | Two generic params, `extraEnv` / `extraSecrets` |
| `infra/08-apps.bicep` | `opsDigestJob` module + `opsDigestCron` / `opsDigestDelivery` params |
| `infra/ops-digest-job-only.bicep` | Narrow standalone template — the only *safe* way to create this job today (see "Why it is not deployed") |
| `infra/modules/security/rbac-assignments.bicep` | `Monitoring Reader` at RG scope |
| `tests/test_ops_digest.py` | 56 tests |

### Collection — what the real data actually looks like

**Alerts** come from Azure Resource Graph over `alertsmanagementresources`, reusing the projection
from the Feature 23 workbook (which had been executed live before being filed). Four properties of
the *real* response were confirmed against subscription `2ae37d8b-…` before the parser was written,
and three of them contradict what the column names imply:

1. `properties.essentials.alertRule` is the **full resource ID**, not a friendly name —
   `rule_display_name()` takes the last segment.
2. `severity` is the string `"Sev2"`, not the integer `2`.
3. `monitorConditionResolvedDateTime` is `""` (empty string, not null) while an alert still fires.
4. `alertState` (`New`/`Acknowledged`/`Closed`) is **not** whether the alert is over — that is
   `monitorCondition` (`Fired`/`Resolved`). Real live rows are `monitorCondition: Resolved` +
   `alertState: New` simultaneously, because nobody ever clicked "close" in the portal. Reading
   `alertState` would have reported every self-resolved alert as still open, and is pinned by
   `test_self_resolved_reads_monitor_condition_not_alert_state`.

ARG does not return which action group an alert notified, so `action_group_for_alert()` reconstructs
it from severity: Sev 0/1 → critical, Sev 2/3 → info. That is not a guess — all 16 rules in
`alert-rules.bicep` were read one by one and the mapping holds without exception, with the CAE
resource-health activity-log alert (which carries no `severity` field at all) special-cased by name.
`classify()`'s contract is to *trust* the alert's own assignment; this reconstructs it from the only
field available.

**Cost** reuses `services/azure_cost.py::collect_cost_snapshot()` unchanged.

**AI-eval findings** are read from **Postgres `agent_eval_run`**, not from the Application Insights
`agent_eval_run` / `online_eval_signal` custom events. Worth stating because the telemetry mirror is
the more obvious answer: those events exist *because an Azure Workbook cannot query Postgres*
(`telemetry.py` says so at the constant's definition). This agent runs inside this codebase with a
live session, so reading the mirror would add a Log Analytics dependency, a KQL round-trip and an
ingestion delay to get strictly less data. Online-eval signals come from
`compute_online_signals()`, also pure SQL.

Three finding kinds: `audit_job_failed`, per-metric `quality_score_drop` (≥ 0.20 absolute, a cliff)
/ `quality_score_drift` (≥ 0.05, gradual), and `pass_rate_drop`, plus one item per breached online
signal. Each score column has its **own** denominator, because every one of them is
nullable-means-not-scored — a shared denominator would report `persona_score` (NULL on most turns by
design) as a quality collapse.

### The digest itself

`build_digest()` implements the three rules that make this a digest and not a dump:

1. **Critical items are excluded, not re-sent.** They were already paged in real time by the action
   group; repeating them six hours later would page the same incident twice. They are counted in one
   line so the reader knows the digest is not pretending they did not happen.

   **The honest exception**: an AI-eval finding classified critical (a sharp quality drop,
   `audit_job_failed`) has **no immediate pager wired to it at all** — Feature 23 emits no Azure
   Monitor alert. For those, "already handled" is currently false, so they are listed *by name* with
   an explicit "and nothing else has notified anyone about it". Wiring a real immediate path for them
   needs a scheduled-query alert rule over the telemetry mirror, and is recorded as a gap rather than
   quietly assumed to exist.

2. **Fired-and-self-resolved items compress to one line each, deterministically, with no LLM
   involved.** `compress_self_resolved()` renders `title — fired 23 Aug 04:12 UTC, self-resolved
   after 47m`. Doing this in Python rather than asking the model to "keep it brief" is the only way
   to *guarantee* one line, and it means the common case on this environment (memory alerts that
   resolve themselves overnight) costs zero tokens.

3. **Everything needing a decision gets a written analysis** — what happened, likely cause, suggested
   action — from **one** structured LLM call over the whole set, via the app's existing
   `get_llm()` / `with_structured_output()` path. One call, not one per item: cheaper, and a per-item
   call structurally cannot see that a cost spike and a scaling event in the same window are the same
   story.

The prompt is written as a rubric. Three parts are load-bearing: an **anti-restatement rule with a
worked example** of the failure (the likeliest way this feature degrades into an expensive alert
forwarder), a **"say you don't know" clause** (a confident wrong diagnosis is worse than "ambiguous,
check X", because it gets acted on), and Feature 23's **soft-metric → component map** pasted in for
Area 3's "say where to look".

The LLM step is **fail-open**: an unreachable model still produces a delivered digest carrying the
raw items and their deterministic `component_hint`, plus a line saying the analysis failed. An item
the model skips is reported as skipped, never silently uncommented.

### Delivery — the open question, closed

**Decision: same channel as critical alerts** (founder, 2026-08-23). The interesting part is *how*.

Azure action groups cannot be fired programmatically — there is no "notify with arbitrary content"
API. The only way to reach the same humans is to send to the same *receivers*. So rather than copy
the Teams webhook URL into a second place where it can drift, `resolve_critical_channel()` **reads
the deployed action group over ARM and delivers to exactly the receivers it finds**. Change where
critical alerts go, and the digest follows automatically.

What is actually deployed, checked live rather than read off the bicep:

* The live groups are `ag-invoice-llm-dev` and `ag-invoicellm-dev`. The `-critical` / `-info`
  **split declared in `action-group.bicep` does not exist** — Stage 9 has not been redeployed since
  it was authored. The candidate-name list tries the bicep name first and falls back to the live one;
  verified live, `-critical` 404s and the fallback resolves.
* That group has one email receiver (`application@infinevocloud.com`) and one webhook receiver
  (`teams-alert-channel`) whose `serviceUri` is a **Power Automate** flow trigger with
  `useCommonAlertSchema: true`.

Because the receiver is registered with `useCommonAlertSchema: true`, the flow on the other end is
parsing `data.essentials.*`. `build_common_alert_schema_payload()` therefore posts that shape, with
the digest in `description`, `severity: Sev4` and `monitorCondition: Resolved` — deliberately, so a
digest does not render as a red "Fired" card in the same channel as real pages.

**Not verified end to end**: that payload has never actually been posted. Confirming it means
sending a real message into the founder's live Teams channel, which is not something to do unasked
while building. The shape is right; whether that specific flow renders `description` nicely is
unknown until someone sends one. `--print-channel` and `OPS_DIGEST_DELIVERY=none` exist so the
destination can be confirmed without posting.

**SendGrid is not wired on any live container.** `ca-invoice-be-dev` lists 11 secrets and
`sendgrid-key-secret` is not among them, though `invoice-be.bicep` declares it. Email delivery works
from this code but will raise "SENDGRID_API_KEY is not configured" until a deploy seeds it.
`deliver_digest()` records that per receiver instead of failing the run.

### Verified against real Azure, twice

Both read-only, both `--dry-run`:

* `--print-channel` resolved the live action group through the ARM fallback chain and printed the
  real Teams webhook + email.
* A 72-hour window collected **16 real alerts**: 3 critical (excluded, counted), 12 compressed to one
  line each, 1 needing a decision — and the cost source collected cleanly with no errors. A **real
  gpt-5-mini synthesis call** produced an analysis that obeyed the "say you don't know" rule verbatim
  ("The evidence is ambiguous: this pattern fits either a memory leak … or repeated workload spikes …
  To tell them apart, check …").

That run also produced a **real improvement found by observation, not by design**: the first version
analysed a still-firing `memory-high` alert without knowing the same rule had self-resolved 12 times
in the same 72 hours — the single most useful fact about it, and the difference between "investigate
a possible leak" and "this threshold is wrong". The compressed one-liners are now passed into the
prompt as *context* (explicitly not as work). On re-run the model said "The service has shown
multiple similar memory-high alerts across the past 72 hours, so the behaviour is recurring rather
than isolated." Pinned by `test_self_resolved_one_liners_are_supplied_as_cross_item_context`.

### The full-outage exception is still dormant

Nothing here computes "0 of N replicas running", and nothing was invented to change that. No
collector emits `replica_count` / `expected_min_replicas`, so the exception `classify()` documents as
scaffolding remains exactly that. The nearest real signal that exists today is the CAE resource-health
alert, which is a different thing — the whole environment being unavailable, not one app's replicas —
and it already routes critical on its own.

### Budget items are off by default

`OPS_DIGEST_BUDGET_ITEMS` defaults to False because of **Gap 295**: `budget-invoicellm-dev` is
denominated in INR with an amount set as if it were USD, so it has been permanently breached (~10,935%
of budget) for its entire existence. Emitting a budget item would put one guaranteed, meaningless line
in every digest from day one — the exact noise this feature exists to remove. Flip it once the budget
amount/currency is corrected; that is a founder decision, not a default to guess at.

### Why it is not deployed

`az deployment group what-if` was run three times against `rg-invoice-llm-dev`:

| Template | Result |
|---|---|
| `08-apps.bicep` | **3 to create, 4 to modify** — not safe |
| `07-rbac.bicep` | Role assignments are "unsupported" for what-if analysis (nested template + computed GUID); the new Monitoring Reader assignment is present in the compiled template |
| `ops-digest-job-only.bicep` | **1 to create, 50 to ignore** — clean, create-only |

The Stage 8 result is the reason `ops-digest-job-only.bicep` exists. The 4 modifications are every
running container app, for reasons that have nothing to do with this feature:

* `params.dev.json`'s `backendImage` is `acrinvoicellmdev.azurecr.io/invoice-be:latest`. **That
  registry does not exist** — `az acr list` returns exactly one, `acrinvoicellmdev2`. A Stage 8
  deploy would repoint all four apps at an unreachable image.
* `params.dev.json` sets `namingPrefix: "invoice-llm"`, but this environment was built with
  `invoicellm` (live: `kv-invoicellm-dev`, `id-invoicellm-dev`, `cae-invoicellm-dev`). With the
  file's own prefix, what-if rewrites every Key Vault secret URI and the identity to names that do
  not exist.
* It would roll back Gap 290's CPU/memory scale rules, applied live via `az containerapp update`.

Even with the clean standalone template, **two prerequisites are not met**, so it was not deployed:

1. **The backend image does not contain `scripts/ops_digest_job.py`.** This code is uncommitted, so
   no CI build has pushed it. Deploying now creates a job whose every execution fails with `No such
   file or directory`.
2. **`Monitoring Reader` is not granted** to `id-invoicellm-dev`. Declared in
   `rbac-assignments.bicep`, never deployed (Stage 7 has the same drift problem — its storage
   assignment targets `stinvoicellmdev`, and the live account is `stinvoicellmdev2`). Without it the
   job runs but collects zero alerts and cannot read the action group.
   `scripts/ops_digest_job.py --print-channel` inside the container is the one-command check.

A related finding while checking: `az containerapp job list` returns **nothing**.
`caj-overdue-sweep-dev` and `caj-billing-lifecycle-dev` were never deployed either — consistent with
the tracker's existing "activate the two other scheduled jobs already coded but never deployed" gap.

## Open / not yet decided

- ~~**Delivery channel**~~ — **closed 2026-08-23: same channel**, resolved at runtime off the
  deployed action group. See "Delivery" above.
- ~~**Underlying mechanism**~~ — **closed**: a Container Apps job over `scheduled-job.bicep`, every
  6 hours. See "Cadence" and "As built".
- **Action scope**: per the earlier discussion, this agent **proposes, it does not act** — no auto-fix
  by default. A small, explicit allowlist of genuinely safe auto-actions (if any) is a separate,
  deliberate decision, not a default. Nothing here should silently change cost, scaling, model config,
  data, or deployed code — the earlier real production outage this session (Gap 280's missing
  migration) is exactly the kind of thing an overly-autonomous agent could make worse, not better.
  **Honoured as built**: there is no code path in any of the four modules that changes anything, the
  synthesis schema's field is named `suggested_action` and is only ever rendered as text, the prompt
  forbids proposing automatic changes, and the delivered digest ends with "This agent proposes; it
  does not act."
- **Where "how we see these items" (Feature 19/20's and Feature 23's own dashboards) lands** — Azure
  Workbooks vs. a custom in-app page — is still an open decision from the same discussion, tracked in
  Feature 19/20's doc, not duplicated here.
- **An immediate path for AI-eval criticals.** New, opened by this build: a sharp quality drop and
  `audit_job_failed` are classified critical but nothing pages on them, so the digest names them
  instead. Closing this needs a Log Analytics scheduled-query alert rule over the
  `agent_eval_run` / `ops_digest_run` custom events, wired to the critical action group.
- **Verifying the Teams webhook payload** — needs one real post into the live channel.

## Tasks

- `[x]` Two-tier `classify()` + 11 tests (first pass)
- `[x]` Collection: Azure Monitor alerts via Resource Graph
- `[x]` Collection: cost, via the existing `collect_cost_snapshot()`
- `[x]` Collection: AI-eval findings from `agent_eval_run` + online-eval signals
- `[x]` Critical/digest split with criticals excluded from the digest body
- `[x]` Self-resolved compression to one deterministic line each
- `[x]` LLM synthesis: one structured call, three fields per item, fail-open
- `[x]` Delivery to the same channel as critical alerts, resolved off the action group
- `[x]` `ops_digest_run` telemetry (the only durable evidence the job ran)
- `[x]` Scheduled job: `08-apps.bicep` + the standalone `ops-digest-job-only.bicep`
- `[x]` `Monitoring Reader` declared in `rbac-assignments.bicep`
- `[x]` 56 tests; full suite re-run with no new failures
- `[ ]` **Deploy** — blocked on an image build containing the code, and on the Stage 7 RBAC grant
- `[ ]` Verify the Teams webhook payload renders in the real channel
- `[ ]` Full-outage exception — still has no data source (deliberately)
