# load-tester — live dev load pass, phase 1 (read-only baseline)

Founder-approved scope, 2026-09-01. Targets `rg-invoice-llm-dev` through the
public website gateway only. Synthetic data + one dedicated throwaway tenant —
never a real tenant. VU cap: start 5, ceiling 25. Each run <= 10 minutes.
Kill switch ready before any run. No writes to app code, no tracker edits,
no commits, no pushes. Phase 2 (ingestion) is OUT of scope — separate tasklist.

- [ ] Confirm k6 absent (already confirmed 2026-09-01: not on PATH), then STOP
      and ask the founder to install it — k6 is not allow-listed, an
      unattended install attempt will stall. Record `k6 version` once done.
- [ ] Pre-flight kill switch: record current min/max replicas for
      `ca-invoice-be-dev`, `ca-queue-worker-dev`, `ca-invoice-website-dev` via
      `az containerapp show`; write the exact `az containerapp update
      --min-replicas` rollback command in this file.
- [ ] Pre-run spend snapshot via Azure Cost Management (NOT the Cost & Health
      workbook — its cost panels are confirmed stale/broken as of today).
      Record Azure OpenAI + Doc Intelligence spend to date.
- [ ] Confirm no nightly eval job is running/scheduled in the run window —
      keeps Azure OpenAI TPM contention out of both sets of numbers.
- [ ] Provision a throwaway tenant + one `inv_live_` API key (Feature 25
      dual-credential auth, Gap 358, confirmed externally reachable) +
      synthetic invoice rows. Record the tenant_id here.
- [ ] Write k6 scripts to the scratchpad (not the repo): read-baseline
      covering dashboard reads, `/api/v1/auth/me`, chat/RAG query.
- [ ] Smoke run: 1 VU, 60s. Abort if any 5xx. Record raw output.
- [ ] Ramp run: 5 VUs, 5 min. Record p50/p95/p99, error rate, RPS per endpoint.
- [ ] Ramp run: 25 VUs, 10 min (only if the 5-VU run passed thresholds).
- [ ] Thresholds (first-run guesses, no historical baseline exists yet): read
      p95 < 1.5s, chat p95 < 8s, error rate < 1%, no 5xx alert fired. Record
      pass/fail against each, not just raw numbers.
- [ ] Post-run: confirm replicas scaled back down; queue depth back to 0
      within 5 min; query Log Analytics workspace
      `a0f26ce7-43d6-457d-9f7b-47e36af39a02` (`law-invoicellm-dev`, confirmed
      current) for 5xx/latency over the run window.
- [ ] Post-run spend snapshot; record the delta vs pre-run.
- [ ] Delete the throwaway tenant's data and revoke the `inv_live_` key.
- [ ] File results to
      `Prod_Invoice_LLM/reports/load/2026-09-01-live-dev-phase1.md`
      (pre-stated thresholds and real numbers together, per
      `reports/load/README.md`'s own convention).
- [ ] Draft any Gap entries in the final report-back only — do NOT edit any
      tracker file.
- [ ] Final status line here (done / stopped early / blocked-on-X).
- [ ] STOP for founder review. Do NOT commit, do NOT push, do NOT start
      phase 2 — this tasklist spends real money and scales live infra, so the
      stop here is a deliberate checkpoint, not just a permission prompt.
