targetScope = 'resourceGroup'

// Narrow, standalone deployment for ONE resource: a GPT-4o model deployment
// under the existing openai-invoicellm-dev Azure OpenAI account, for
// Feature 23's model-comparison work (see feature_23_ai_control_tower.md's
// 2026-08-23 section, "Model comparison" candidates table). Founder-approved
// 2026-08-23. Not routed through 08-apps.bicep for the same reason
// agent-eval-job-only.bicep wasn't -- that file's image params are stale
// relative to what CI/CD actually has running, so a full deploy risks
// rolling back live container apps to old images. This file only touches
// the OpenAI account, which 08-apps.bicep doesn't own anyway.
//
// Model/version verified live via `az cognitiveservices account
// list-models` 2026-08-23: gpt-4o 2024-11-20 is the latest GA version
// available in this resource's region, with GlobalStandard SKU offered.
// 2024-11-20 comfortably clears the 2024-08-06+ requirement for guaranteed
// strict-mode structured-output compliance (Microsoft Learn, checked the
// same day this deployment was scoped).

@description('Deployment name as it will be referenced by AZURE_OPENAI_DEPLOYMENT_NAME for test/comparison runs.')
param deploymentName string = 'gpt-4o'

@description('Model version.')
param modelVersion string = '2024-11-20'

@description('SKU/capacity type.')
param skuName string = 'GlobalStandard'

@description('Tokens-per-minute capacity, in thousands (i.e. 100 = 100K TPM).')
// Raised 10 -> 100 on 2026-09-03, at the founder\'s instruction, and the reason it
// is no longer "benchmark only": Feature 6.1 item A2 moves the four non-reasoning
// call sites of a chat turn -- `chat.classify`, `chat.sql_summary`,
// `chat.rag_answer` and Feature 26\'s attachment narration -- off the reasoning
// deployment (`gpt-5-mini`) and onto this one, because none of them reasons about
// anything: they route, phrase, or narrate work that deterministic code has
// already done.
//
// Why 10 was not enough, with the arithmetic: those four consume roughly 5K input
// tokens per turn (268 + 1,947 + 2,809 measured on 2026-09-03; narration
// unmeasured), so 10K TPM allows about **two turns per minute** before 429s. At
// 100K TPM it is about twenty, which is a dev-realistic ceiling.
//
// This value was changed live with `az cognitiveservices account deployment
// create` before it was written here. Keeping the two in step matters more than
// usual for this parameter: a bicep run that still said 10 would silently undo it
// and A2 would start returning 429s with no code change to explain it.
param capacity int = 100

resource openaiAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: 'openai-invoicellm-dev'
}

resource gpt4oDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: openaiAccount
  name: deploymentName
  sku: {
    name: skuName
    capacity: capacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o'
      version: modelVersion
    }
  }
}

output deploymentName string = gpt4oDeployment.name
