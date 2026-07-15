targetScope = 'resourceGroup'

// ================= Parameters =================
@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region for resource provisioning')
param location string = resourceGroup().location

@description('Prefix for resource naming')
param namingPrefix string = 'invoice-llm'

@description('Clerk SSO Publishable Client Key')
param nextPublicClerkPublishableKey string

@description('Azure OpenAI Endpoint URL')
param azureOpenAiEndpoint string

@description('Azure OpenAI Model Deployment Name')
param azureOpenAiDeploymentName string = 'gpt-5-mini'

@description('Azure Document Intelligence Endpoint URL')
param azureDocIntelEndpoint string

@description('Image tag for backend API container')
param backendImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('Image tag for queue worker container')
param queueWorkerImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('Image tag for frontend container')
param frontendImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'


@description('Identity ID from step1')
param identityId string

@description('Identity Client ID from step1')
param identityClientId string

@description('Key Vault name from step1')
param keyVaultName string

@description('Storage account name from step1')
param storageAccountName string

@description('ACR name from step1')
param acrName string

@description('CAE ID from step3')
param caeId string

@description('ChromaDB FQDN from step3')
param chromaDbFqdn string

// ================= Variables =================
var uniqueSuffix = uniqueString(resourceGroup().id)
var vnetName = 'vnet-${namingPrefix}-${environment}'

// Get VNet outputs from existing deployment
module network './modules/network/vnet.bicep' = {
  name: 'network-reference'
  params: {
    location: location
    vnetName: vnetName
  }
}

// ================= 1. RBAC Assignments =================
module rbacAssignments './modules/security/rbac-assignments.bicep' = {
  name: 'rbac-assignments-deploy'
  params: {
    identityPrincipalId: identityId
    storageAccountName: storageAccountName
    openaiName: 'openai-${namingPrefix}-${environment}'
    docIntelName: 'docintel-${namingPrefix}-${environment}'
    keyVaultName: keyVaultName
    acrName: acrName
  }
}

// ================= 2. Compute Layer (Stateless Containers) =================
module backendApp './modules/compute/invoice-be.bicep' = {
  name: 'backend-deploy'
  dependsOn: [
    rbacAssignments
  ]
  params: {
    location: location
    caeId: caeId
    appName: 'ca-invoice-be-${environment}'
    userAssignedIdentityId: identityId
    userAssignedIdentityClientId: identityClientId
    keyVaultName: keyVaultName
    // Settings
    chromaHost: chromaDbFqdn
    azureOpenAiEndpoint: azureOpenAiEndpoint
    azureOpenAiDeploymentName: azureOpenAiDeploymentName
    azureDocIntelEndpoint: azureDocIntelEndpoint
    acrName: acrName
    image: backendImage
  }
}

module queueWorker './modules/compute/queue-worker.bicep' = {
  name: 'worker-deploy'
  dependsOn: [
    rbacAssignments
  ]
  params: {
    location: location
    caeId: caeId
    appName: 'ca-queue-worker-${environment}'
    userAssignedIdentityId: identityId
    userAssignedIdentityClientId: identityClientId
    keyVaultName: keyVaultName
    // Settings
    chromaHost: chromaDbFqdn
    azureOpenAiEndpoint: azureOpenAiEndpoint
    azureOpenAiDeploymentName: azureOpenAiDeploymentName
    azureDocIntelEndpoint: azureDocIntelEndpoint
    acrName: acrName
    image: queueWorkerImage
  }
}

module frontendApp './modules/compute/invoice-fe.bicep' = {
  name: 'frontend-deploy'
  dependsOn: [
    rbacAssignments
  ]
  params: {
    location: location
    caeId: caeId
    appName: 'ca-invoice-fe-${environment}'
    userAssignedIdentityId: identityId
    userAssignedIdentityClientId: identityClientId
    keyVaultName: keyVaultName
    // Settings
    backendApiUrl: backendApp.outputs.fqdn
    nextPublicClerkPublishableKey: nextPublicClerkPublishableKey
    acrName: acrName
    image: frontendImage
  }
}

// ================= Outputs =================
output frontendUrl string = frontendApp.outputs.fqdn
output backendUrl string = backendApp.outputs.fqdn
