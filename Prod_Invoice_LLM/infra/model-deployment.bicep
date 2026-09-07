targetScope = 'resourceGroup'

// Gap 465 (2026-09-05). Narrow, standalone deployment of ONE model deployment
// under an EXISTING Azure OpenAI account. Replaces `gpt4o-deployment.bicep`,
// which hardcoded both the account (`openai-invoicellm-dev`) and the model
// (`gpt-4o`) and so could neither target prod nor deploy a candidate.
//
// Not routed through 08-apps.bicep for the same reason its predecessor was
// not: that file's image params are stale relative to what CI/CD has running,
// so a full deploy risks rolling live container apps back. This file touches
// only the OpenAI account, which 08-apps.bicep does not own.
//
// Typical use (Feature 6.1 A2 / migration plan step 3 -- deploy GPT-5.6 Luna
// as the `fast` deployment on dev):
//
//   az deployment group create -g rg-invoice-llm-dev -f model-deployment.bicep \
//     -p openaiAccountName=openai-invoicellm-dev deploymentName=gpt-5.6-luna \
//        modelName=gpt-5.6-luna modelVersion=2026-07-09 capacity=100
//
// Availability was verified 2026-09-05 with
//   az cognitiveservices account list-models -n openai-invoicellm-dev -g rg-invoice-llm-dev
// -> gpt-5.6-luna / gpt-5.6-terra / gpt-5.6-sol, version 2026-07-09, GlobalStandard.
//
// ROLES ON DEV, as of 2026-09-06 (Feature 29 task 29.1; decisions 2 and 9).
// Corrected here because the previous version of this comment said Terra had
// been deleted, and it had not been:
//
//   gpt-5.6-luna   primary + fast + the attachment-branch narrator (16/16 on the
//                  16-turn probe after Gaps 470/472/473/475/476).
//   gpt-5-mini     judge, and the FULL-RECORD chat narrator (decision 2:
//                  22.2% -> 52.8% on the golden set with full records, vs Luna's
//                  27.8% -> 37.1%). `AZURE_OPENAI_CHAT_SUMMARY_DEPLOYMENT_NAME`.
//   gpt-5.6-terra  KEPT (decision 9) as the `long_doc` candidate until task 29.10
//                  runs `tests/golden_long_doc.json` on Terra vs Luna and the
//                  2-point rule picks one. `AZURE_OPENAI_LONG_DOC_DEPLOYMENT_NAME`
//                  is unset, so the role currently falls back to fast and Terra
//                  serves no live traffic -- it is a candidate, not a default.
//   gpt-4o         legacy, retiring; kept only so historical rows still price.
//
// DELETED after the matrix: gpt-5.6-sol and gpt-6-astra. Verified 2026-09-06
// with `az cognitiveservices account deployment list -n openai-invoicellm-dev
// -g rg-invoice-llm-dev` -> gpt-5-mini, gpt-4o, gpt-5.6-luna, gpt-5.6-terra and
// nothing else. Their `utils/model_registry.py` catalog rows are deliberately
// KEPT and marked DELETED: historical telemetry and cost rows still have to
// price, and removing a row would silently reprice them at zero.
//
// The deployment name is what the app reads (`AZURE_OPENAI_DEPLOYMENT_NAME`,
// `AZURE_OPENAI_FAST_DEPLOYMENT_NAME`, `AZURE_OPENAI_JUDGE_DEPLOYMENT_NAME`,
// `AZURE_OPENAI_CHAT_SUMMARY_DEPLOYMENT_NAME`,
// `AZURE_OPENAI_LONG_DOC_DEPLOYMENT_NAME`); `utils/model_registry.py` maps it to
// context/price by longest-prefix match, so keep the deployment name starting
// with the model name.

@description('Existing Azure OpenAI account in this resource group.')
param openaiAccountName string

@description('Deployment name as the app will reference it. Keep it prefixed with the model name so utils/model_registry.py can classify it.')
param deploymentName string

@description('OpenAI model name, e.g. gpt-5.6-luna. Verify with: az cognitiveservices account list-models -n <account> -g <rg> -o table')
param modelName string

@description('Model version string, e.g. 2026-07-09. Do not guess; read it from list-models.')
param modelVersion string

@description('SKU name.')
@allowed([
  'GlobalStandard'
  'DataZoneStandard'
  'Standard'
])
param skuName string = 'GlobalStandard'

@description('Tokens-per-minute capacity in thousands (100 = 100K TPM). A live `az cognitiveservices account deployment update` that changes this must be written back here or the next bicep run silently reverts it.')
param capacity int = 100

resource openaiAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: openaiAccountName
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: openaiAccount
  name: deploymentName
  sku: {
    name: skuName
    capacity: capacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: modelName
      version: modelVersion
    }
  }
}

output deploymentName string = modelDeployment.name
output modelName string = modelName
output modelVersion string = modelVersion
