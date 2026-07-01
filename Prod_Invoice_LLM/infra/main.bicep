targetScope = 'resourceGroup'

// ================= Parameters =================
@description('Deployment environment (e.g. dev, uat, prod)')
param environment string = 'dev'

@description('Azure region for resource provisioning')
param location string = resourceGroup().location

@description('Prefix for resource naming')
param namingPrefix string = 'invoice-llm'

@description('Admin login name for PostgreSQL')
param dbAdminLogin string = 'dbadmin'

@description('Secure admin password for PostgreSQL')
@secure()
param dbAdminPassword string

@description('Clerk SSO API Secret Key')
@secure()
param clerkSecretKey string

@description('Clerk SSO Publishable Client Key')
param nextPublicClerkPublishableKey string

@description('AES-256 Fernet key for token encryption')
@secure()
param tokenEncryptionKey string

@description('Azure OpenAI Endpoint URL')
param azureOpenAiEndpoint string

@description('Azure OpenAI Key')
@secure()
param azureOpenAiApiKey string

@description('Azure OpenAI Model Deployment Name')
param azureOpenAiDeploymentName string = 'gpt-4o-mini'

@description('Azure Document Intelligence Endpoint URL')
param azureDocIntelEndpoint string

@description('Azure Document Intelligence Secret Key')
@secure()
param azureDocIntelKey string

@description('Image tag for backend API container')
param backendImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('Image tag for celery worker container')
param celeryWorkerImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

@description('Image tag for frontend container')
param frontendImage string = 'mcr.microsoft.com/azuredocs/aci-helloworld:latest'

// ================= Variables =================
var uniqueSuffix = uniqueString(resourceGroup().id)
var keyVaultName = 'kv-${namingPrefix}-${environment}-${substring(uniqueSuffix, 0, 4)}'
var storageAccountName = 'st${replace(namingPrefix, '-', '')}${environment}'
var vnetName = 'vnet-${namingPrefix}-${environment}'
var caeName = 'cae-${namingPrefix}-${environment}'

// ================= 1. Managed Identities =================
module identities './modules/security/managed-identities.bicep' = {
  name: 'managed-identities-deploy'
  params: {
    location: location
    identityName: 'id-${namingPrefix}-${environment}'
  }
}

// ================= 2. Virtual Network & NSGs =================
module network './modules/network/vnet.bicep' = {
  name: 'network-deploy'
  params: {
    location: location
    vnetName: vnetName
  }
}

// ================= 3. Azure Key Vault =================
module keyVault './modules/security/keyvault.bicep' = {
  name: 'keyvault-deploy'
  params: {
    location: location
    keyVaultName: keyVaultName
    managedIdentityPrincipalId: identities.outputs.principalId
    // Initial secret seeding
    dbAdminPassword: dbAdminPassword
    clerkSecretKey: clerkSecretKey
    tokenEncryptionKey: tokenEncryptionKey
    azureOpenAiApiKey: azureOpenAiApiKey
    azureDocIntelKey: azureDocIntelKey
  }
}

// ================= 4. Data Services =================
module postgresql './modules/data/postgresql.bicep' = {
  name: 'postgresql-deploy'
  params: {
    location: location
    serverName: 'psql-${namingPrefix}-${environment}'
    adminLogin: dbAdminLogin
    adminPassword: dbAdminPassword
    subnetId: network.outputs.dataSubnetId
    privateDnsZoneId: network.outputs.postgresDnsZoneId
  }
}

module redis './modules/data/redis.bicep' = {
  name: 'redis-deploy'
  params: {
    location: location
    redisName: 'redis-${namingPrefix}-${environment}'
    subnetId: network.outputs.dataSubnetId
    privateDnsZoneId: network.outputs.redisDnsZoneId
  }
}

module storage './modules/data/storage.bicep' = {
  name: 'storage-deploy'
  params: {
    location: location
    storageAccountName: storageAccountName
    subnetId: network.outputs.dataSubnetId
    privateDnsZoneId: network.outputs.storageDnsZoneId
  }
}

