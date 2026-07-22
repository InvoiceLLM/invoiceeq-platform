targetScope = 'resourceGroup'

// ================= Stage 8: Application Container Apps =================
// Backend, queue-worker, frontend. Depends on Stage 6 (CAE + ChromaDB)
// and Stage 7 (RBAC — so the identity can actually pull images / read
// secrets by the time these apps start). All cross-stage values (CAE id,
// ChromaDB FQDN, identity IDs, OpenAI/DocIntel endpoints) are read via
// `existing` resource references instead of being threaded through the
// orchestrator script as deployment outputs.

@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region for resource provisioning')
param location string = resourceGroup().location

@description('Prefix for resource naming')
param namingPrefix string = 'invoice-llm'

@description('Clerk SSO Publishable Client Key')
param nextPublicClerkPublishableKey string

@description('Azure OpenAI Model Deployment Name')
param azureOpenAiDeploymentName string = 'gpt-5-mini'

@description('Image tag for backend API container')
param backendImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('Image tag for queue worker container')
param queueWorkerImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('Image tag for frontend container')
param frontendImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

var identityName = 'id-${namingPrefix}-${environment}'
var caeName = 'cae-${namingPrefix}-${environment}'
var keyVaultName = 'kv-${namingPrefix}-${environment}'
var acrName = 'acr${replace(namingPrefix, '-', '')}${environment}'
var openaiName = 'openai-${namingPrefix}-${environment}'
var docIntelName = 'docintel-${namingPrefix}-${environment}'

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: identityName
}

resource cae 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: caeName
}

resource chromaDbApp 'Microsoft.App/containerApps@2024-03-01' existing = {
  name: 'ca-chromadb-${environment}'
}

resource openaiAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: openaiName
}

resource docIntelAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' existing = {
  name: docIntelName
}

module backendApp './modules/compute/invoice-be.bicep' = {
  name: 'backend-deploy'
  params: {
    location: location
    caeId: cae.id
    appName: 'ca-invoice-be-${environment}'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    chromaHost: chromaDbApp.properties.configuration.ingress.fqdn
    azureOpenAiEndpoint: openaiAccount.properties.endpoint
    azureOpenAiDeploymentName: azureOpenAiDeploymentName
    azureDocIntelEndpoint: docIntelAccount.properties.endpoint
    acrName: acrName
    image: backendImage
  }
}

module queueWorker './modules/compute/queue-worker.bicep' = {
  name: 'worker-deploy'
  params: {
    location: location
    caeId: cae.id
    appName: 'ca-queue-worker-${environment}'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    chromaHost: chromaDbApp.properties.configuration.ingress.fqdn
    azureOpenAiEndpoint: openaiAccount.properties.endpoint
    azureOpenAiDeploymentName: azureOpenAiDeploymentName
    azureDocIntelEndpoint: docIntelAccount.properties.endpoint
    acrName: acrName
    image: queueWorkerImage
  }
}

module frontendApp './modules/compute/invoice-fe.bicep' = {
  name: 'frontend-deploy'
  params: {
    location: location
    caeId: cae.id
    appName: 'ca-invoice-fe-${environment}'
    userAssignedIdentityId: identity.id
    userAssignedIdentityClientId: identity.properties.clientId
    keyVaultName: keyVaultName
    backendApiUrl: backendApp.outputs.fqdn
    nextPublicClerkPublishableKey: nextPublicClerkPublishableKey
    acrName: acrName
    image: frontendImage
  }
}

// ================= Outputs =================
output frontendUrl string = frontendApp.outputs.fqdn
output backendUrl string = backendApp.outputs.fqdn
