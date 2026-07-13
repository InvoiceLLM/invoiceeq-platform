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
    databaseUrl: 'postgresql://${dbAdminLogin}:${dbAdminPassword}@${postgresql.outputs.fqdn}:5432/invoice_db?sslmode=require'
    redisUrl: 'rediss://:${redis.outputs.primaryKey}@${redis.outputs.host}:${redis.outputs.port}/0'
  }
  dependsOn: [
    postgresql
    redis
  ]
}

// ================= Outputs =================
output keyVaultName string = keyVaultName
output identityId string = identities.outputs.identityId
output identityClientId string = identities.outputs.clientId
output vnetName string = vnetName
output storageAccountName string = storageAccountName
output acrName string = acrName