// ================= 5. Cognitive & AI Services =================
module openai './modules/ai/openai.bicep' = {
  name: 'openai-deploy'
  params: {
    location: location
    openaiName: 'oai-${namingPrefix}-${environment}'
    deploymentName: azureOpenAiDeploymentName
    subnetId: network.outputs.aiSubnetId
    privateDnsZoneId: network.outputs.openaiDnsZoneId
  }
}

module docIntelligence './modules/ai/doc-intelligence.bicep' = {
  name: 'docintel-deploy'
  params: {
    location: location
    docIntelName: 'docintel-${namingPrefix}-${environment}'
    subnetId: network.outputs.aiSubnetId
    privateDnsZoneId: network.outputs.docIntelDnsZoneId
  }
}

// ================= 6. Container Apps Environment =================
module containerEnv './modules/compute/container-env.bicep' = {
  name: 'container-env-deploy'
  params: {
    location: location
    caeName: caeName
    subnetId: network.outputs.acaSubnetId
  }
}

// ================= 7. Vector Database (ChromaDB Container) =================
module chromadb './modules/data/chromadb.bicep' = {
  name: 'chromadb-deploy'
  params: {
    location: location
    caeId: containerEnv.outputs.caeId
    appName: 'ca-chromadb-${environment}'
  }
}

// ================= 8. Compute Layer (Stateless Containers) =================
module backendApp './modules/compute/invoice-be.bicep' = {
  name: 'backend-deploy'
  params: {
    location: location
    caeId: containerEnv.outputs.caeId
    appName: 'ca-invoice-be-${environment}'
    userAssignedIdentityId: identities.outputs.identityId
    userAssignedIdentityClientId: identities.outputs.clientId
    keyVaultName: keyVaultName
    // Settings
    chromaHost: chromadb.outputs.internalFqdn
    azureOpenAiEndpoint: azureOpenAiEndpoint
    azureOpenAiDeploymentName: azureOpenAiDeploymentName
    azureDocIntelEndpoint: azureDocIntelEndpoint
    image: backendImage
  }
}

module celeryWorker './modules/compute/celery-worker.bicep' = {
  name: 'worker-deploy'
  params: {
    location: location
    caeId: containerEnv.outputs.caeId
    appName: 'ca-celery-worker-${environment}'
    userAssignedIdentityId: identities.outputs.identityId
    userAssignedIdentityClientId: identities.outputs.clientId
    keyVaultName: keyVaultName
    // Settings
    chromaHost: chromadb.outputs.internalFqdn
    azureOpenAiEndpoint: azureOpenAiEndpoint
    azureOpenAiDeploymentName: azureOpenAiDeploymentName
    azureDocIntelEndpoint: azureDocIntelEndpoint
    image: celeryWorkerImage
  }
}

module frontendApp './modules/compute/invoice-fe.bicep' = {
  name: 'frontend-deploy'
  params: {
    location: location
    caeId: containerEnv.outputs.caeId
    appName: 'ca-invoice-fe-${environment}'
    userAssignedIdentityId: identities.outputs.identityId
    userAssignedIdentityClientId: identities.outputs.clientId
    keyVaultName: keyVaultName
    // Settings
    backendApiUrl: backendApp.outputs.fqdn
    nextPublicClerkPublishableKey: nextPublicClerkPublishableKey
    image: frontendImage
  }
}

// ================= 9. RBAC Assignments =================
module rbacAssignments './modules/security/rbac-assignments.bicep' = {
  name: 'rbac-assignments-deploy'
  params: {
    identityPrincipalId: identities.outputs.principalId
    storageAccountName: storage.outputs.storageAccountName
    openaiName: 'oai-${namingPrefix}-${environment}'
    docIntelName: 'docintel-${namingPrefix}-${environment}'
  }
}

// ================= Outputs =================
output frontendUrl string = frontendApp.outputs.fqdn
output backendUrl string = backendApp.outputs.fqdn
