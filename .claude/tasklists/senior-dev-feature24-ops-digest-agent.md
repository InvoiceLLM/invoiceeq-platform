# Feature 24 — Ops Digest Agent: collection, LLM synthesis, schedule, delivery (senior-dev)

Scope: everything around the already-built `services/ops_digest_routing.py::classify()`.

## Recon (done before writing any code)
- [x] Read `.claude/CONVENTIONS.md`, `feature_24_ops_digest_agent.md` (full), `services/ops_digest_routing.py`,
      `services/azure_cost.py`, `utils/llm.py`, `services/agent_eval.py`, `services/online_eval_signals.py`,
      `telemetry.py`, `scripts/sweep_azure_cost.py`, `scheduled-job.bicep`, `08-apps.bicep`,
      `action-group.bicep`, `alert-rules.bicep`
- [x] Recovered the live-validated ARG `alertsmanagementresources` query from the deleted
      `ai_control_tower.workbook.json` (git `b3233d9`) rather than inventing one
- [x] Verified alert-rules.bicep's severity→action-group mapping rule by rule (Sev 0/1 → critical,
      Sev 2/3 → info; no exceptions) so the collector can derive `action_group` faithfully
- [x] **Live checks against `rg-invoice-llm-dev`** (not assumed):
      - ARG alerts query runs and returns real rows; `rule` comes back as a **full resource ID**,
        `sev` as `"Sev2"` (string), `resolved` as `""` when still firing — all three differ from what
        the workbook query implied, so the parser is written against the real shape
      - action groups live are `ag-invoice-llm-dev` / `ag-invoicellm-dev` — the `-critical`/`-info`
        split in `action-group.bicep` is **not deployed**; both live groups carry a
        `teams-alert-channel` webhook (a Power Automate HTTP trigger) + email to `application@…`
      - `ca-invoice-be-dev` has **no** `sendgrid-key-secret` → SendGrid is not wired live
      - `az containerapp job list` returns **nothing** — `caj-overdue-sweep-dev` was never deployed

## Build
- [x] `services/ops_digest_collect.py` — `DigestItem`, `collect_alert_items()` (ARG),
      `collect_cost_items()` (reuses `collect_cost_snapshot()`), `collect_ai_eval_items()`
      (Postgres `agent_eval_run` + `compute_online_signals()`), `collect_all()`
- [x] `services/azure_cost.py` — one added public `arm_request()` so the ARG call reuses the existing
      managed-identity/CLI token chain + 429 retry instead of growing a second auth path
- [x] `services/ops_digest.py` — `split_by_tier()` over `classify()`, `DigestSynthesis` schema,
      `synthesize_digest()` (one structured LLM call), `compress_self_resolved()` (deterministic),
      `render_digest()`, `build_digest()`, `run_ops_digest()`
- [x] `services/ops_digest_delivery.py` — `resolve_critical_channel()` reads the *deployed* action
      group over ARM and delivers to exactly those receivers (Teams webhook + email)
- [x] `telemetry.py` — `track_ops_digest_run()` / `OPS_DIGEST_EVENT_NAME`
- [x] `config.py` — 7 `OPS_DIGEST_*` settings
- [x] `scripts/ops_digest_job.py` — entrypoint (`--dry-run`, `--json`, `--window-hours`, `--no-llm`,
      `--send-empty`, `--print-channel`)

## Infra
- [x] `modules/compute/scheduled-job.bicep` — generic `extraEnv` / `extraSecrets` params (defaults
      `[]`; `concat(x, [])` is the identity, so the overdue-sweep job's *evaluated* template is
      unchanged — the compiled ARM expression differs, the value does not)
- [x] `08-apps.bicep` — `opsDigestJob` module, cron `0 1,7,13,19 * * *` (every 6h UTC)
- [x] `modules/security/rbac-assignments.bicep` — `Monitoring Reader`
      (`43d0d8ad-25c7-4714-9337-8ba259a9fe05`, confirmed live with `az role definition list`) at RG
      scope, for the ARG alert read + the action-group read
- [x] `infra/ops-digest-job-only.bicep` — narrow standalone template, added after the Stage 8
      what-if came back **3 create / 4 modify**. Follows the tracker's 2026-08-22 precedent
      (`agent-eval-job-only.bicep`).
- [x] `az bicep build` clean on 07-rbac, 08-apps, ops-digest-job-only
- [x] `az deployment group what-if` run three times against `rg-invoice-llm-dev`:
      - `08-apps.bicep` → **3 to create, 4 to modify** — NOT safe (see report: `params.dev.json`
        names a registry that does not exist and the wrong `namingPrefix`)
      - `07-rbac.bicep` → role assignments are "unsupported" for what-if analysis; the new
        Monitoring Reader assignment is visible in the compiled template
      - `ops-digest-job-only.bicep` → **1 to create, 50 to ignore** — clean and create-only
- [x] **Not deployed.** Asked instead — the image does not contain the new code yet.

## Tests
- [x] `tests/test_ops_digest.py` — 56 tests. Collection/classification/rendering real, LLM +
      ARM/webhook/email mocked
- [x] Full backend suite: **1304 passed / 3 failed / 7 skipped**; the same 3 pre-existing failures
      (2 need a local Redis, 1 calls `routers/chat.post_chat_message` with a stale signature — that
      file is untouched by this work)
- [x] Two live read-only runs against real Azure (`--dry-run`), one of them making a real
      gpt-5-mini synthesis call

## Docs
- [x] `feature_24_ops_digest_agent.md` body updated (what was actually built + deviations)
- [x] `be_features_tracker.md` status + Gap entries

Status: complete, pending a deploy decision. Full-outage exception left dormant, as documented.
