# infra-devops — Gap 297: Monitoring Reader + Cost Management Reader RBAC (live deploy)

Task: grant Monitoring Reader and Cost Management Reader (already declared in
`modules/security/rbac-assignments.bicep`, never deployed) to `id-invoicellm-dev`
via a new narrow standalone bicep template — same precedent as
`workbook-cost-health-only.bicep` / `benchmark-eval-job-only.bicep`. Do NOT
redeploy Stage 7 (storage-account-name drift: `stinvoicellmdev` vs real
`stinvoicellmdev2`).

## Steps

- [x] Read CONVENTIONS.md + active-work.md — confirmed "Monitoring Reader RBAC —
      declared, never deployed" is an open (not frozen) blocker; no conflicting
      in-flight work.
- [x] Read `modules/security/rbac-assignments.bicep` — reused role definition IDs:
      Cost Management Reader `72fafb9e-0641-4937-9268-a91bfd8191a3`,
      Monitoring Reader `43d0d8ad-25c7-4714-9337-8ba259a9fe05`. Both RG-scoped
      (no `scope:` override — default deployment RG), matching the source module.
- [x] Read `workbook-cost-health-only.bicep` and `benchmark-eval-job-only.bicep`
      for the narrow-standalone-template pattern (reference existing resources
      by their real live names, header comment explaining why not a full-stage
      redeploy).
- [x] Read `07-rbac.bicep` to confirm identity naming convention
      (`id-${namingPrefix}-${environment}` → `id-invoicellm-dev` live).
- [x] Create `Prod_Invoice_LLM/infra/rbac-monitoring-cost-only.bicep` — references
      `id-invoicellm-dev` by its real live name (not derived from namingPrefix),
      two role assignments, RG-scoped, role GUIDs copied verbatim from
      `rbac-assignments.bicep`.
- [x] Rung A: `az bicep build --file rbac-monitoring-cost-only.bicep` — 0 errors
      (first attempt hit BCP120 using `identity.properties.principalId` in the
      `name:` guid — fixed by using `identity.id` there instead, keeping
      `principalId` only in the `properties` block).
- [x] Rung B: `az deployment group what-if -g rg-invoice-llm-dev -f rbac-monitoring-cost-only.bicep`
      — **2 to create, 54 to ignore**. The 2 creates are exactly the two role
      assignments; nothing else touched.
- [x] Rung C: `az deployment group create` — `provisioningState: "Succeeded"`.
- [x] Rung D: `az role assignment list --assignee b9e91856-7386-42f7-b928-f33d8a2d7215 --all -o table`
      — **7 total**: original 5 + `Monitoring Reader` + `Cost Management Reader`,
      both at `/subscriptions/.../resourceGroups/rg-invoice-llm-dev` scope.
      Baseline (5, no cost/monitoring role) captured before deploy for comparison.
- [x] Closure test — actually run as the managed identity, not just scope-checked.
      `az containerapp exec` into the live `ca-invoice-be-dev` replica
      (revision `--0000084`) and called the real deployed code under its own
      `IDENTITY_ENDPOINT`:
      - Cost Management Reader: `services.azure_cost.get_spend_by_dimension(scope=...)`
        returned real spend rows (no `CostAuthError`).
      - Monitoring Reader: same session, `services.azure_cost.arm_request()` against
        `Microsoft.ResourceGraph/resources` (the exact call `ops_recommendation.py`'s
        `collect_container_health()` makes) returned all 6 live container apps, and
        a `Microsoft.Insights/metrics` read for `ca-invoice-be-dev` returned
        `CpuPercentage`/`MemoryPercentage` series — no 403 on either.
      - `ops_recommendation.py` itself is not yet in the deployed image
        (`ModuleNotFoundError` confirmed) — noted as a separate follow-up, not
        part of this grant's closure.
- [x] Update `be_features_tracker.md` — Gap 297 entry flipped to `[x]` with a
      2026-08-26 closure paragraph (all 4 rungs + closure test), original body
      text untouched per hard rule 4.
- [x] Update `feature_20_23_24_ops_workbook.md` — blockers table's Monitoring
      Reader row struck through with a correction paragraph, the "four rows
      remain open" note corrected to three, and the matching Tasks-section
      checkbox flipped to `[x]` with a correction note. Gap 318's
      `container_health` re-evaluation explicitly left open (needs a deployed
      image + nightly run, not this task).
- [x] Report full verification evidence in chat (no reports/infra/ file).

## Final status
Done, 2026-08-26. `infra/rbac-monitoring-cost-only.bicep` deployed to
`rg-invoice-llm-dev` — 2 new role assignments (Monitoring Reader, Cost
Management Reader) created, 0 modified, `id-invoicellm-dev` now holds 7 total.
All 4 verification rungs passed with real Azure evidence, and the closure test
was run live as the managed identity (not just a scope check) via
`az containerapp exec` into `ca-invoice-be-dev`, exercising both grants
end-to-end with no auth errors. Docs updated additively in
`be_features_tracker.md` (Gap 297) and `feature_20_23_24_ops_workbook.md`
(blockers table + Tasks list). Out of scope, correctly left untouched: Stage 7,
Stage 8, `07-rbac.bicep`, `08-apps.bicep`, `params.dev.json`, Gap 298,
`ops_recommendation.py` deployment.
