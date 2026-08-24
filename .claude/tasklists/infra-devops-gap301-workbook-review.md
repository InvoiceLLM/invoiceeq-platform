# infra-devops: Gap 301 alert fix + workbook manual-edit validation (2026-08-24)

- [x] Read CONVENTIONS.md, alert-rules.bicep, 09-monitoring.bicep, 08-apps.bicep to understand maxReplicas wiring pattern
- [x] Confirm params.dev.json/params.prod.json don't currently override MaxReplicas (deploy-all.ps1's New-StageParamArgs filters per-stage by declared param names) -- so new params are safe with bicep defaults only
- [x] Implement Gap 301: add backendMaxReplicas/workerMaxReplicas/frontendMaxReplicas/chromaDbMaxReplicas/websiteMaxReplicas params to alert-rules.bicep, thread maxReplicas into containerApps loop array, add `Replicas >= app.maxReplicas` as second AllOf criterion on cpuAlerts + memoryAlerts
- [x] Thread the same 5 params through 09-monitoring.bicep (declare + pass into alertRules module call)
- [x] `az bicep build` on alert-rules.bicep, 09-monitoring.bicep, workbook-cost-health-only.bicep
- [x] Validate cost_health_workbook.json (4 manual edits) is valid JSON structurally
- [x] Look for/re-derive an equivalent workbook-schema validation approach (710-template cross-check mentioned in tracker)
- [x] `az deployment group what-if` for 09-monitoring.bicep against rg-invoice-llm-dev (read-only) -- Succeeded, 22 Modify/22 Create/31 Ignore, all 10 CPU/memory alerts show the new ReplicasAtMax criterion
- [x] Update feature_20_observability_monitoring_alerts.md (Gap 301 fix, workbook edits, File Coordinates note)
- [x] Update feature_20_23_24_implementation_status.md (Gap 301 fixed-not-deployed, workbook manual-edit validation section)
- [x] Report back to user in chat with real command output; left everything uncommitted

Final status: done. Both alert-rules.bicep/09-monitoring.bicep (Gap 301) and cost_health_workbook.json's 4 manual edits verified structurally sound. Nothing deployed, nothing committed.
