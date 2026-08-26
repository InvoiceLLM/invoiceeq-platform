targetScope = 'resourceGroup'

// ============ Gap 297: Monitoring Reader + Cost Management Reader, and nothing else ============
//
// Why this file exists instead of just redeploying Stage 7
// ----------------------------------------------------------
// `modules/security/rbac-assignments.bicep` already declares both role
// assignments this template creates -- they were added there on 2026-08-23
// (Feature 20 Area 1 / Feature 24) but a Stage 7 (`07-rbac.bicep`) redeploy has
// never actually been run against dev. Stage 7 is not a safe way to create
// them now: it derives `storageAccountName` as
// `st${replace(namingPrefix, '-', '')}${environment}` -> `stinvoicellmdev`
// (namingPrefix default `invoice-llm`), but the live storage account is
// `stinvoicellmdev2` -- the `2` is not derivable from any Stage 7 parameter.
// A plain Stage 7 redeploy therefore either fails resolving the storage
// account (`existing` resource lookup on a name that doesn't exist) or,
// worse, drifts every other resource name Stage 7 computes with the same
// hyphen/no-hyphen mismatch (see `benchmark-eval-job-only.bicep`'s header for
// the same class of drift). Do not attempt a Stage 7 redeploy for this gap.
//
// So this file does what `workbook-cost-health-only.bicep` and
// `benchmark-eval-job-only.bicep` already did for the same class of problem:
// create just the missing resource(s) -- here, two role assignments -- by
// referencing the identity that already exists under its real, live name,
// rather than re-deriving names from possibly-drifted naming-prefix params.
//
// This template creates exactly two resources (role assignments) and
// modifies nothing else. Role definition IDs are copied verbatim from
// `modules/security/rbac-assignments.bicep` (not re-derived) -- see that
// file's comments for how each GUID was verified against this subscription
// on 2026-08-23 via `az role definition list --name "..."` rather than
// copied from documentation.
//
//   az bicep build --file infra/rbac-monitoring-cost-only.bicep
//   az deployment group what-if --resource-group rg-invoice-llm-dev \
//     --template-file infra/rbac-monitoring-cost-only.bicep
//   az deployment group create   --resource-group rg-invoice-llm-dev \
//     --template-file infra/rbac-monitoring-cost-only.bicep
//
// Scope: both roles are assigned at this resource group's scope, identical to
// how `rbac-assignments.bicep` assigns them (no `scope:` override there means
// the deployment's own resource group) -- not broadened to subscription
// scope. See that module's comments for why RG scope is believed sufficient
// for both `services/azure_cost.py` (Cost Management) and the Resource
// Graph / action-group reads the ops-recommendation pass needs (Monitoring
// Reader), and what to check first if a live run ever suggests it isn't.

@description('Managed identity resource name. Defaults to the real, live dev identity name -- not derived from a naming-prefix/environment param pair, since this environment was built with `invoicellm` (no hyphen) while some params default to `invoice-llm`.')
param identityName string = 'id-invoicellm-dev'

// Role Definition IDs -- copied verbatim from modules/security/rbac-assignments.bicep,
// not re-derived. See that file for the verification note on each.
var costManagementReader = '72fafb9e-0641-4937-9268-a91bfd8191a3'
var monitoringReader = '43d0d8ad-25c7-4714-9337-8ba259a9fe05'

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: identityName
}

// RBAC for Cost Management (Feature 20 Area 1 -- `apps/invoice-be/services/azure_cost.py`)
// RG-scoped: Cost Management has no per-resource scope to grant on.
resource costManagementRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(identity.id, resourceGroup().id, costManagementReader)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', costManagementReader)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// Monitoring Reader -- Azure Resource Graph (alertsmanagementresources) +
// Azure Monitor action-group reads for the workbook-recommendation pass
// (Gap 318's container_health category) and any future in-codebase
// monitoring job. RG-scoped, matching the Cost Management assignment above.
resource monitoringReaderRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(identity.id, resourceGroup().id, monitoringReader)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', monitoringReader)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

output identityPrincipalId string = identity.properties.principalId
output costManagementRoleAssignmentId string = costManagementRoleAssignment.id
output monitoringReaderRoleAssignmentId string = monitoringReaderRoleAssignment.id
