# infra-devops: Gap 298 ACR naming fix

Scope: fix `sharedAcrName` default resolution in `08-apps.bicep` by adding
an explicit override in `params.dev.json` (params-file-only change, no
bicep default expression change). What-if verify only; no
`az deployment group create` against Stage 8. Also confirm (read-only,
no fix) whether other namingPrefix-derived vars in 08-apps.bicep
(identity/CAE/KeyVault/OpenAI/DocIntel/AppInsights) drift from live Azure,
and report findings for founder review.

- [x] Read CONVENTIONS.md, active-work.md — no conflicts with in-flight work (F23 3-way comparison, arch-docs Gap244) found.
- [x] Read `08-apps.bicep` (root cause, lines 61-62 + 152-162 naming vars) and confirm against `benchmark-eval-job-only.bicep` precedent (hardcoded `acrinvoicellmdev2` comment).
- [x] Read `params.dev.json` — confirmed no `sharedAcrName` key present.
- [x] Read `deploy-all.ps1` and `.github/workflows/deploy-dev.yml` for invocation pattern (deploy-all.ps1 is the bicep runner; deploy-dev.yml only does `az containerapp update`, never bicep).
- [x] Read canonical Gap 298 tracker entry (be_features_tracker.md, `## Open Items / Gaps`) — already documents the `invoice-llm` vs live `invoicellm` namingPrefix drift affecting identity/CAE/KeyVault, and the `stinvoicellmdev` vs live `stinvoicellmdev2` storage drift.
- [x] Add `sharedAcrName: acrinvoicellmdev2` to `params.dev.json`.
- [x] `az bicep build --file 08-apps.bicep` — 0 errors.
- [x] `az deployment group what-if -g rg-invoice-llm-dev -f 08-apps.bicep -p @params.dev.json -p @params.dev.secrets.json` — raw combined file fails outright with `InvalidTemplate` (params.dev.json/secrets carry keys `08-apps.bicep` doesn't declare, e.g. `networkIsolation`, `dbAdminPassword`), exactly the class of problem `deploy-all.ps1`'s own header comment documents. Rebuilt a params file filtered to the template's 42 declared param names (same filtering `deploy-all.ps1`'s `New-StageParamArgs`/`Get-DeclaredParamNames` does) and re-ran: confirmed `registries[].server` resolves to `acrinvoicellmdev2.azurecr.io` on all 5 apps/jobs that carry one, no diff vs. live. Ran a second what-if with `sharedAcrName` removed as a causality check — all 5 flip to the broken `acrinvoicellmdev.azurecr.io`, isolating the fix's effect. All scratch/temp what-if files deleted after use, not committed.
- [x] Read-only comparison: `az resource list -g rg-invoice-llm-dev` vs. 08-apps.bicep's namingPrefix-derived vars (identityName, caeName, keyVaultName, openaiName, docIntelName, storageAccountName, appInsightsName) — confirm which are wrong live.
- [x] Update canonical Gap 298 tracker entry — additive only — noting ACR half fixed-on-disk-not-deployed, other drift still open pending founder review.
- [x] Report findings in chat (no reports/infra/ file).

Final status: ACR params fix applied to params.dev.json only, bicep build clean, what-if confirms sharedAcrName now resolves to acrinvoicellmdev2 (no accidental change to the pre-existing 4-modify/3-create what-if drift caused by namingPrefix/backendImage, which remain untouched/open). Read-only audit found identity/CAE/KeyVault/OpenAI/DocIntel names are ALL wrong against live Azure (same invoice-llm vs invoicellm namingPrefix drift already on record in Gap 298's canonical entry) — not a new finding, but now independently reconfirmed via az resource list. Tracker updated additively. No Stage 8 deploy was run.
