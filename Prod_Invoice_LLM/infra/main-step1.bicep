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
param azureOpenAiEndpoint string = ''

@description('Azure OpenAI Model Deployment Name')
param azureOpenAiDeploymentName string = ''

@description('Azure OpenAI Model Version')
param azureOpenAiModelVersion string = ''

@description('Azure Document Intelligence Endpoint URL')
param azureDocIntelEndpoint string = ''

@description('Image tag for backend API container')
param backendImage string = ''

@description('Image tag for queue worker container')
param queueWorkerImage string = ''

@description('Image tag for frontend container')
param frontendImage string = ''

@description('Whether to deploy Redis (skip if already exists due to ARM bug)')
param deployRedis bool = true

// ================= Variables =================
var uniqueSuffix = uniqueString(resourceGroup().id)
var keyVaultName = 'kv-${namingPrefix}-${environment}-${substring(uniqueSuffix, 0, 4)}'
var storageAccountName = 'st${replace(namingPrefix, '-', '')}${environment}'
var acrName = 'acr${replace(namingPrefix, '-', '')}${environment}'
var vnetName = 'vnet-${namingPrefix}-${environment}'

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

// ================= 3. Data Services =================
module postgresql './modules/data/postgresql.bicep' = {
  name: 'postgresql-deploy'
  params: {
    location: location
    serverName: 'psql-${namingPrefix}-${environment}'
    adminLogin: dbAdminLogin
    adminPassword: dbAdminPassword
    subnetId: network.outputs.postgresSubnetId
    privateDnsZoneId: network.outputs.postgresDnsZoneId
  }
}

module redis './modules/data/redis.bicep' = if (deployRedis) {
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
    queueDnsZoneId: network.outputs.queueDnsZoneId
  }
}

module acr './modules/data/acr.bicep' = {
  name: 'acr-deploy'
  params: {
    location: location
    acrName: acrName
    subnetId: network.outputs.dataSubnetId
    privateDnsZoneId: network.outputs.acrDnsZoneId
  }
}

// ================= 4. Azure Key Vault =================
module keyVault './modules/security/keyvault.bicep' = {
  name: 'keyvault-deploy'
  params: {
    location: location
    keyVaultName: keyVaultName
    // Initial secret seeding
    dbAdminPassword: dbAdminPassword
    clerkSecretKey: clerkSecretKey
    tokenEncryptionKey: tokenEncryptionKey
    databaseUrl: 'postgresql://${dbAdminLogin}:${uriComponent(dbAdminPassword)}@${postgresql.outputs.fqdn}:5432/invoice_db?sslmode=require'
    redisUrl: deployRedis ? 'rediss://:${uriComponent(redis.outputs.primaryKey)}@${redis.outputs.host}:${redis.outputs.port}/0' : ''
    azureStorageConnectionString: 'DefaultEndpointsProtocol=https;AccountName=${storageAccountName};AccountKey=${listKeys(resourceId('Microsoft.Storage/storageAccounts', storageAccountName), '2023-01-01').keys[0].value};EndpointSuffix=core.windows.net'
  }
  dependsOn: [
    storage
  ]
}

// ================= Outputs =================
output keyVaultName string = keyVaultName
output identityId string = identities.outputs.identityId
output identityClientId string = identities.outputs.clientId
output vnetName string = vnetName
output storageAccountName string = storageAccountName
output acrName string = acrName
